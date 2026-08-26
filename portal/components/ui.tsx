"use client";

import type { ReactNode } from "react";
import { Loader2, X } from "lucide-react";

/* ── Badge ─────────────────────────────────────────────────── */

export function Badge({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${className}`}
    >
      {children}
    </span>
  );
}

export function StatusDot({ className = "" }: { className?: string }) {
  return <span className={`inline-block size-2 rounded-full ${className}`} />;
}

/* ── Card ──────────────────────────────────────────────────── */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  padded = true,
  headerClass = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
  headerClass?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_1px_rgba(15,23,42,0.03)] ${className}`}>
      {(title || actions) && (
        <header className={`flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 ${headerClass}`}>
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight text-slate-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] leading-snug text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

/* ── Button ────────────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "success" | "outline";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary:
    "bg-[#635a5a] text-white shadow-sm shadow-[#635a5a]/20 hover:bg-[#4f4848] active:bg-[#3b3636] focus-visible:outline-[#635a5a] disabled:bg-[#a8a0a0] disabled:shadow-none",
  success:
    "bg-emerald-600 text-white shadow-sm shadow-emerald-600/20 hover:bg-emerald-700 active:bg-emerald-800 focus-visible:outline-emerald-600 disabled:bg-emerald-300 disabled:shadow-none",
  secondary:
    "bg-slate-50 text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-100 active:bg-slate-200 disabled:text-slate-300",
  outline:
    "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 active:bg-slate-100 disabled:text-slate-300",
  danger:
    "bg-white text-rose-600 ring-1 ring-inset ring-rose-300 hover:bg-rose-50 active:bg-rose-100 disabled:text-rose-300",
  ghost: "text-slate-600 hover:bg-slate-100 active:bg-slate-200 disabled:text-slate-300",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  children,
  disabled,
  ...rest
}: {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  className?: string;
  children: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const sizeClass =
    size === "sm"
      ? "h-8 px-3 text-xs"
      : size === "lg"
        ? "h-11 px-5 text-sm"
        : "h-9.5 px-3.5 text-sm";
  return (
    <button
      className={`inline-flex select-none items-center justify-center gap-1.5 rounded-lg font-medium transition-all duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed ${sizeClass} ${BUTTON_STYLES[variant]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

/* ── Form controls ─────────────────────────────────────────── */

export function Field({
  label,
  required,
  hint,
  children,
  className = "",
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 flex items-center gap-1 text-[13px] font-medium text-slate-700">
        {label}
        {required && <span className="text-rose-500">*</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs leading-snug text-slate-400">{hint}</span>}
    </label>
  );
}

const CONTROL_CLASS =
  "h-9.5 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 transition-colors focus:border-blue-500 focus:outline-none focus:ring-4 focus:ring-blue-500/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL_CLASS} ${props.className ?? ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`${CONTROL_CLASS} cursor-pointer pr-9 ${props.className ?? ""}`}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL_CLASS} min-h-20 py-2 ${props.className ?? ""}`} />;
}

/* ── Loading / Empty ───────────────────────────────────────── */

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-12 text-sm text-slate-500">
      <Loader2 className="size-5 animate-spin text-[#635a5a]" />
      {label ?? "Đang tải…"}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && (
        <div className="mb-1 flex size-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      {description && <p className="max-w-md text-[13px] leading-snug text-slate-400">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/* ── Error banner ──────────────────────────────────────────── */

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      <span className="flex items-center gap-2">
        <span className="flex size-5 items-center justify-center rounded-full bg-rose-100 text-rose-600">!</span>
        {message}
      </span>
      {onRetry && (
        <button className="font-semibold underline-offset-2 hover:underline" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  );
}

/* ── Modal ─────────────────────────────────────────────────── */

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onClose} />
      <div
        className={`relative z-10 max-h-[90vh] w-full overflow-y-auto rounded-2xl bg-white shadow-2xl ${
          wide ? "max-w-3xl" : "max-w-lg"
        }`}
      >
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-slate-100 bg-white/95 px-6 py-4 backdrop-blur">
          <h3 className="text-[15px] font-semibold text-slate-800">{title}</h3>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            aria-label="Đóng"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="px-6 py-5">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50/50 px-6 py-4">{footer}</footer>
        )}
      </div>
    </div>
  );
}

/* ── Table helpers ───────────────────────────────────────────
   QUY TẮC: mọi <table> PHẢI bọc trong <div className={TABLE_WRAP}>.
   Bảng co theo container (w-full) — KHÔNG dùng min-w-max để tránh
   đẩy cả trang lăn ngang. Khi nội dung rộng, .tbl-wrap cuộn ngang
   NỘI BỘ (xem Design.md). */
export const TABLE_WRAP = "tbl-wrap";
export const TABLE = "w-full border-collapse text-left text-sm";
export const THEAD = "border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-wider text-slate-500";
export const TH = "px-4 py-3 font-semibold whitespace-nowrap";
export const TD = "border-b border-slate-100 px-4 py-3 align-middle text-slate-700";
export const TR_HOVER = "transition-colors hover:bg-slate-50/70";

/* ── Page header ───────────────────────────────────────────── */

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[22px] font-bold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm leading-snug text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
