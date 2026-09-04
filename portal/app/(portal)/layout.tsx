"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu, Wifi, WifiOff } from "lucide-react";
import { AuthProvider, useAuth } from "@/components/auth-context";
import { RealtimeProvider, useRealtimeStatus } from "@/components/realtime-context";
import { NotificationProvider, NotificationBell, NotificationToast } from "@/components/notification-bell";
import { ComplianceGate } from "@/components/compliance-gate";
import { PasswordChangeGate } from "@/components/password-change-gate";
import { Sidebar } from "@/components/sidebar";
import { UserInfo } from "@/components/user-info";
import { Spinner } from "@/components/ui";

const TITLES: Array<[string, string]> = [
  ["/dashboard", "Dashboard tổng quan"],
  ["/machines", "Danh sách máy"],
  ["/ghost-machines", "Máy mất kết nối"],
  ["/tokens", "Thêm máy mới"],
  ["/reports", "Xuất báo cáo"],
  ["/eol", "Báo cáo Windows hết hỗ trợ"],
  ["/inventory-stats", "Thống kê cấu hình máy"],
  ["/audit", "Audit log"],
  ["/users", "Quản trị tài khoản"],
  ["/security", "Bảo mật tài khoản"],
  ["/compliance", "Thông báo tuân thủ"],
  ["/agent-config", "Cấu hình Agent"],
  ["/org-machine-stats", "Thống kê máy theo tổ chức"],
  ["/notifications-alerts", "Thông báo & Cảnh báo"],
];

function titleFor(pathname: string): string {
  if (pathname.startsWith("/machines/") && pathname !== "/machines") return "Chi tiết máy";
  return TITLES.find(([p]) => (p === "/dashboard" ? pathname === p : pathname.startsWith(p)))?.[1] ?? "Portal";
}

function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const { connected } = useRealtimeStatus();
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

  // Đang dùng mật khẩu mặc định → chặn toàn bộ portal cho tới khi đổi mật khẩu
  // (server cũng trả 403 PASSWORD_CHANGE_REQUIRED cho mọi API khác).
  if (user.must_change_password) {
    return <PasswordChangeGate />;
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="z-30 flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 sm:px-6">
          <button
            className="cursor-pointer rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 lg:hidden"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Mở menu"
            aria-expanded={menuOpen}
            aria-controls="portal-sidebar"
          >
            <Menu className="size-5" />
          </button>
          <h1 className="truncate text-sm font-semibold tracking-tight text-slate-900">{titleFor(pathname)}</h1>

          <div className="ml-auto flex items-center gap-3">
            <span
              role="status"
              aria-live="polite"
              className={
                connected
                  ? "inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20"
                  : "inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500"
              }
              title={
                connected
                  ? "Kết nối realtime đang hoạt động"
                  : "Kết nối realtime bị ngắt — dữ liệu sẽ tự nạp định kỳ"
              }
            >
              {connected ? (
                <>
                  <Wifi className="size-3.5" /> Realtime
                </>
              ) : (
                <>
                  <WifiOff className="size-3.5" /> Offline
                </>
              )}
            </span>
            <span className="h-6 w-px bg-slate-200" aria-hidden />
            <UserInfo />
            <NotificationBell />
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1320px] min-w-0 px-4 py-6 sm:px-6 lg:px-8">{children}</div>
        </main>

        <footer className="shrink-0 border-t border-slate-200 bg-slate-50 px-6 py-3 text-center text-xs text-slate-500">
          Hệ thống quản lý tài sản máy tính — agent read-only, không giám sát cá nhân (mục 6.6)
        </footer>
      </div>

      <ComplianceGate />
      <NotificationToast />
    </div>
  );
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <RealtimeProvider>
        <NotificationProvider>
          <Shell>{children}</Shell>
        </NotificationProvider>
      </RealtimeProvider>
    </AuthProvider>
  );
}