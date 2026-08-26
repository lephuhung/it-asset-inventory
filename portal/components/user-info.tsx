"use client";

import { LogOut } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { ROLE_META } from "@/lib/format";
import { Badge } from "@/components/ui";

/** Khối thông tin quản trị viên hiển thị ở góc trên phải màn hình */
export function UserInfo() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className="flex items-center gap-2.5">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600">
        {user.full_name.slice(0, 1).toUpperCase()}
      </div>
      <div className="hidden min-w-0 leading-tight sm:block">
        <p className="truncate text-xs font-medium text-slate-900">{user.full_name}</p>
        <p className="truncate text-[11px] text-slate-400">{user.email}</p>
      </div>
      <Badge className={ROLE_META[user.role].badge}>{ROLE_META[user.role].label}</Badge>
      <button
        onClick={() => void logout()}
        title="Đăng xuất"
        aria-label="Đăng xuất"
        className="cursor-pointer rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}
