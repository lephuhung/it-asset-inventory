/**
 * Metadata trung tâm cho Investigation Status/Severity — NHẤT NHẤT với backend.
 *
 * Trước đây 4 file tự giữ bản copy riêng (machine-investigation-panel,
 * llm-dfir/stats, llm-dfir/investigations ×2) — màu lệch nhau dần và icon bị
 * khai báo `any`. Sửa màu/label ở MỘT chỗ duy nhất tại đây.
 *
 * Pill tinted theo Design.md — màu đã remap trong globals.css:
 * bad → rose · warn → amber · ok → emerald · info → blue (primary).
 */
import type { ComponentType } from "react";
import {
  AlertOctagon,
  Brain,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCcw,
  Search,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type { InvestigationSeverity, InvestigationStatus } from "@/lib/types";

export type MetaIcon = ComponentType<{ className?: string }>;

export interface InvestigationStatusMeta {
  /** Label ngắn — chip/filter trong list + panel. */
  label: string;
  /** Label đầy đủ — badge ở trang chi tiết (nếu khác label ngắn). */
  longLabel?: string;
  /** Pill tinted cho <Badge>. */
  badge: string;
  /** Ring khi chip được chọn trong panel. */
  ring: string;
  /** Nền tint nhạt cho row/panel. */
  tint: string;
  /** Màu fill cho biểu đồ. */
  fill: string;
  icon: MetaIcon;
}

export interface InvestigationSeverityMeta {
  label: string;
  /** Pill tinted cho <Badge>. */
  badge: string;
  /** Vạch trái row / màu fill biểu đồ. */
  fill: string;
  icon: MetaIcon;
}

export const INVESTIGATION_STATUS_META: Record<InvestigationStatus, InvestigationStatusMeta> = {
  pending: {
    label: "Chờ FIFO",
    badge: "bg-slate-100 text-slate-700 ring-slate-600/20",
    icon: Clock,
    ring: "ring-slate-300",
    tint: "bg-slate-50",
    fill: "bg-slate-400",
  },
  running: {
    label: "Khởi động",
    longLabel: "Đang khởi động",
    badge: "bg-blue-100 text-blue-700 ring-blue-600/20",
    icon: Loader2,
    ring: "ring-blue-300",
    tint: "bg-blue-50",
    fill: "bg-blue-500",
  },
  collecting: {
    label: "Thu thập",
    longLabel: "Đang thu thập dữ liệu",
    badge: "bg-sky-50 text-sky-700 ring-sky-600/20",
    icon: RefreshCcw,
    ring: "ring-sky-300",
    tint: "bg-sky-50",
    fill: "bg-sky-600",
  },
  analyzing: {
    label: "Phân tích",
    longLabel: "AI đang phân tích",
    badge: "bg-violet-100 text-violet-700 ring-violet-600/20",
    icon: Brain,
    ring: "ring-violet-300",
    tint: "bg-violet-50",
    fill: "bg-violet-600",
  },
  completed: {
    label: "Hoàn thành",
    badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20",
    icon: CheckCircle2,
    ring: "ring-emerald-300",
    tint: "bg-emerald-50",
    fill: "bg-emerald-500",
  },
  failed: {
    label: "Lỗi",
    badge: "bg-rose-100 text-rose-700 ring-rose-600/20",
    icon: XCircle,
    ring: "ring-rose-300",
    tint: "bg-rose-50",
    fill: "bg-rose-500",
  },
};

export const INVESTIGATION_SEVERITY_META: Record<InvestigationSeverity, InvestigationSeverityMeta> = {
  critical: { label: "Critical", badge: "bg-rose-100 text-rose-700 ring-rose-600/20", fill: "bg-rose-500", icon: AlertOctagon },
  high: { label: "High", badge: "bg-amber-100 text-amber-700 ring-amber-600/20", fill: "bg-amber-500", icon: ShieldAlert },
  medium: { label: "Medium", badge: "bg-amber-50 text-amber-800 ring-amber-600/20", fill: "bg-amber-400", icon: ShieldAlert },
  low: { label: "Low", badge: "bg-blue-100 text-blue-700 ring-blue-600/20", fill: "bg-blue-500", icon: Search },
  info: { label: "Info", badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", fill: "bg-emerald-500", icon: CheckCircle2 },
};

export const INVESTIGATION_STATUS_FALLBACK = INVESTIGATION_STATUS_META.pending;
export const INVESTIGATION_SEVERITY_FALLBACK = INVESTIGATION_SEVERITY_META.info;

/** Label theo ngữ cảnh: gọn (chip/filter) hoặc đầy đủ (badge trang chi tiết). */
export function statusLabel(status: InvestigationStatus, long = false): string {
  const meta = INVESTIGATION_STATUS_META[status];
  return long ? (meta.longLabel ?? meta.label) : meta.label;
}
