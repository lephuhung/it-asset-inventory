"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu, ShieldAlert, Wifi, WifiOff } from "lucide-react";
import { AuthProvider, useAuth } from "@/components/auth-context";
import { RealtimeProvider, useRealtime } from "@/components/realtime-context";
import { ComplianceGate } from "@/components/compliance-gate";
import { Sidebar } from "@/components/sidebar";
import { Spinner } from "@/components/ui";

const TITLES: Array<[string, string]> = [
  ["/dashboard", "Dashboard tổng quan"],
  ["/machines", "Danh sách máy"],
  ["/ghost-machines", "Máy ma"],
  ["/tokens", "Token triển khai"],
  ["/reports", "Xuất báo cáo"],
  ["/eol", "Báo cáo Windows EOL"],
  ["/audit", "Audit log"],
  ["/users", "Quản trị tài khoản"],
  ["/security", "Bảo mật tài khoản"],
  ["/compliance", "Thông báo tuân thủ"],
];

function titleFor(pathname: string): string {
  if (pathname.startsWith("/machines/") && pathname !== "/machines") return "Chi tiết máy";
  return TITLES.find(([p]) => (p === "/dashboard" ? pathname === p : pathname.startsWith(p)))?.[1] ?? "Portal";
}

function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const { connected } = useRealtime();
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, router, pathname]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Đang kiểm tra phiên đăng nhập…" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="flex min-h-screen overflow-x-clip">
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200/80 bg-white/85 px-4 backdrop-blur-md sm:px-6">
          <button
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 lg:hidden"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Mở menu"
          >
            <Menu className="size-5" />
          </button>
          <h1 className="truncate text-sm font-semibold text-slate-800">{titleFor(pathname)}</h1>

          <div className="ml-auto flex items-center gap-2.5">
            {connected ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                <Wifi className="size-3.5" /> Realtime
              </span>
            ) : (
              <span
                className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500"
                title="Kết nối realtime bị ngắt — dữ liệu sẽ tự nạp định kỳ"
              >
                <WifiOff className="size-3.5" /> Offline
              </span>
            )}
            <span className="hidden items-center gap-2 text-xs text-slate-500 sm:flex">
              <span className="flex size-6 items-center justify-center rounded-full bg-slate-100 text-slate-500">
                <ShieldAlert className="size-3.5" />
              </span>
              {user.full_name}
            </span>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1320px] min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>

        <footer className="border-t border-slate-200 px-6 py-3 text-center text-[11px] text-slate-400">
          Hệ thống quản lý tài sản máy tính — agent read-only, không giám sát cá nhân (mục 6.6)
        </footer>
      </div>

      <ComplianceGate />
    </div>
  );
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <RealtimeProvider>
        <Shell>{children}</Shell>
      </RealtimeProvider>
    </AuthProvider>
  );
}