"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import type { NotificationOut } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { Bell, BellRing, Check, ExternalLink, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { Badge, ConfirmDialog, IconButton } from "@/components/ui";
import { useRealtimeEmitter } from "@/components/realtime-context";

/** Validate link investigation trước khi navigate — tránh 422 nếu link lỗi. */
function isValidInvestigationLink(link: string): boolean {
  // /admin/llm-dfir/investigations/{uuid}
  // /machines/{uuid}
  const investigationMatch = link.match(/^\/admin\/llm-dfir\/investigations\/([0-9a-f-]+)$/i);
  if (investigationMatch) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(investigationMatch[1]);
  }
  const machineMatch = link.match(/^\/machines\/([0-9a-f-]+)$/i);
  if (machineMatch) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(machineMatch[1]);
  }
  return true; // các link khác (dashboard, reports...) coi như OK
}

/* ── Severity styles dùng chung (đồng bộ bell ↔ trang /notifications) ──
   Pill tinted theo Design.md — màu đã remap trong globals.css:
   bad → rose · warn → amber · ok → emerald · info → blue (primary). */
export const SEVERITY_BADGES: Record<string, string> = {
  critical: "bg-rose-100 text-rose-700 ring-rose-600/20",
  error: "bg-rose-50 text-rose-800 ring-rose-600/20",
  warning: "bg-amber-100 text-amber-700 ring-amber-600/20",
  success: "bg-emerald-100 text-emerald-700 ring-emerald-600/20",
  info: "bg-blue-100 text-blue-700 ring-blue-600/20",
};

export const SEVERITY_ACCENTS: Record<string, string> = {
  critical: "border-rose-600",
  error: "border-rose-500",
  warning: "border-amber-500",
  success: "border-emerald-500",
  info: "border-blue-600",
};

