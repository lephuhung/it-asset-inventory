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
import type { MachineEvent } from "@/lib/types";

interface RealtimeContextValue {
  connected: boolean;
  /** Sự kiện máy gần nhất, mới nhất trước (tối đa 50). */
  events: MachineEvent[];
  lastEvent: MachineEvent | null;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

const MAX_EVENTS = 50;

/** Chuyển `http://host:port` → `ws://host:port` (idempotent nếu đã là ws/wss). */
function toWs(origin: string): string {
  if (origin.startsWith("ws://") || origin.startsWith("wss://")) return origin;
  return origin.replace(/^http/, "ws");
}

/** Đảm bảo URL kết thúc bằng `/api/ws` (backend WS route duy nhất). */
function ensureApiWs(url: string): string {
  return url.endsWith("/api/ws") ? url : `${url.replace(/\/$/, "")}/api/ws`;
}

/**
 * Danh sách URL WebSocket ứng viên (thử lần lượt đến khi 1 URL connect được),
 * theo thứ tự ưu tiên:
 *  1. `NEXT_PUBLIC_WS_BASE` env var (override cho môi trường đặc biệt)
 *  2. `agent_server_url` từ `/api/agent-settings` — chính là backend API chứa
 *     route `/api/ws` (dev: http://<ip>:8000). ⚠️ NGUỒN CHÍNH: trước đây dùng
 *     `portal_url` làm WS base → trình duyệt kết nối WS tới chính Portal
 *     (Next.js dev server :3003, không có route /api/ws) → handshake fail →
 *     badge "Offline" kẹt vĩnh viễn dù backend WS vẫn hoạt động.
 *  3. `portal_url` từ `/api/agent-settings` — portal công khai (khi deploy có
 *     nginx proxy `/api/ws` sang backend — xem server/deploy/nginx/nginx.conf).
 *  4. `window.location.origin` (cùng nguồn — chỉ đúng nếu proxy có route WS).
 */
async function fetchWsCandidates(): Promise<string[]> {
  const push = (u: string | undefined | null, list: string[]) => {
    const v = (u ?? "").trim();
    if (v && !list.includes(v)) list.push(v);
  };
  const list: string[] = [];
  push(process.env.NEXT_PUBLIC_WS_BASE, list);
  try {
    const s = await api.get<{ agent_server_url?: string; portal_url?: string }>("/agent-settings");
    push(s.agent_server_url, list);
    push(s.portal_url, list);
  } catch {
    // Chưa đăng nhập hoặc lỗi — fall back.
  }
  push(window.location.origin, list);
  return list.map((u) => ensureApiWs(toWs(u)));
}

/**
 * RealtimeProvider — kết nối WebSocket `/api/ws?token=...` của backend,
 * tự reconnect với backoff. Sự kiện máy (online/offline/lost) được giữ trong context.
 *
 * URL lấy từ cấu hình agent (`agent_server_url` / `portal_url` trong /agent-config)
 * — không cần sửa .env khi đổi IP server. Nếu URL đầu không kết nối được,
 * tự động thử URL kế tiếp trong danh sách ứng viên (self-healing, không kẹt Offline).
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<MachineEvent[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  /** Chỉ số ứng viên URL đang thử — tăng lên mỗi lần handshake fail. */
  const candidateIdxRef = useRef(0);
  /** URL đã kết nối thành công — khóa lại để reconnect dùng đúng URL đó. */
  const lockedUrlRef = useRef<string | null>(null);

  const connect = useCallback(() => {
    let cancelled = false;
    (async () => {
      // Lấy token + danh sách WS base song song (cùng nguồn xác thực).
      const [tokenRes, candidates] = await Promise.all([
        fetch("/api/auth/ws-token", { cache: "no-store" }),
        fetchWsCandidates(),
      ]);
      if (cancelled) return;
      if (!tokenRes.ok) {
        // Chưa đăng nhập — dừng, AuthProvider sẽ remount khi có phiên.
        return;
      }
      const token = ((await tokenRes.json()) as { token: string }).token;

      if (candidates.length === 0) {
        // Phòng thủ: không có URL nào — thử lại sau (không để kẹt Offline).
        setTimeout(() => {
          if (!cancelled) connect();
        }, 5000);
        return;
      }

      // Chọn URL: ưu tiên URL đã connect thành công (nếu còn trong danh sách);
      // ngược lại thử lần lượt từng ứng viên (vòng tròn).
      let url: string;
      if (lockedUrlRef.current && candidates.includes(lockedUrlRef.current)) {
        url = lockedUrlRef.current;
      } else {
        lockedUrlRef.current = null;
        if (candidateIdxRef.current >= candidates.length) candidateIdxRef.current = 0;
        url = candidates[candidateIdxRef.current];
      }

      const ws = new WebSocket(`${url}?token=${encodeURIComponent(token)}`);
      socketRef.current = ws;
      let opened = false;

      ws.onopen = () => {
        opened = true;
        retryRef.current = 0;
        candidateIdxRef.current = candidates.indexOf(url);
        lockedUrlRef.current = url;
        setConnected(true);
      };
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data as string) as MachineEvent;
          if (data.type === "machine_event") {
            setEvents((prev) => [data, ...prev].slice(0, MAX_EVENTS));
          }
        } catch {
          // bỏ qua message lạ
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        if (!opened) {
          // Chưa từng mở → URL này không phục vụ WS, thử ứng viên kế tiếp.
          lockedUrlRef.current = null;
          candidateIdxRef.current += 1;
        }
        const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
        retryRef.current += 1;
        setTimeout(() => {
          if (!cancelled) connect();
        }, delay);
      };
      ws.onerror = () => ws.close();
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const cleanup = connect();
    return () => {
      cleanup();
      socketRef.current?.close();
    };
  }, [connect]);

  const lastEvent = events[0] ?? null;

  return (
    <RealtimeContext.Provider value={{ connected, events, lastEvent }}>
      {children}
    </RealtimeContext.Provider>
  );
}

export function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error("useRealtime phải dùng trong <RealtimeProvider>");
  return ctx;
}
