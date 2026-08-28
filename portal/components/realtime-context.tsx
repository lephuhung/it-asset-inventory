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
import type { MachineEvent } from "@/lib/types";

interface RealtimeContextValue {
  connected: boolean;
  /** Sự kiện máy gần nhất, mới nhất trước (tối đa 50). */
  events: MachineEvent[];
  lastEvent: MachineEvent | null;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

const MAX_EVENTS = 50;

function wsBase(): string {
  const configured = (process.env.NEXT_PUBLIC_WS_BASE ?? "").trim();
  if (configured) {
    // Tự động append `/api/ws` nếu user quên — backend WS route chỉ ở path này.
    const ws = configured.replace(/^http/, "ws");
    return ws.endsWith("/api/ws") ? ws : `${ws.replace(/\/$/, "")}/api/ws`;
  }
  return `${window.location.origin}/api/ws`.replace(/^http/, "ws");
}

/**
 * RealtimeProvider — kết nối WebSocket `/api/ws?token=...` của backend,
 * tự reconnect với backoff. Sự kiện máy (online/offline/lost) được giữ trong context.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<MachineEvent[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  const connect = useCallback(() => {
    let cancelled = false;
    (async () => {
      let token = "";
      try {
        const res = await fetch("/api/auth/ws-token", { cache: "no-store" });
        if (!res.ok) {
          throw new Error("no token");
        }
        token = ((await res.json()) as { token: string }).token;
      } catch {
        // Chưa đăng nhập — dừng, AuthProvider sẽ remount khi có phiên.
        return;
      }

      const url = `${wsBase()}?token=${encodeURIComponent(token)}`;
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