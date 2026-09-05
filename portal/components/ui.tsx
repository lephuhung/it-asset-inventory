"use client";

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode, type Ref } from "react";
import { Check, ChevronDown, ChevronLeft, ChevronRight, Copy, Loader2, X } from "lucide-react";

/* ── Badge ─────────────────────────────────────────────────── */

export function Badge({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${className}`}
    >
      {children}
    </span>
  );
}

export function StatusDot({ className = "" }: { className?: string }) {
  return <span className={`inline-block size-2 rounded-full ${className}`} />;
}

/** Badge có chấm trạng thái đi kèm — pattern dùng ở khắp các bảng. */
export function StatusBadge({ badge, dot, children }: { badge: string; dot: string; children: ReactNode }) {
  return (
    <Badge className={badge}>
      <StatusDot className={dot} />
      {children}
    </Badge>
  );
}

/**
 * Công tắc hiển thị trạng thái ON/OFF (read-only, không thao tác được).
 * Dùng cho các giá trị true/false thay cho chữ "Bật"/"Đã tắt".
 */
export function BoolSwitch({ on, label }: { on: boolean; label?: string }) {
  return (
    <span
      role="img"
      aria-label={label ?? (on ? "Bật" : "Tắt")}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-default items-center rounded-full transition-colors ${
        on ? "bg-emerald-500" : "bg-slate-300"
      }`}
    >
      <span
        className={`absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-all ${
          on ? "left-[18px]" : "left-0.5"
        }`}
      />
    </span>
  );
}

/**
 * Công tắc bật/tắt (interactive, a11y: role=switch + aria-checked).
 * Bật = primary blue (màu hành động duy nhất), tắt = slate — theo Design.md.
 */
export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
  className = "",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-150 motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? "bg-brand-600" : "bg-slate-300"
      } ${className}`}
    >
      <span
        className={`absolute left-0.5 top-0.5 size-5 rounded-full bg-white shadow-sm transition-transform duration-150 motion-reduce:transition-none ${
          checked ? "translate-x-5" : ""
        }`}
      />
    </button>
  );
}

/* ── Card ──────────────────────────────────────────────────── */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClass = "",
  padded = true,
  headerClass = "",
  sectionRef,
  style,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Bổ sung class cho body — dùng khi muốn body lấp đầy card (vd `flex flex-col min-h-0 flex-1`)
   *  để danh sách con dùng được `flex-1` và khớp chiều cao với card bên cạnh trong grid. */
  bodyClass?: string;
  padded?: boolean;
  headerClass?: string;
  /** Ref tới <section> của card — dùng khi cần đo/khóa chiều cao card theo card bên cạnh. */
  sectionRef?: Ref<HTMLElement>;
  /** Style inline cho <section> — vd `{ height }` để khóa chiều cao card. */
  style?: CSSProperties;
}) {
  return (
    <section
      ref={sectionRef}
      style={style}
      className={`flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm ${className}`}
    >
      {(title || actions) && (
        <header className={`flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 ${headerClass}`}>
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight text-slate-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] leading-snug text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`${padded ? "p-5" : ""} ${bodyClass}`}>{children}</div>
    </section>
  );
}

/* ── KPI card (trắng phẳng + hairline, điểm nhấn màu ở icon) ─── */

export function KpiCard({
  label,
  value,
  icon,
  accent,
  sub,
  hint,
  className = "",
}: {
  label: string;
  value: number | string;
  icon: ReactNode;
  accent: string;
  sub?: string;
  /** Tooltip giải thích ý nghĩa số liệu (hiển thị khi hover icon ⓘ). */
  hint?: string;
  className?: string;
}) {
  const [showHint, setShowHint] = useState(false);
  return (
    <div className={`kpi-card flex min-h-[108px] h-full flex-col justify-between p-3.5 sm:p-4 ${className}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-slate-400">
          {label}
          {hint && (
            <span
              className="relative inline-flex"
              onMouseEnter={() => setShowHint(true)}
              onMouseLeave={() => setShowHint(false)}
              onFocus={() => setShowHint(true)}
              onBlur={() => setShowHint(false)}
              tabIndex={0}
            >
              <span
                role="img"
                aria-label="Thông tin"
                className="inline-flex size-3.5 cursor-help items-center justify-center rounded-full text-[10px] font-bold text-slate-400 ring-1 ring-inset ring-slate-300 hover:bg-slate-100"
              >
                i
              </span>
              {showHint && (
                <span
                  role="tooltip"
                  className="pointer-events-none absolute left-0 top-full z-10 mt-1 w-56 rounded-lg bg-slate-900 px-2.5 py-1.5 text-left text-[11px] font-normal normal-case tracking-normal text-white shadow-lg"
                >
                  {hint}
                </span>
              )}
            </span>
          )}
        </p>
        <span className={`flex size-7 shrink-0 items-center justify-center rounded-lg ${accent}`}>{icon}</span>
      </div>
      <div className="mt-2">
        <p className="text-2xl font-bold leading-tight tabular-nums text-slate-900">{value}</p>
        {sub && <p className="mt-1 text-[11px] leading-snug text-slate-400">{sub}</p>}
      </div>
    </div>
  );
}

