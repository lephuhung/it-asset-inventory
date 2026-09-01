"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  BellRing,
  Check,
  ExternalLink,
  History,
  Loader2,
  Plus,
  SendHorizontal,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertTemplate, NotificationOut, Organization } from "@/lib/types";
import { formatDateTime, timeAgo } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Select,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import { useNotifications, SEVERITY_BADGES } from "@/components/notification-bell";
import SubscriptionsTab from "./SubscriptionsTab";
import TemplatesTab from "./TemplatesTab";
import HistoryTab from "./HistoryTab";

type Tab = "subscriptions" | "templates" | "history";

const NOTIF_SEVERITY_OPTIONS = [
  { value: "info", label: "Info" },
  { value: "success", label: "Success" },
  { value: "warning", label: "Warning" },
  { value: "error", label: "Error" },
  { value: "critical", label: "Critical" },
];

const NOTIF_CATEGORY_OPTIONS = [
  { value: "message", label: "Tin nhắn" },
  { value: "investigation", label: "Điều tra" },
  { value: "alert", label: "Cảnh báo" },
  { value: "system", label: "Hệ thống" },
  { value: "machine", label: "Máy" },
  { value: "security", label: "Bảo mật" },
];

const NOTIF_RECIPIENT_OPTIONS = [
  { value: "admins", label: "Tất cả Admin (Super + Org)" },
  { value: "super", label: "Chỉ Super Admin" },
  { value: "org_admins", label: "Admin tổ chức (Org Admin)" },
  { value: "broadcast", label: "Toàn hệ thống (mọi người dùng)" },
];

