"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Bell,
  BellOff,
  BellRing,
  Building2,
  CalendarClock,
  ClipboardCheck,
  FileSpreadsheet,
  FileText,
  Ghost,
  HardDriveDownload,
  KeyRound,
  LayoutDashboard,
  MessageCircle,
  Monitor,
  ListTree,
  ScrollText,
  Search,
  Brain,
  ServerCog,
  ShieldCheck,
  Tags,
  Ticket,
  UserCog,
  type LucideIcon,
} from "lucide-react";
import type { UserRole } from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import { api } from "@/lib/api";
import { LogoMark } from "@/components/logo";

const ADMIN_ROLES: UserRole[] = ["super_admin", "org_admin", "admin_global", "admin_org"];
const SUPER_ADMIN_ROLES: UserRole[] = ["super_admin", "admin_global"];
const ALL_ROLES: UserRole[] = [
  "super_admin", "admin_global", "org_admin", "admin_org", "viewer",
];

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  roles?: UserRole[];
  exact?: boolean;
}

const NAV_GROUPS: Array<{ group: string; items: NavItem[] }> = [
  {
    group: "Tổng quan",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, exact: true },
      { href: "/leadership", label: "Lãnh đạo", icon: BarChart3 },
    ],
  },
  {
    group: "Quản lý máy tính",
    items: [
      { href: "/machines", label: "Máy tính", icon: Monitor },
      { href: "/approvals", label: "Máy chờ duyệt", icon: ClipboardCheck, roles: ADMIN_ROLES },
      { href: "/ghost-machines", label: "Máy mất kết nối", icon: Ghost },
      {
        href: "/tokens",
        label: "Thêm máy mới",
        icon: Ticket,
        roles: ADMIN_ROLES,
      },
      {
        href: "/offline-import",
        label: "Thêm máy BMNN",
        icon: HardDriveDownload,
        roles: ADMIN_ROLES,
      },
    ],
  },
  {
    group: "Tổ chức",
    items: [
      {
        href: "/organizations",
        label: "Cây tổ chức",
        icon: Building2,
        roles: ADMIN_ROLES,
      },
      {
        href: "/org-machine-stats",
        label: "Thống kê theo tổ chức",
        icon: Building2,
      },
    ],
  },
  {
    group: "Báo cáo",
    items: [
      { href: "/reports", label: "Xuất báo cáo", icon: FileSpreadsheet },
      { href: "/inventory-stats", label: "Thống kê cấu hình", icon: BarChart3 },
      { href: "/llm-dfir/stats", label: "Điều tra AI", icon: Brain, roles: ADMIN_ROLES },
      { href: "/eol", label: "Windows hết hỗ trợ", icon: CalendarClock },
    ],
  },
  {
    group: "Vận hành",
    items: [
      {
        href: "/notifications-alerts",
        label: "Thông báo & Cảnh báo",
        icon: Bell,
        roles: ALL_ROLES,
      },
      {
        href: "/dfir",
        label: "DFIR",
        icon: Search,
        roles: ADMIN_ROLES,
      },
      {
        href: "/admin/llm-dfir",
        label: "AI Điều tra",
        icon: Brain,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/audit",
        label: "System Logs",
        icon: ScrollText,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/users",
        label: "Quản trị tài khoản",
        icon: UserCog,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/api-keys",
        label: "API Keys",
        icon: KeyRound,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/admin/telegram-bot",
        label: "Cấu hình bot Telegram",
        icon: MessageCircle,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/admin/notification-prefs",
        label: "Cài đặt nhận thông báo",
        icon: BellOff,
        roles: ADMIN_ROLES,
      },
      {
        href: "/agent-config",
        label: "Cấu hình Agent",
        icon: ServerCog,
        roles: ADMIN_ROLES,
      },
      {
        href: "/tags",
        label: "Phân loại & mục đích",
        icon: Tags,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/admin/announcements",
        label: "Thông báo đăng nhập",
        icon: BellRing,
        roles: SUPER_ADMIN_ROLES,
      },
      { href: "/compliance", label: "Thông báo tuân thủ", icon: FileText },
    ],
  },
];

/** Số lượng hiển thị trên badge điều hướng — 1 request /machines/stats là đủ. */
interface MachineStats {
  total: number;
  by_status: Record<string, number>;
}

const NAV_BADGES: Record<string, (s: MachineStats) => number> = {
  // Assets — chỉ đếm máy đã duyệt (online/offline/lost/decommissioned); máy pending
  // đã có badge riêng ở "Chờ duyệt", tránh đếm trùng.
  "/machines": (s) => s.total - (s.by_status.pending ?? 0),
  "/approvals": (s) => s.by_status.pending ?? 0,
  "/ghost-machines": (s) => s.by_status.lost ?? 0,
};

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const [stats, setStats] = useState<MachineStats | null>(null);

  // Badge số lượng: nạp khi vào trang, refresh mỗi 60s và khi đổi route
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await api.get<MachineStats>("/machines/stats");
        if (!cancelled) setStats(s);
      } catch {
        // im lặng — badge chỉ là tiện ích, không chặn điều hướng
      }
    };
    void load();
    const t = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [pathname]);

  // ESC đóng menu mobile
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onNavigate?.();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onNavigate]);

  const visibleGroups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => !i.roles || (user && i.roles.includes(user.role))),
  })).filter((g) => g.items.length > 0);

  const containerClass = open
    ? "fixed inset-y-0 left-0 z-40 flex w-[260px] -translate-x-0"
    : "hidden lg:flex lg:w-[260px] lg:shrink-0";

  return (
    <aside
      id="portal-sidebar"
      className={`${containerClass} flex-col border-r border-slate-200 bg-white transition-transform`}
      aria-label="Điều hướng chính"
    >
      {/* Brand — khối icon primary duy nhất trên chrome trắng */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white">
          <LogoMark size={20} />
        </div>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-base font-bold tracking-tight text-slate-900">AssetManager</p>
          <p className="truncate text-[11px] text-slate-400">Enterprise Infrastructure</p>
        </div>
      </div>

      {/* Nav — hàng sáng, active = nền canvas + vạch primary bên trái */}
      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        <div className="space-y-4">
          {visibleGroups.map((group) => (
            <div key={group.group}>
              <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {group.group}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const active = item.exact
                    ? pathname === item.href
                    : pathname.startsWith(item.href);
                  const Icon = item.icon;
                  const count = stats ? NAV_BADGES[item.href]?.(stats) : undefined;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        className={`group flex items-center gap-3 rounded-sm border-l-4 px-2.5 py-2 text-sm transition-colors ${
                          active
                            ? "border-brand-600 bg-slate-50 font-semibold text-slate-900"
                            : "border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-900"
                        }`}
                      >
                        <Icon className={`size-4 shrink-0 ${active ? "text-brand-600" : ""}`} />
                        <span className="truncate">{item.label}</span>
                        {count !== undefined && count > 0 && (
                          <span
                            className={`ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-semibold leading-none ${
                              item.href === "/approvals"
                                ? "bg-amber-100 text-amber-700"
                                : item.href === "/ghost-machines"
                                  ? "bg-rose-100 text-rose-700"
                                  : "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {count > 99 ? "99+" : count}
                          </span>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </nav>
    </aside>
  );
}
