"use client";

import React from "react";

/** Cấu hình OS — thứ tự hiển thị trong picker. */
export const OS_OPTIONS = [
  { id: "windows", label: "Windows", icon: "🪟", description: "PowerShell MSI silent install" },
  { id: "linux", label: "Linux", icon: "🐧", description: "curl | bash — .deb / .rpm tự động" },
  { id: "offline", label: "Offline USB", icon: "💾", description: "Gói ZIP cho máy cách ly" },
] as const;

export type OsId = (typeof OS_OPTIONS)[number]["id"];

interface Props {
  value: OsId;
  onChange: (id: OsId) => void;
  className?: string;
  /** Tùy chọn: ẩn một số OS (vd. tắt offline trên trang public enroll). */
  hideOffline?: boolean;
}

/** Tab 3 OS cho trang tokens/enroll — cho phép người dùng chọn đúng lệnh cài. */
export function OsPicker({ value, onChange, className, hideOffline = false }: Props) {
  const options = hideOffline ? OS_OPTIONS.filter((o) => o.id !== "offline") : OS_OPTIONS;
  return (
    <div
      role="tablist"
      aria-label="Chọn hệ điều hành"
      className={`grid gap-2 sm:grid-cols-3 rounded-xl border border-slate-200 bg-slate-50 p-1.5${
        hideOffline ? " sm:grid-cols-2" : ""
      }${className ? " " + className : ""}`}
    >
      {options.map((opt) => {
        const active = value === opt.id;
        return (
          <button
            key={opt.id}
            role="tab"
            aria-selected={active}
            type="button"
            onClick={() => onChange(opt.id)}
            className={`flex flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left text-xs transition ${
              active
                ? "bg-white shadow-sm ring-1 ring-blue-300 text-slate-900"
                : "text-slate-600 hover:bg-white/60"
            }`}
          >
            <span className="flex items-center gap-1.5 text-sm font-semibold">
              <span aria-hidden>{opt.icon}</span>
              {opt.label}
            </span>
            <span className="text-[11px] text-slate-500">{opt.description}</span>
          </button>
        );
      })}
    </div>
  );
}