"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { SessionUser } from "@/lib/types";

interface AuthContextValue {
  user: SessionUser | null;
  /** Đang kiểm tra phiên lần đầu (guard hiện spinner). */
  loading: boolean;
  /** Tải lại phiên (sau login / bật 2FA). Trả true nếu có user. */
  refresh: () => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch("/api/auth/session", { cache: "no-store" });
      if (!res.ok) {
        setUser(null);
        return false;
      }
      const data = (await res.json()) as { user: SessionUser };
      setUser(data.user);
      return true;
    } catch {
      setUser(null);
      return false;
    }
  }, []);

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  // Lắng nghe sự kiện 401 từ api.ts (proxy đã refresh fail + clear cookie) → set user=null,
  // để layout redirect về /login tự động.
  useEffect(() => {
    const onExpired = () => {
      setUser(null);
    };
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      window.location.href = "/login";
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth phải dùng trong <AuthProvider>");
  return ctx;
}