/* ── Button ────────────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "success" | "outline";

/* Radius theo Design.md §Buttons: primary/secondary là marketing CTA —
   pill trọn (rounded.full); các variant còn lại là nút utility — 8px.
   Press state: nền đậm hơn + scale nhẹ (thay cho scale(0.9) mạnh). */
const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary:
    "rounded-full bg-brand-600 text-white shadow-sm hover:bg-brand-700 active:bg-brand-700 active:scale-[0.98] focus-visible:outline-brand-600 disabled:bg-brand-400 disabled:shadow-none",
  success:
    "rounded-full bg-emerald-600 text-white shadow-sm hover:bg-emerald-700 active:bg-emerald-700 active:scale-[0.98] focus-visible:outline-emerald-600 disabled:bg-emerald-300 disabled:shadow-none",
  secondary:
    "rounded-full bg-white text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50 active:bg-slate-100 active:scale-[0.98] disabled:text-slate-300 disabled:shadow-none",
  outline:
    "rounded-md bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 active:bg-slate-100 active:scale-[0.98] disabled:text-slate-300",
  danger:
    "rounded-md bg-white text-rose-600 ring-1 ring-inset ring-rose-300 hover:bg-rose-50 active:bg-rose-100 active:scale-[0.98] disabled:text-rose-300",
  ghost:
    "rounded-md text-slate-600 hover:bg-slate-100 active:bg-slate-100 disabled:text-slate-300",
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
      ? "h-8 min-h-8 px-3 text-xs"
      : size === "lg"
        ? "h-11 min-h-11 px-5 text-sm"
        : "h-9.5 min-h-9.5 px-3.5 text-sm";
  return (
    <button
      className={`inline-flex cursor-pointer select-none items-center justify-center gap-1.5 font-medium whitespace-nowrap transition-all duration-150 motion-reduce:transition-none motion-reduce:active:scale-100 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:active:scale-100 ${sizeClass} ${BUTTON_STYLES[variant]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />}
      {children}
    </button>
  );
}

/** Nút chỉ có icon — luôn cần aria-label (skill: icon button accessible label). */
/** Nút chỉ có icon — luôn cần aria-label (skill: icon button accessible label).
    Mặc định neutral; truyền className="hover:bg-rose-50 hover:text-rose-600" cho nút xóa. */
export function IconButton({
  label,
  className = "",
  children,
  ...rest
}: { label: string; className?: string; children?: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      aria-label={label}
      title={label}
      className={`inline-flex size-8 min-h-8 min-w-8 cursor-pointer items-center justify-center rounded-full text-slate-400 transition-colors duration-150 motion-reduce:transition-none hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ── Copy button dùng chung (3 nơi đã duplicate) ───────────── */

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Button variant="secondary" size="sm" onClick={() => void copy()}>
      {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
      {copied ? "Đã copy" : label}
    </Button>
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

/* text-input: bo tròn xs 4px — cố ý khác hẳn pill CTA (Design.md §Inputs).
   Viền #dddddd, focus = primary + shadow Level-1. */
const CONTROL_CLASS =
  "h-9.5 w-full rounded-xs border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 transition-shadow focus:border-brand-600 focus:shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-600/15 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL_CLASS} ${props.className ?? ""}`} />;
}

/* Select — thả xuống đồng bộ design (Design.md §Inputs): bo xs 4px, chevron
   riêng thay arrow native, focus = primary. width override (w-*) được tôn
   trọng: nếu caller truyền w-* thì bỏ w-full mặc định, tránh xung đột CSS
   (w-full xếp sau w-36 trong stylesheet → select bị kéo full-width, gây
   wrap hàng trong flex). */
export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "" } = props;
  const hasWidth = /\bw-[^\s"']+/.test(className);
  const widthClass = hasWidth ? className : `w-full ${className}`;
  return (
    <span className={`relative block ${hasWidth ? "" : "w-full"}`}>
      <select
        {...props}
        className={`${CONTROL_CLASS.replace(" w-full", "")} cursor-pointer appearance-none pr-9 ${widthClass}`}
      />
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
    </span>
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL_CLASS} min-h-20 py-2 ${props.className ?? ""}`} />;
}

/* ── Loading / Empty ───────────────────────────────────────── */

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-12 text-sm text-slate-500">
      <Loader2 className="size-5 animate-spin motion-reduce:animate-none text-brand-600" />
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
    <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      <span className="flex items-center gap-2">
        <span className="flex size-5 items-center justify-center rounded-full bg-rose-100 text-rose-600">!</span>
        {message}
      </span>
      {onRetry && (
        <button
          className="cursor-pointer font-semibold underline-offset-2 hover:underline"
          onClick={onRetry}
        >
          Thử lại
        </button>
      )}
    </div>
  );
}

/* ── Modal (a11y: role=dialog, aria-modal, ESC, focus trap, scroll lock) ── */

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

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
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const lastFocused = useRef<HTMLElement | null>(null);
  // Giữ onClose mới nhất qua ref — KHÔNG đưa onClose vào deps của effect bên dưới.
  // Caller thường truyền inline () => setX(false) nên reference đổi mỗi render;
  // nếu để trong deps, effect chạy lại mỗi lần gõ phím trong form → cleanup
  // restore focus (lastFocused.focus()) → focus bị cướp khỏi ô đang nhập.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // ESC đóng + focus trap — chỉ chạy lại khi open thay đổi (không theo onClose)
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    lastFocused.current = prev;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const nodes = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    // Focus phần tử đầu tiên trong modal (hoặc chính panel)
    const t = setTimeout(() => {
      const nodes = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      (nodes?.[0] ?? panelRef.current)?.focus();
    }, 30);
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKeyDown, true);
      lastFocused.current?.focus?.();
    };
  }, [open]);

  // Khóa cuộn body khi mở
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/55" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`relative z-10 max-h-[90vh] w-full overflow-y-auto rounded-2xl bg-white shadow-2xl outline-none ${
          wide ? "max-w-3xl" : "max-w-lg"
        }`}
      >
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-slate-100 bg-white px-6 py-4">
          <h3 id={titleId} className="text-[15px] font-semibold text-slate-800">{title}</h3>
          <IconButton label="Đóng" onClick={onClose} className="hover:bg-slate-100 hover:text-slate-600">
            <X className="size-4" />
          </IconButton>
        </header>
        <div className="px-6 py-5">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50/50 px-6 py-4">{footer}</footer>
        )}
      </div>
    </div>
  );
}

/* ── ConfirmDialog — thay window.confirm (native confirm là anti-pattern) ── */

export function ConfirmDialog({
  open,
  onClose,
  title,
  message,
  confirmLabel = "Xác nhận",
  danger = false,
  loading = false,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            Hủy
          </Button>
          <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm leading-relaxed text-slate-600">{message}</div>
    </Modal>
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


/* ── Pagination ─────────────────────────────────────────────────── */

/** Trả về response phân trang từ backend (`Page<T>` wrapper). */
export interface PageResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Component phân trang — dùng cho table có nhiều dòng.
 *  Props: `page` (offset/limit/total/items) + callback khi user đổi trang.
 *  Hiển thị: "Tổng X · Trang N/M" + nút Trước/Sau + chọn trang nhảy nhanh. */
export function Pagination({
  page,
  onChange,
  className = "",
}: {
  page: PageResponse<unknown>;
  onChange: (offset: number) => void;
  className?: string;
}) {
  const { total, limit, offset } = page;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  const goTo = (newOffset: number) => {
    const clamped = Math.max(0, Math.min(newOffset, (totalPages - 1) * limit));
    if (clamped !== offset) onChange(clamped);
  };

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-xs text-slate-500 ${className}`}
    >
      <p>
        Hiển thị <b className="text-slate-700">{from}–{to}</b> trong tổng số{" "}
        <b className="text-slate-700">{total}</b> · Trang <b className="text-slate-700">{currentPage}/{totalPages}</b>
      </p>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => goTo(0)}
          disabled={offset === 0}
          className="cursor-pointer rounded border border-slate-200 px-2 py-1 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          title="Trang đầu"
          aria-label="Trang đầu"
        >
          «
        </button>
        <button
          type="button"
          onClick={() => goTo(offset - limit)}
          disabled={offset === 0}
          className="cursor-pointer rounded border border-slate-200 px-2 py-1 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          title="Trang trước"
          aria-label="Trang trước"
        >
          <ChevronLeft className="size-3.5" />
        </button>
        <input
          type="number"
          min={1}
          max={totalPages}
          value={currentPage}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (Number.isFinite(v) && v >= 1 && v <= totalPages) goTo((v - 1) * limit);
          }}
          className="w-12 rounded border border-slate-200 px-1.5 py-1 text-center font-mono text-xs tabular-nums"
          aria-label="Trang hiện tại"
        />
        <span className="text-slate-400">/ {totalPages}</span>
        <button
          type="button"
          onClick={() => goTo(offset + limit)}
          disabled={offset + limit >= total}
          className="cursor-pointer rounded border border-slate-200 px-2 py-1 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          title="Trang sau"
          aria-label="Trang sau"
        >
          <ChevronRight className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => goTo((totalPages - 1) * limit)}
          disabled={offset + limit >= total}
          className="cursor-pointer rounded border border-slate-200 px-2 py-1 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          title="Trang cuối"
          aria-label="Trang cuối"
        >
          »
        </button>
      </div>
    </div>
  );
}
