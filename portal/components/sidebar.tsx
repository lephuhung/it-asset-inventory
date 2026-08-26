"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bell,
  Building2,
  CalendarClock,
  ClipboardCheck,
  FileSpreadsheet,
  FileText,
  Fingerprint,
  Ghost,
  GitCompareArrows,
  HardDriveDownload,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Monitor,
  ScrollText,
  ShieldCheck,
  Ticket,
  UserCog,
  type LucideIcon,
} from "lucide-react";
import type { UserRole } from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import { ROLE_META } from "@/lib/format";
import { Badge } from "@/components/ui";

const ADMIN_ROLES: UserRole[] = ["super_admin", "org_admin", "admin_global", "admin_org"];
const SUPER_ADMIN_ROLES: UserRole[] = ["super_admin", "admin_global"];

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
    group: "Quản lý tài sản",
    items: [
      { href: "/machines", label: "Assets", icon: Monitor },
      { href: "/approvals", label: "Chờ duyệt", icon: ClipboardCheck, roles: ADMIN_ROLES },
      { href: "/ghost-machines", label: "Máy ma", icon: Ghost },
      { href: "/drifts", label: "Fingerprint drift", icon: Fingerprint, roles: ADMIN_ROLES },
      {
        href: "/tokens",
        label: "Agent Config",
        icon: Ticket,
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
    ],
  },
  {
    group: "Báo cáo",
    items: [
      { href: "/reports", label: "Xuất báo cáo", icon: FileSpreadsheet },
      { href: "/eol", label: "Windows EOL", icon: CalendarClock },
      { href: "/diff", label: "So sánh máy (Diff)", icon: GitCompareArrows },
      { href: "/offline-import", label: "Máy cách ly", icon: HardDriveDownload, roles: ADMIN_ROLES },
    ],
  },
  {
    group: "Vận hành",
    items: [
      {
        href: "/alerts",
        label: "Alerts",
        icon: Bell,
        roles: ADMIN_ROLES,
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
        href: "/security",
        label: "User Access",
        icon: ShieldCheck,
        roles: ADMIN_ROLES,
      },
      { href: "/compliance", label: "Thông báo tuân thủ", icon: FileText },
    ],
  },
];

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const visibleGroups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => !i.roles || (user && i.roles.includes(user.role))),
  })).filter((g) => g.items.length > 0);

  const containerClass = open
    ? "fixed inset-y-0 left-0 z-40 flex w-[260px] -translate-x-0"
    : "hidden lg:flex lg:w-[260px] lg:shrink-0 lg:sticky lg:top-0 lg:h-screen";

  return (
    <aside
      className={`${containerClass} flex-col bg-slate-900 text-slate-300 transition-transform`}
    >
      {/* Brand — AssetManager */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-800 text-white ring-1 ring-inset ring-slate-700">
          <ShieldCheck className="size-5" />
        </div>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-base font-bold text-white">AssetManager</p>
          <p className="truncate text-[11px] text-slate-400">Enterprise Infrastructure</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        <div className="space-y-4">
          {visibleGroups.map((group) => (
            <div key={group.group}>
              <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                {group.group}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const active = item.exact
                    ? pathname === item.href
                    : pathname.startsWith(item.href);
                  const Icon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        className={`group flex items-center gap-3 rounded px-2.5 py-2 text-sm transition-colors ${
                          active
                            ? "border-l-4 border-white bg-white/10 font-bold text-white"
                            : "border-l-4 border-transparent text-slate-400 hover:bg-white/5 hover:text-white"
                        }`}
                      >
                        <Icon className="size-4 shrink-0" />
                        <span className="truncate">{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </nav>

      {/* User */}
      {user && (
        <div className="border-t border-slate-800 px-4 py-4">
          <div className="mb-3 flex items-center gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-slate-700 text-sm font-semibold text-white">
              {user.full_name.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 leading-tight">
              <p className="truncate text-sm font-medium text-white">{user.full_name}</p>
              <p className="truncate text-xs text-slate-400">{user.email}</p>
            </div>
          </div>
          <div className="mb-2.5">
            <Badge className={ROLE_META[user.role].badge}>{ROLE_META[user.role].label}</Badge>
          </div>
          <button
            onClick={() => void logout()}
            className="flex w-full items-center gap-2 rounded px-2.5 py-2 text-sm text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LogOut className="size-4" />
            Đăng xuất
          </button>
        </div>
      )}
    </aside>
  );
}
