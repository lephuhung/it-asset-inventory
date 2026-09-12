"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Bell,
  BellOff,
  BellRing,
  Briefcase,
  Building2,
  CalendarClock,
  ChevronRight,
  ClipboardCheck,
  FileSpreadsheet,
  FileText,
  Ghost,
  HardDriveDownload,
  KeyRound,
  LayoutDashboard,
  MessageCircle,
  Monitor,
  ScrollText,
  Search,
  Brain,
  ServerCog,
  Settings,
  ShieldAlert,
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
  /** Sub-links hiển thị dưới parent khi bung. Parent vẫn là link thật — chevron
   *  bên phải chỉ bung/thu, không navigate. Tự bung khi pathname khớp bất kỳ con nào. */
  children?: NavItem[];
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
      { href: "/enroll-requests", label: "Yêu cầu enroll bị từ chối", icon: ShieldAlert, roles: ADMIN_ROLES },
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
      // Tách từ nhóm "Báo cáo" — trang này phân tích AI trên dữ liệu máy,
      // gần với quản lý máy hơn là báo cáo tổng hợp.
      { href: "/llm-dfir/stats", label: "Điều tra AI", icon: Brain, roles: ADMIN_ROLES },
    ],
  },
  {
    group: "Tổ chức",
    items: [
      {
        href: "/system-profiles",
        label: "Hồ sơ cấp độ HTTT",
        icon: ShieldCheck,
        roles: ADMIN_ROLES,
      },
      {
        href: "/contacts",
        label: "Chuyên trách CNTT",
        icon: UserCog,
        roles: ADMIN_ROLES,
      },
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
        children: [
          {
            href: "/admin/notification-prefs",
            label: "Cài đặt nhận thông báo",
            icon: BellOff,
            roles: ADMIN_ROLES,
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
      {
        href: "/system-profiles/config",
        label: "Cấu hình hồ sơ cấp độ",
        icon: Settings,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/admin/officers",
        label: "Cán bộ phụ trách",
        icon: Briefcase,
        roles: SUPER_ADMIN_ROLES,
      },
      {
        href: "/dfir",
        label: "DFIR & AI",
        icon: Search,
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
        href: "/admin/telegram-bot",
        label: "Cấu hình bot Telegram",
        icon: MessageCircle,
        roles: SUPER_ADMIN_ROLES,
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

  /** Submenu đang bung — mặc định bung nếu pathname khớp parent HOẶC bất kỳ con nào. */
  const initialExpanded = useMemo(() => {
    const out: Record<string, boolean> = {};
    for (const g of NAV_GROUPS) {
      for (const it of g.items) {
        if (!it.children?.length) continue;
        const childActive = it.children.some((c) => pathname === c.href || pathname.startsWith(c.href + "/"));
        const parentActive = pathname === it.href || pathname.startsWith(it.href + "/");
        if (parentActive || childActive) out[it.href] = true;
      }
    }
    return out;
  }, [pathname]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>(initialExpanded);
  // Đồng bộ lại khi route đổi — đảm bảo submenu bung khi user navigate vào con.
  useEffect(() => {
    setExpanded((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const g of NAV_GROUPS) {
        for (const it of g.items) {
          if (!it.children?.length) continue;
          const childActive = it.children.some((c) => pathname === c.href || pathname.startsWith(c.href + "/"));
          if (childActive && !next[it.href]) {
            next[it.href] = true;
            changed = true;
          }
        }
      }
      return changed ? next : prev;
    });
  }, [pathname]);
  const toggleExpand = (href: string) =>
    setExpanded((prev) => ({ ...prev, [href]: !prev[href] }));

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
    items: g.items
      .map((i) => ({
        ...i,
        children: i.children?.filter((c) => !c.roles || (user && c.roles.includes(user.role))),
      }))
      .filter((i) => {
        // Giữ parent nếu user có quyền parent HOẶC còn ít nhất 1 con sau khi lọc.
        const parentVisible = !i.roles || (user && i.roles.includes(user.role));
        return parentVisible || (i.children && i.children.length > 0);
      }),
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
                  const hasChildren = !!item.children?.length;
                  const isOpen = !!expanded[item.href];
                  return (
                    <li key={item.href}>
                      <div
                        className={`group flex items-center gap-2 rounded-sm border-l-4 transition-colors ${
                          active
                            ? "border-brand-600 bg-slate-50"
                            : "border-transparent hover:bg-slate-50"
                        }`}
                      >
                        <Link
                          href={item.href}
                          onClick={onNavigate}
                          aria-current={active ? "page" : undefined}
                          className={`flex min-w-0 flex-1 items-center gap-3 px-2.5 py-2 text-sm ${
                            active
                              ? "font-semibold text-slate-900"
                              : "text-slate-500 group-hover:text-slate-900"
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
                        {hasChildren && (
                          <button
                            type="button"
                            aria-label={isOpen ? "Thu gọn" : "Bung ra"}
                            aria-expanded={isOpen}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              toggleExpand(item.href);
                            }}
                            className="mr-1.5 flex size-6 shrink-0 items-center justify-center rounded-sm text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
                          >
                            <ChevronRight
                              className={`size-3.5 transition-transform duration-150 motion-reduce:transition-none ${isOpen ? "rotate-90" : ""}`}
                            />
                          </button>
                        )}
                      </div>
                      {hasChildren && isOpen && (
                        <ul className="mt-0.5 space-y-0.5 border-l-2 border-slate-200 pl-3 ml-3">
                          {item.children!.map((child) => {
                            const childActive = child.exact
                              ? pathname === child.href
                              : pathname.startsWith(child.href);
                            const ChildIcon = child.icon;
                            return (
                              <li key={child.href}>
                                <Link
                                  href={child.href}
                                  onClick={onNavigate}
                                  aria-current={childActive ? "page" : undefined}
                                  className={`flex items-center gap-2.5 rounded-sm border-l-2 px-2.5 py-1.5 text-[13px] transition-colors ${
                                    childActive
                                      ? "border-brand-600 bg-slate-50 font-semibold text-slate-900"
                                      : "border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-900"
                                  }`}
                                >
                                  <ChildIcon className={`size-3.5 shrink-0 ${childActive ? "text-brand-600" : ""}`} />
                                  <span className="truncate">{child.label}</span>
                                </Link>
                              </li>
                            );
                          })}
                        </ul>
                      )}
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