export default function NotificationsAlertsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [tab, setTab] = useState<Tab>("subscriptions");
  const [templates, setTemplates] = useState<AlertTemplate[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);

  // ── Notification compose modal state ───────────────────────
  const { notifications, unreadCount, refresh, markAllRead, markRead, deleteOne } = useNotifications();
  const [composeOpen, setComposeOpen] = useState(false);
  const [notifTitle, setNotifTitle] = useState("");
  const [notifSeverity, setNotifSeverity] = useState("info");
  const [notifCategory, setNotifCategory] = useState("message");
  const [notifBody, setNotifBody] = useState("");
  const [notifLink, setNotifLink] = useState("");
  const [notifRecipient, setNotifRecipient] = useState("admins");
  const [sending, setSending] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composeDone, setComposeDone] = useState<string | null>(null);

  // ── History slide-over state ──────────────────────────────
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyTab, setHistoryTab] = useState<"all" | "read">("all");

  const loadTemplates = useCallback(() => {
    api.get<AlertTemplate[]>("/admin/alert-templates")
      .then((list) => setTemplates(Array.isArray(list) ? list : []))
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    loadTemplates();
    api.get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
    void refresh();
  }, [loadTemplates, refresh]);

  // ── Notification compose handlers ──────────────────────────
  const openCompose = () => {
    setNotifTitle("");
    setNotifSeverity("info");
    setNotifCategory("message");
    setNotifBody("");
    setNotifLink("");
    setNotifRecipient("admins");
    setComposeError(null);
    setComposeDone(null);
    setComposeOpen(true);
  };

  const sendNotification = async () => {
    if (!notifTitle.trim()) {
      setComposeError("Nhập tiêu đề thông báo");
      return;
    }
    setSending(true);
    setComposeError(null);
    setComposeDone(null);
    try {
      const payload = {
        title: notifTitle.trim(),
        severity: notifSeverity,
        category: notifCategory,
        body: notifBody.trim() || null,
        link: notifLink.trim() || null,
      };
      let res: { delivered_to: number };
      if (notifRecipient === "broadcast") {
        res = await api.post<{ delivered_to: number }>("/admin/notifications/broadcast", payload);
      } else {
        const role =
          notifRecipient === "admins"
            ? "admin"
            : notifRecipient === "super"
            ? "super_admin"
            : "org_admin";
        res = await api.post<{ delivered_to: number }>("/admin/notifications", {
          recipient_filter: { role },
          ...payload,
        });
      }
      setComposeDone(`Đã gửi tới ${res.delivered_to} người nhận.`);
      setNotifTitle("");
      setNotifBody("");
      setNotifLink("");
      setComposeOpen(false);
      void refresh();
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : "Gửi thất bại");
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    if (!composeDone) return;
    const t = setTimeout(() => setComposeDone(null), 6000);
    return () => clearTimeout(t);
  }, [composeDone]);

  // ESC đóng history panel
  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHistoryOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  // ── History list (computed) ───────────────────────────────
  const historyAll = notifications;
  const historyRead = useMemo(() => notifications.filter((n) => !!n.read_at), [notifications]);
  const visibleHistory = historyTab === "read" ? historyRead : historyAll;

  const tabs: Array<{ key: Tab; label: string; icon: React.ReactNode; show: boolean }> = [
    { key: "subscriptions", label: "Subscriptions", icon: <BellRing className="size-3.5" />, show: true },
    { key: "templates", label: "Templates", icon: <Bell className="size-3.5" />, show: isSuperAdmin },
    { key: "history", label: "Lịch sử", icon: <History className="size-3.5" />, show: true },
  ];

  return (
    <div>
      <PageHeader
        title="Thông báo & Cảnh báo"
        description="Mẫu alert · Phạm vi · Người nhận — quản lý theo 3 trục"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)}>
              <History className="size-3.5" /> Lịch sử thông báo
              {unreadCount > 0 && (
                <Badge className="ml-1 bg-brand-50 text-brand-700 ring-brand-600/20">
                  {unreadCount} mới
                </Badge>
              )}
            </Button>
            {isSuperAdmin && (
              <Button size="sm" onClick={openCompose}>
                <Plus className="size-3.5" /> Tạo thông báo
              </Button>
            )}
          </div>
        }
      />

      {composeDone && (
        <div className="mb-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" />
          {composeDone}
        </div>
      )}

      {/* Tab strip — underline tabs theo Design.md: chrome im lặng (hairline),
          tab active đánh dấu bằng ĐÚNG MỘT vạch primary (màu cấu trúc duy nhất),
          label active = ink đậm, tab khác = stone. */}
      <div className="mb-6 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Thông báo & Cảnh báo">
        {tabs.filter((t) => t.show).map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
              tab === t.key
                ? "border-brand-600 text-slate-900"
                : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
            }`}
          >
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      {tab === "subscriptions" && <SubscriptionsTab isSuperAdmin={isSuperAdmin} templates={templates} orgs={orgs} />}
      {tab === "templates" && <TemplatesTab templates={templates} onReload={loadTemplates} />}
      {tab === "history" && <HistoryTab />}

      {/* ── Slide-over: lịch sử thông báo ─────────────────────── */}
      {historyOpen && (
        <div
          className="fixed inset-0 z-40 flex justify-end"
          role="dialog"
          aria-modal="true"
          aria-labelledby="history-title"
        >
          <div
            className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
            onClick={() => setHistoryOpen(false)}
          />
          <div className="relative z-10 flex h-full w-full max-w-md flex-col bg-white shadow-2xl">
            <header className="flex items-center justify-between gap-3 border-b border-slate-100 bg-white/95 px-5 py-4 backdrop-blur">
              <div className="min-w-0">
                <h2 id="history-title" className="text-[15px] font-semibold text-slate-800">
                  Lịch sử thông báo
                </h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Tất cả {historyAll.length} · Đã đọc {historyRead.length} · Chưa đọc {unreadCount}
                </p>
              </div>
              <IconButton
                label="Đóng"
                onClick={() => setHistoryOpen(false)}
                className="hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="size-4" />
              </IconButton>
            </header>

            {/* Tab strip — cùng pattern underline như tab chính */}
            <div className="flex items-center gap-1 border-b border-slate-200 px-5" role="tablist" aria-label="Lọc lịch sử thông báo">
              <button
                role="tab"
                aria-selected={historyTab === "all"}
                onClick={() => setHistoryTab("all")}
                className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
                  historyTab === "all"
                    ? "border-brand-600 text-slate-900"
                    : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
                }`}
              >
                <Bell className="size-3.5" />
                Tất cả
                <span className="text-xs text-slate-400">({historyAll.length})</span>
              </button>
              <button
                role="tab"
                aria-selected={historyTab === "read"}
                onClick={() => setHistoryTab("read")}
                className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
                  historyTab === "read"
                    ? "border-brand-600 text-slate-900"
                    : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
                }`}
              >
                <Check className="size-3.5" />
                Đã xem
                <span className="text-xs text-slate-400">({historyRead.length})</span>
              </button>

              {historyTab === "all" && unreadCount > 0 && (
                <button
                  onClick={() => void markAllRead()}
                  className="ml-auto text-xs font-medium text-brand-600 hover:underline"
                >
                  Đánh dấu tất cả đã đọc
                </button>
              )}
            </div>

            {/* List */}
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
              {visibleHistory.length === 0 ? (
                <EmptyState
                  icon={<Bell className="size-8" />}
                  title={historyTab === "read" ? "Chưa có thông báo đã đọc" : "Chưa có thông báo"}
                  description={
                    historyTab === "read"
                      ? "Các thông báo bạn đã đọc sẽ xuất hiện ở đây."
                      : "Notification sẽ xuất hiện khi có sự kiện: investigation xong, máy offline, alert security…"
                  }
                />
              ) : (
                <ul className="space-y-2">
                  {visibleHistory.map((n) => (
                    <HistoryRow
                      key={n.id}
                      n={n}
                      onOpen={() => {
                        if (!n.read_at) void markRead(n.id);
                        setHistoryOpen(false);
                        if (n.link) router.push(n.link);
                      }}
                      onDelete={() => void deleteOne(n.id)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: tạo / push notification ── */}
      <Modal
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        title="Gửi thông báo tới Admin"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setComposeOpen(false)} disabled={sending}>
              Hủy
            </Button>
            <Button onClick={sendNotification} disabled={sending || !notifTitle.trim()}>
              {sending ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <SendHorizontal className="size-3.5" />
              )}
              Gửi thông báo
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {composeError && <ErrorBanner message={composeError} />}

          <Field
            label="Đối tượng nhận"
            hint="Admin gửi — chọn nhóm người nhận. Người gửi không nhận được thông báo của chính mình."
          >
            <Select value={notifRecipient} onChange={(e) => setNotifRecipient(e.target.value)}>
              {NOTIF_RECIPIENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Tiêu đề" required>
            <Input
              value={notifTitle}
              onChange={(e) => setNotifTitle(e.target.value)}
              placeholder="VD: Bảo trì hệ thống đêm nay 22:00–23:00"
              maxLength={200}
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Mức độ">
              <Select value={notifSeverity} onChange={(e) => setNotifSeverity(e.target.value)}>
                {NOTIF_SEVERITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Loại">
              <Select value={notifCategory} onChange={(e) => setNotifCategory(e.target.value)}>
                {NOTIF_CATEGORY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field
            label="Nội dung"
            hint="Hiển thị trong dropdown chuông thông báo và trang này."
          >
            <textarea
              rows={3}
              value={notifBody}
              onChange={(e) => setNotifBody(e.target.value)}
              placeholder="Chi tiết thông báo…"
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm transition-colors placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30"
            />
          </Field>

          <Field
            label="Link (tùy chọn)"
            hint="VD /machines hoặc /admin/llm-dfir/investigations — bấm thông báo sẽ chuyển tới đó."
          >
            <Input
              value={notifLink}
              onChange={(e) => setNotifLink(e.target.value)}
              placeholder="/dashboard"
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

// ── History slide-over row ──────────────────────────────────
function HistoryRow({
  n,
  onOpen,
  onDelete,
}: {
  n: NotificationOut;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const sev = (n.severity || "info").toLowerCase();
  const unread = !n.read_at;
  return (
    <li
      className={`group rounded-lg border border-slate-200 bg-white p-3 transition-colors hover:border-slate-300 ${
        unread ? "border-l-2 border-l-brand-600 bg-brand-50/30" : ""
      }`}
    >
      <div className="flex items-start gap-2">
        <button onClick={onOpen} className="min-w-0 flex-1 cursor-pointer text-left">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <Badge className={SEVERITY_BADGES[sev] ?? SEVERITY_BADGES.info}>{sev}</Badge>
            <span className="text-[11px] text-slate-500">{n.category}</span>
            {unread && (
              <span
                className="size-1.5 rounded-full bg-brand-600"
                aria-label="Chưa đọc"
              />
            )}
          </div>
          <div
            className={`text-sm ${
              unread ? "font-semibold text-slate-900" : "font-medium text-slate-700"
            }`}
          >
            {n.title}
          </div>
          {n.body && (
            <div className="mt-1 line-clamp-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
              {n.body}
            </div>
          )}
          <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-400">
            <span title={formatDateTime(n.created_at)}>{timeAgo(n.created_at)}</span>
            {n.link && (
              <span className="inline-flex items-center gap-0.5 font-medium text-brand-600">
                <ExternalLink className="size-3" /> có link
              </span>
            )}
          </div>
        </button>
        <IconButton
          label="Xoá thông báo"
          onClick={onDelete}
          className="shrink-0 opacity-60 hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100"
        >
          <Trash2 className="size-3.5" />
        </IconButton>
      </div>
    </li>
  );
}
