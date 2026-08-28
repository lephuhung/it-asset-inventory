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

/** Trả về base URL cho WebSocket, theo thứ tự ưu tiên:
 *  1. `NEXT_PUBLIC_WS_BASE` env var (override cho môi trường đặc biệt)
 *  2. `portal_url` từ `/api/agent-settings` (cùng nguồn với IP user cấu hình qua UI /agent-config)
 *  3. `window.location.origin` (mặc định — chỉ hoạt động nếu portal proxy có route WS hoặc nginx proxy WS)
 */
async function fetchWsBase(): Promise<string> {
  const configured = (process.env.NEXT_PUBLIC_WS_BASE ?? "").trim();
  if (configured) {
    return ensureApiWs(toWs(configured));
  }
  try {
    const s = await api.get<{ portal_url: string }>("/agent-settings");
    if (s.portal_url) {
      return ensureApiWs(toWs(s.portal_url));
    }
  } catch {
    // Chưa đăng nhập hoặc lỗi — fall back.
  }
  return ensureApiWs(toWs(window.location.origin));
}

/**
 * RealtimeProvider — kết nối WebSocket `/api/ws?token=...` của backend,
 * tự reconnect với backoff. Sự kiện máy (online/offline/lost) được giữ trong context.
 *
 * URL lấy từ `portal_url` trong agent config (cùng nguồn với cấu hình IP
 * ở /agent-config) — không cần sửa .env khi đổi IP server.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<MachineEvent[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  const connect = useCallback(() => {
    let cancelled = false;
    (async () => {
      // Lấy token + WS base song song (cùng nguồn xác thực).
      const [tokenRes, wsBase] = await Promise.all([
        fetch("/api/auth/ws-token", { cache: "no-store" }),
        fetchWsBase(),
      ]);
      if (cancelled) return;
      if (!tokenRes.ok) {
        // Chưa đăng nhập — dừng, AuthProvider sẽ remount khi có phiên.
        return;
      }
      const token = ((await tokenRes.json()) as { token: string }).token;

      const url = `${wsBase}?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      socketRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
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