interface NotificationContextValue {
  notifications: NotificationOut[];
  unreadCount: number;
  refresh: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  deleteOne: (id: string) => Promise<void>;
  toast: NotificationOut | null;
  dismissToast: () => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

/** Provider quản lý state + nhận realtime qua emitter của RealtimeProvider. */
export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [toast, setToast] = useState<NotificationOut | null>(null);
  const lastToastedIdRef = useRef<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, count] = await Promise.all([
        api.get<NotificationOut[]>("/notifications?limit=50"),
        api.get<{ total: number }>("/notifications/unread-count"),
      ]);
      setNotifications(list);
      setUnreadCount(count.total);
    } catch {
      // ignore — chưa login hoặc lỗi tạm thời
    }
  }, []);

  const markRead = useCallback(
    async (id: string) => {
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)),
      );
      setUnreadCount((c) => Math.max(0, c - 1));
      try {
        await api.patch(`/notifications/${id}/read`);
      } catch {
        // Optimistic fail → resync từ server để badge không nói dối
        void refresh();
      }
    },
    [refresh],
  );

  const markAllRead = useCallback(async () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })));
    setUnreadCount(0);
    try {
      await api.post("/notifications/mark-all-read", {});
    } catch {
      void refresh();
    }
  }, [refresh]);

  const deleteOne = useCallback(
    async (id: string) => {
      const n = notifications.find((x) => x.id === id);
      setNotifications((prev) => prev.filter((x) => x.id !== id));
      if (n && !n.read_at) setUnreadCount((c) => Math.max(0, c - 1));
      try {
        await api.delete(`/notifications/${id}`);
      } catch {
        void refresh();
      }
    },
    [notifications, refresh],
  );

  const dismissToast = useCallback(() => setToast(null), []);

  const showToast = useCallback((n: NotificationOut) => {
    lastToastedIdRef.current = n.id;
    setToast(n);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(null), 8000);
  }, []);

  // Poll lần đầu khi mount
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll định kỳ 60s — lưới an toàn khi WS không tới được (proxy chặn WS,
  // mạng họp...). Realtime chỉ là lớp tăng tốc, polling đảm bảo badge luôn đúng.
  useEffect(() => {
    const t = setInterval(() => {
      void refresh();
    }, 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  // Toast timer phải được clear khi unmount (trước đây bị rò timer)
  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  // Lắng nghe realtime từ WebSocket emitter (loại `notification:new`)
  const emitter = useRealtimeEmitter();
  useEffect(() => {
    if (!emitter) return;
    const handle = (raw: unknown) => {
      const data = raw as { notifications?: NotificationOut[] };
      const incoming = Array.isArray(data?.notifications) ? data.notifications : [];
      if (incoming.length === 0) return;
      // Chèn phần chưa có trong list (polling có thể đã nhặt trước đó)
      setNotifications((prev) => {
        const known = new Set(prev.map((n) => n.id));
        return [...incoming.filter((n) => !known.has(n.id)), ...prev].slice(0, 100);
      });
      setUnreadCount((c) => c + incoming.length);
      // Toast cho notification đầu tiên (chỉ khi severity >= warning)
      const first = incoming[0];
      if (
        first &&
        ["warning", "error", "critical"].includes(first.severity) &&
        lastToastedIdRef.current !== first.id
      ) {
        showToast(first);
      }
    };
    emitter.on("notification:new", handle);
    return () => emitter.off("notification:new", handle);
  }, [emitter, showToast]);

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount,
        refresh,
        markRead,
        markAllRead,
        deleteOne,
        toast,
        dismissToast,
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationContextValue {
  const ctx = useContext(NotificationContext);
  if (!ctx) {
    // SSR / không có provider — trả stub để không crash
    return {
      notifications: [],
      unreadCount: 0,
      refresh: async () => {},
      markRead: async () => {},
      markAllRead: async () => {},
      deleteOne: async () => {},
      toast: null,
      dismissToast: () => {},
    };
  }
  return ctx;
}

// ── Bell + dropdown ────────────────────────────────────────────

export function NotificationBell() {
  const { notifications, unreadCount, markRead, markAllRead, deleteOne } = useNotifications();
  const [open, setOpen] = useState(false);
  const [invalidLinkOpen, setInvalidLinkOpen] = useState(false);
  const router = useRouter();
  const wrapRef = useRef<HTMLDivElement>(null);

  // Click outside + Escape để đóng
  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const handleClick = (n: NotificationOut) => {
    if (!n.read_at) void markRead(n.id);
    if (n.link) {
      setOpen(false);
      // Validate UUID trong link trước khi navigate (tránh 422)
      if (!isValidInvestigationLink(n.link)) {
        setInvalidLinkOpen(true);
        return;
      }
      router.push(n.link);
    }
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative cursor-pointer rounded-full p-2 text-slate-500 transition-colors duration-150 motion-reduce:transition-none hover:bg-slate-100 hover:text-slate-700"
        title="Thông báo"
        aria-label={`Thông báo${unreadCount > 0 ? ` (${unreadCount} chưa đọc)` : ""}`}
        aria-expanded={open}
      >
        {unreadCount > 0 ? (
          <BellRing className="size-5 text-brand-600" />
        ) : (
          <Bell className="size-5" />
        )}
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-bold leading-none text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      <ConfirmDialog
        open={invalidLinkOpen}
        onClose={() => setInvalidLinkOpen(false)}
        onConfirm={() => setInvalidLinkOpen(false)}
        title="Liên kết không hợp lệ"
        confirmLabel="Đã hiểu"
        message="Liên kết trong thông báo này không còn hợp lệ — investigation có thể đã bị xoá hoặc link bị lỗi."
      />

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 flex max-h-[600px] w-96 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-semibold tracking-tight text-slate-800">Thông báo</span>
            {unreadCount > 0 && (
              <button
                onClick={() => void markAllRead()}
                className="inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
              >
                <Check className="size-3" /> Đánh dấu tất cả đã đọc
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                Chưa có thông báo nào
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {notifications.map((n) => {
                  const sev = (n.severity || "info").toLowerCase();
                  return (
                    <li
                      key={n.id}
                      className={`cursor-pointer p-3 transition-colors duration-150 motion-reduce:transition-none hover:bg-slate-50 ${
                        !n.read_at ? "bg-brand-50/40" : ""
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <button
                          onClick={() => handleClick(n)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="mb-1 flex items-center gap-2">
                            <Badge className={SEVERITY_BADGES[sev] ?? SEVERITY_BADGES.info}>
                              {sev}
                            </Badge>
                            <span className="text-xs text-slate-500">{n.category}</span>
                            {!n.read_at && (
                              <span className="size-1.5 shrink-0 rounded-full bg-brand-600" />
                            )}
                          </div>
                          <div
                            className={`line-clamp-2 text-sm ${
                              n.read_at ? "font-medium text-slate-700" : "font-semibold text-slate-900"
                            }`}
                          >
                            {n.title}
                          </div>
                          {n.body && (
                            <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">
                              {n.body}
                            </div>
                          )}
                          <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                            {n.source !== "user" && <span>via {n.source}</span>}
                            <span>{timeAgo(n.created_at)}</span>
                            {n.link && <ExternalLink className="size-3" />}
                          </div>
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            void deleteOne(n.id);
                          }}
                          className="shrink-0 cursor-pointer rounded-full p-1 text-slate-400 transition-colors duration-150 motion-reduce:transition-none hover:bg-rose-50 hover:text-rose-600"
                          title="Xoá"
                          aria-label="Xoá thông báo"
                        >
                          <X className="size-3.5" />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Toast popup (góc trên bên phải) ────────────────────────────
// Surface trắng + vạch severity trái + pill tinted — theo Design.md ex-toast.

export function NotificationToast() {
  const { toast, dismissToast } = useNotifications();
  if (!toast) return null;
  const sev = (toast.severity || "info").toLowerCase();
  const accent = SEVERITY_ACCENTS[sev] ?? SEVERITY_ACCENTS.info;
  return (
    <div className="fixed right-4 top-4 z-[100] max-w-sm">
      <div
        role="status"
        className={`rounded-xl border border-slate-200 border-l-4 bg-white p-3 shadow-lg ${accent}`}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2">
              <Badge className={SEVERITY_BADGES[sev] ?? SEVERITY_BADGES.info}>
                {toast.severity}
              </Badge>
              <span className="text-xs text-slate-400">{toast.category}</span>
            </div>
            <div className="text-sm font-semibold tracking-tight text-slate-900">
              {toast.title}
            </div>
            {toast.body && (
              <div className="mt-1 text-xs leading-relaxed text-slate-500">{toast.body}</div>
            )}
            {toast.link && (
              <a
                href={toast.link}
                onClick={dismissToast}
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 underline underline-offset-2 hover:text-brand-700"
              >
                Mở chi tiết <ExternalLink className="size-3" />
              </a>
            )}
          </div>
          <IconButton label="Đóng" onClick={dismissToast} className="hover:bg-slate-100 hover:text-slate-600">
            <X className="size-4" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
