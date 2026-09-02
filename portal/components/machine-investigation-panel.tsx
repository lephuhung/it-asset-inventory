"use client";

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertOctagon,
  Brain,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  Filter,
  History,
  Info,
  Loader2,
  RefreshCcw,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,
  Spinner,
} from "@/components/ui";
import type {
  DfirInvestigation,
  DfirInvestigationListOut,
  InvestigationSeverity,
  InvestigationStatus,
} from "@/lib/types";
import { InvestigationMarkdown } from "@/components/investigation-markdown";

/* ── Pill tinted theo Design.md — màu đã remap trong globals.css
   (đồng bộ với trang /admin/llm-dfir/investigations). Các style ở
   đây được dùng cho cả badge trong panel + modal chi tiết. ──  */
const STATUS_STYLES: Record<
  InvestigationStatus,
  { label: string; badge: string; icon: any; ring: string; tint: string }
> = {
  pending: {
    label: "Chờ FIFO",
    badge: "bg-slate-100 text-slate-700 ring-slate-600/20",
    icon: Clock,
    ring: "ring-slate-300",
    tint: "bg-slate-50",
  },
  running: {
    label: "Khởi động",
    badge: "bg-blue-100 text-blue-700 ring-blue-600/20",
    icon: Loader2,
    ring: "ring-blue-300",
    tint: "bg-blue-50",
  },
  collecting: {
    label: "Thu thập",
    badge: "bg-sky-50 text-sky-700 ring-sky-600/20",
    icon: RefreshCcw,
    ring: "ring-sky-300",
    tint: "bg-sky-50",
  },
  analyzing: {
    label: "Phân tích",
    badge: "bg-violet-100 text-violet-700 ring-violet-600/20",
    icon: Brain,
    ring: "ring-violet-300",
    tint: "bg-violet-50",
  },
  completed: {
    label: "Hoàn thành",
    badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20",
    icon: CheckCircle2,
    ring: "ring-emerald-300",
    tint: "bg-emerald-50",
  },
  failed: {
    label: "Lỗi",
    badge: "bg-rose-100 text-rose-700 ring-rose-600/20",
    icon: XCircle,
    ring: "ring-rose-300",
    tint: "bg-rose-50",
  },
};

const SEVERITY_STYLES: Record<
  InvestigationSeverity,
  { label: string; badge: string; icon: any; /** Vạch trái row + glow ring khi selected */ accent: string }
> = {
  critical: {
    label: "Critical",
    badge: "bg-rose-100 text-rose-700 ring-rose-600/20",
    icon: AlertOctagon,
    accent: "bg-rose-500",
  },
  high: {
    label: "High",
    badge: "bg-amber-100 text-amber-700 ring-amber-600/20",
    icon: ShieldAlert,
    accent: "bg-amber-500",
  },
  medium: {
    label: "Medium",
    badge: "bg-amber-50 text-amber-800 ring-amber-600/20",
    icon: ShieldAlert,
    accent: "bg-amber-400",
  },
  low: {
    label: "Low",
    badge: "bg-blue-100 text-blue-700 ring-blue-600/20",
    icon: Search,
    accent: "bg-blue-500",
  },
  info: {
    label: "Info",
    badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20",
    icon: CheckCircle2,
    accent: "bg-emerald-500",
  },
};

const STATUS_FALLBACK = STATUS_STYLES.pending;
const SEVERITY_FALLBACK = SEVERITY_STYLES.info;

/** Các trạng thái "còn đang xử lý" — dùng để quyết định animation + ring glow. */
const ACTIVE_STATUSES: InvestigationStatus[] = ["pending", "running", "collecting", "analyzing"];

const PAGE_SIZE = 10;

interface Props {
  machineId: string;
  machineHostname: string | null;
  open: boolean;
  onClose: () => void;
}

/** Panel phải: lịch sử investigations của 1 máy + modal xem chi tiết.
 *
 *  Style theo Design.md:
 *  - Surface trắng + hairline + shadow Level-2 (Notion "barely-there")
 *  - Primary = màu hành động duy nhất (xanh #0075de); status/severity dùng
 *    palette sticker để phân biệt nhưng KHÔNG cạnh tranh với primary
 *  - Mỗi dòng investigation có vạch trái theo severity (Critical = đỏ,
 *    High = cam, …) — giúp quét nhanh theo mức độ nguy hiểm khi danh sách
 *    dài.
 *  - Active investigation (đang chạy) có ring glow xanh + spinner quay để
 *    tách khỏi các dòng lịch sử tĩnh.
 *  - Có KPI strip tóm tắt tổng quan (tổng cuộc / đang chạy / critical /
 *    findings) ngay dưới header — giúp admin đánh giá máy trong 1 giây. */
export function MachineInvestigationPanel({ machineId, machineHostname, open, onClose }: Props) {
  const [data, setData] = useState<DfirInvestigationListOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const params: Record<string, string> = {
        page: String(page),
        limit: String(PAGE_SIZE),
      };
      if (statusFilter) params.status = statusFilter;
      const d = await api.get<DfirInvestigationListOut>(
        `/machines/${machineId}/investigations`,
        params,
      );
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được");
    } finally {
      setLoading(false);
    }
  }, [machineId, page, statusFilter]);

  useEffect(() => {
    if (open) {
      void load();
    } else {
      setSelectedId(null);
    }
  }, [open, load]);

  // ESC đóng panel / modal
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (selectedId) setSelectedId(null);
        else onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, selectedId, onClose]);

  // Đếm số investigation đang chạy + critical để hiển thị trên KPI strip.
  // Dùng `useMemo` tránh tính lại mỗi lần render phụ (đỡ re-render list).
  const summary = useMemo(() => {
    const items = data?.items ?? [];
    return {
      total: data?.total ?? items.length,
      running: items.filter((i) => ACTIVE_STATUSES.includes(i.status)).length,
      critical:
        items.filter((i) => i.severity === "critical" || i.severity === "high").length,
      findings: items.reduce((sum, i) => sum + (i.findings_count ?? 0), 0),
    };
  }, [data]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop — gradient + blur nhẹ cho cảm giác panel "nổi" lên trên */}
      <div
        className="fixed inset-0 z-40 bg-slate-900/45 transition-opacity duration-300"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel trượt từ phải — surface trắng + hairline + shadow Level-2.
          Width tăng từ max-w-md (28rem) → max-w-lg (32rem) để chứa row giàu
          thông tin (severity border + meta row + ID + duration). */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl">
        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="relative flex shrink-0 items-start gap-3 border-b border-slate-100 bg-gradient-to-b from-white to-slate-50/40 px-5 py-4">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-100 to-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200">
            <History className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-[15px] font-semibold tracking-tight text-slate-900">
                Lịch sử điều tra AI
              </h2>
              {data && (
                <Badge className="border border-slate-200 bg-white text-[10px] font-semibold text-slate-600 ring-0">
                  {data.total}
                </Badge>
              )}
            </div>
            <p className="mt-0.5 truncate text-[12.5px] text-slate-500">
              <span className="font-medium text-slate-700">
                {machineHostname || machineId.slice(0, 8)}
              </span>
              <span className="mx-1.5 text-slate-300">·</span>
              <span className="font-mono text-[11px] text-slate-400">
                {machineId.slice(0, 8)}
              </span>
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <IconButton
              label="Tải lại"
              onClick={() => void load()}
              disabled={loading}
              className="hover:bg-slate-100 hover:text-slate-600 disabled:opacity-50"
            >
              <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
            </IconButton>
            <IconButton
              label="Đóng (Esc)"
              onClick={onClose}
              className="hover:bg-slate-100 hover:text-slate-600"
            >
              <X className="size-4" />
            </IconButton>
          </div>
        </div>

        {/* ── KPI Strip ────────────────────────────────────────────
            Mini stats: tổng cuộc / đang chạy / critical+high / findings.
            Compact 4 cột — mỗi ô là 1 số + label nhỏ, dùng accent tint
            theo loại (primary cho tổng, brand cho active, rose cho
            critical, emerald cho findings) — quét 1 giây biết ngay máy
            này có bao nhiêu investigation, bao nhiêu đang chạy, có
            critical không. */}
        <div className="grid shrink-0 grid-cols-4 divide-x divide-slate-100 border-b border-slate-100 bg-white">
          <KpiCell
            label="Tổng"
            value={summary.total}
            tone="default"
            active={!statusFilter}
            onClick={() => {
              setStatusFilter("");
              setPage(1);
            }}
          />
          <KpiCell
            label="Đang chạy"
            value={summary.running}
            tone="brand"
            active={statusFilter === "running"}
            onClick={() => {
              setStatusFilter((cur) => (cur === "running" ? "" : "running"));
              setPage(1);
            }}
          />
          <KpiCell
            label="Critical+"
            value={summary.critical}
            tone="rose"
            active={statusFilter === "completed" || statusFilter === "failed"}
            onClick={() => {
              setStatusFilter("completed");
              setPage(1);
            }}
          />
          <KpiCell
            label="Phát hiện"
            value={summary.findings}
            tone="emerald"
            isLast
          />
        </div>

        {/* ── Filter chips ─────────────────────────────────────────
            Pill-style thay cho dropdown — mỗi chip hiển thị nhãn trạng
            thái kèm icon và màu. Active chip dùng ring + tint theo màu
            status (trừ primary mặc định). Cuộn ngang khi tràn. */}
        <div className="shrink-0 border-b border-slate-100 bg-slate-50/40 px-4 py-2.5">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            <Filter className="size-3" />
            Lọc trạng thái
          </div>
          <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <FilterChip
              label="Tất cả"
              active={statusFilter === ""}
              onClick={() => {
                setStatusFilter("");
                setPage(1);
              }}
            />
            {(Object.keys(STATUS_STYLES) as InvestigationStatus[]).map((key) => {
              const s = STATUS_STYLES[key];
              const Icon = s.icon;
              const active = statusFilter === key;
              const isActiveState = ACTIVE_STATUSES.includes(key);
              return (
                <FilterChip
                  key={key}
                  label={s.label}
                  active={active}
                  accent={s.tint}
                  icon={
                    <Icon className={`size-3 ${active && isActiveState ? "animate-spin" : ""}`} />
                  }
                  onClick={() => {
                    setStatusFilter((cur) => (cur === key ? "" : key));
                    setPage(1);
                  }}
                />
              );
            })}
          </div>
        </div>

        {/* ── List ───────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto bg-slate-50/30">
          {loading && !data ? (
            <Spinner label="Đang tải lịch sử..." />
          ) : error ? (
            <div className="p-4">
              <ErrorBanner message={error} onRetry={() => void load()} />
            </div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState
              icon={
                <span className="flex size-14 items-center justify-center rounded-2xl bg-violet-100 text-violet-600">
                  <Brain className="size-7" />
                </span>
              }
              title={
                statusFilter
                  ? "Không có investigation khớp bộ lọc"
                  : "Chưa có investigation nào"
              }
              description={
                statusFilter
                  ? "Bỏ lọc để xem toàn bộ lịch sử."
                  : "Bấm 'Điều tra AI' trên card Velociraptor để bắt đầu cuộc điều tra đầu tiên."
              }
              action={
                statusFilter ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setStatusFilter("");
                      setPage(1);
                    }}
                  >
                    <X className="size-3.5" /> Bỏ lọc
                  </Button>
                ) : null
              }
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.items.map((inv) => (
                <InvestigationHistoryRow
                  key={inv.id}
                  inv={inv}
                  onOpen={() => setSelectedId(inv.id)}
                />
              ))}
            </ul>
          )}
        </div>

        {/* ── Pagination footer ──────────────────────────────────── */}
        {data && data.total > 0 && (
          <Pagination
            page={data.page}
            limit={data.limit}
            total={data.total}
            hasMore={data.has_more}
            onPageChange={(p) => setPage(p)}
          />
        )}
      </div>

      {/* Modal chi tiết */}
      {selectedId && (
        <InvestigationDetailModal
          investigationId={selectedId}
          machineId={machineId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </>
  );
}

/* ── KPI Cell ─────────────────────────────────────────────── */

function KpiCell({
  label,
  value,
  tone,
  active,
  onClick,
  isLast,
}: {
  label: string;
  value: number;
  tone: "default" | "brand" | "rose" | "emerald";
  active?: boolean;
  onClick?: () => void;
  isLast?: boolean;
}) {
  const toneClass: Record<string, string> = {
    default: "text-slate-900",
    brand: "text-brand-600",
    rose: "text-rose-600",
    emerald: "text-emerald-600",
  };
  const interactive = !!onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!interactive}
      className={`group relative flex flex-col items-start justify-center gap-0.5 px-3 py-2.5 text-left transition-colors duration-150 motion-reduce:transition-none ${
        interactive ? "cursor-pointer hover:bg-slate-50" : "cursor-default"
      } ${active ? "bg-brand-50/60" : ""} ${isLast ? "" : ""}`}
    >
      {/* Chỉ báo active — vạch dưới cùng (giống tab underline pattern) */}
      {active && (
        <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-brand-600" />
      )}
      <span className={`text-[18px] font-bold tabular-nums leading-none ${toneClass[tone]}`}>
        {value}
      </span>
      <span className="text-[10.5px] font-medium uppercase tracking-wider text-slate-400">
        {label}
      </span>
    </button>
  );
}

/* ── Filter Chip ───────────────────────────────────────────── */

function FilterChip({
  label,
  active,
  icon,
  accent,
  onClick,
}: {
  label: string;
  active: boolean;
  icon?: React.ReactNode;
  accent?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-all duration-150 motion-reduce:transition-none ${
        active
          ? "border-brand-600 bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-600/30 shadow-sm"
          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
      }`}
    >
      {icon && <span className={active ? "text-brand-700" : ""}>{icon}</span>}
      {label}
    </button>
  );
}

/* ── Investigation Row ─────────────────────────────────────── */

function InvestigationHistoryRow({
  inv,
  onOpen,
}: {
  inv: DfirInvestigation;
  onOpen: () => void;
}) {
  const statusStyle = STATUS_STYLES[inv.status] ?? STATUS_FALLBACK;
  const StatusIcon = statusStyle.icon;
  const active = ACTIVE_STATUSES.includes(inv.status);

  // Hover/focus tint theo status — khi row đang chạy thì nền nhạt màu status.
  const hoverTint = active ? statusStyle.tint : "hover:bg-slate-50/80";

  // Duration — chỉ tính khi đã hoàn thành
  const duration =
    inv.started_at && inv.completed_at
      ? formatDuration(
          new Date(inv.completed_at).getTime() - new Date(inv.started_at).getTime(),
        )
      : null;

  return (
    <li>
      <button
        onClick={onOpen}
        className={`group flex w-full items-stretch gap-3 px-4 py-3 text-left transition-colors duration-150 motion-reduce:transition-none ${hoverTint}`}
      >
        {/* Icon block — gắn liền với status, có vòng pulse nhẹ khi đang chạy */}
        <span
          className={`relative flex size-10 shrink-0 items-center justify-center rounded-lg ${
            statusStyle.tint
          } ${active ? `ring-2 ${statusStyle.ring} ring-offset-1 ring-offset-white` : ""}`}
        >
          <StatusIcon
            className={`size-4 ${
              active ? "animate-spin text-brand-700" : "text-slate-700"
            }`}
          />
          {/* Pulse glow cho các status "đang xử lý" */}
          {active && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 animate-ping rounded-lg bg-brand-400/30"
            />
          )}
        </span>

        {/* Body */}
        <div className="min-w-0 flex-1">
          {/* Hàng 1: status badge + findings chip (severity đã được
              encode vào vạch trái theo màu, không cần badge riêng) */}
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge className={statusStyle.badge}>
              <StatusIcon className={`size-3 ${active ? "animate-spin" : ""}`} />
              {statusStyle.label}
            </Badge>
            {inv.findings_count != null && inv.findings_count > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-700 ring-1 ring-inset ring-amber-200">
                <Sparkles className="size-3" />
                {inv.findings_count} phát hiện
              </span>
            )}
          </div>

          {/* Hàng 2: meta (time + model + duration) */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Clock className="size-3 shrink-0 text-slate-400" />
              {timeAgo(inv.created_at)}
            </span>
            {inv.llm_model && (
              <>
                <span className="text-slate-300">·</span>
                <span className="truncate font-mono text-[11px] text-slate-500">
                  {inv.llm_model}
                </span>
              </>
            )}
            {duration && (
              <>
                <span className="text-slate-300">·</span>
                <span className="text-slate-500">{duration}</span>
              </>
            )}
          </div>

          {/* Hàng 3: artifacts + ID cắt ngắn */}
          <div className="mt-1 flex items-center justify-between gap-2 text-[11px]">
            <div className="flex min-w-0 items-center gap-2 text-slate-400">
              <span className="truncate">
                <span className="font-semibold text-slate-600">
                  {inv.artifacts.length}
                </span>{" "}
                artifact
              </span>
              <span className="text-slate-300">·</span>
              <code className="truncate rounded bg-slate-100 px-1 py-px font-mono text-[10px] text-slate-500">
                #{inv.id.slice(0, 8)}
              </code>
            </div>
            <ChevronRight className="size-4 shrink-0 text-slate-300 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-brand-600 motion-reduce:transition-none" />
          </div>

          {/* Error inline — chỉ hiện khi failed */}
          {inv.status === "failed" && inv.error && (
            <p className="mt-1.5 truncate rounded bg-rose-50 px-2 py-1 font-mono text-[10.5px] text-rose-700 ring-1 ring-inset ring-rose-200">
              {inv.error}
            </p>
          )}
        </div>
      </button>
    </li>
  );
}

/* ── Pagination footer ────────────────────────────────────── */

function Pagination({
  page,
  limit,
  total,
  hasMore,
  onPageChange,
}: {
  page: number;
  limit: number;
  total: number;
  hasMore: boolean;
  onPageChange: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const start = (page - 1) * limit + 1;
  const end = Math.min(page * limit, total);
  return (
    <div className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-100 bg-white px-4 py-2.5">
      <span className="text-[11.5px] text-slate-500">
        <b className="font-semibold text-slate-700">{start}–{end}</b> / {total}
      </span>
      <div className="flex items-center gap-1">
        <IconButton
          label="Trang trước"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page === 1}
          className="border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
        >
          <ChevronLeft className="size-3.5" />
        </IconButton>
        <span className="px-2 text-[11.5px] tabular-nums text-slate-600">
          <b className="font-semibold text-slate-900">{page}</b>
          <span className="text-slate-300"> / </span>
          {totalPages}
        </span>
        <IconButton
          label="Trang sau"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={!hasMore}
          className="border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
        >
          <ChevronRight className="size-3.5" />
        </IconButton>
      </div>
    </div>
  );
}

/* ── Helpers ──────────────────────────────────────────────── */

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s trước`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}ph trước`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}giờ trước`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}ngày trước`;
  // Quá 1 tuần thì hiển thị ngày cụ thể
  return new Date(iso).toLocaleDateString("vi-VN");
}

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}ph${s % 60 ? ` ${s % 60}s` : ""}`;
  const h = Math.floor(m / 60);
  return `${h}giờ${m % 60 ? ` ${m % 60}ph` : ""}`;
}

// ── Modal chi tiết ───────────────────────────────────────────

function InvestigationDetailModal({
  investigationId,
  machineId,
  onClose,
}: {
  investigationId: string;
  machineId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [inv, setInv] = useState<DfirInvestigation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const d = await api.get<DfirInvestigation>(
        `/admin/llm-dfir/investigations/${investigationId}`,
      );
      setInv(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được");
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const statusStyle = inv ? STATUS_STYLES[inv.status] ?? STATUS_FALLBACK : STATUS_FALLBACK;
  const active = inv ? ACTIVE_STATUSES.includes(inv.status) : false;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/55 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header — giữ cùng pattern với panel chính để đồng bộ thị giác */}
        <div className="relative flex shrink-0 items-start gap-3 border-b border-slate-100 bg-gradient-to-b from-white to-slate-50/40 px-5 py-4">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-100 to-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200">
            <Brain className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-[15px] font-semibold tracking-tight text-slate-900">
                {inv ? `Điều tra #${inv.id.slice(0, 8)}` : "Đang tải..."}
              </h2>
              {inv && (
                <Badge className={statusStyle.badge}>
                  <statusStyle.icon className={`size-3 ${active ? "animate-spin" : ""}`} />
                  {statusStyle.label}
                </Badge>
              )}
            </div>
            {inv && (
              <p className="mt-0.5 truncate text-[12.5px] text-slate-500">
                Máy:{" "}
                <span className="font-medium text-slate-700">
                  {inv.machine_hostname || machineId.slice(0, 8)}
                </span>
                <span className="mx-1.5 text-slate-300">·</span>
                <span className="font-mono text-[11px] text-slate-400">
                  #{inv.id.slice(0, 8)}
                </span>
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <IconButton
              label="Đóng (Esc)"
              onClick={onClose}
              className="hover:bg-slate-100 hover:text-slate-600"
            >
              <X className="size-4" />
            </IconButton>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-5 overflow-y-auto overscroll-contain p-5">
          {loading && !inv ? (
            <Spinner label="Đang tải kết quả..." />
          ) : error ? (
            <ErrorBanner message={error} onRetry={load} />
          ) : inv ? (
            <InvestigationDetailContent inv={inv} />
          ) : null}
        </div>

        {/* Footer */}
        {inv && (
          <div className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/50 px-5 py-3">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Đóng
            </Button>
            <Button
              size="sm"
              onClick={() => {
                onClose();
                // Truyền `from` để "Quay lại" biết cần về trang máy
                router.push(
                  `/llm-dfir/investigations/${inv.id}?from=${encodeURIComponent(
                    `/machines/${machineId}`,
                  )}`,
                );
              }}
            >
              <ExternalLink className="size-3.5" />
              Xem trang đầy đủ
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

const InvestigationDetailContent = memo(function InvestigationDetailContent({
  inv,
}: {
  inv: DfirInvestigation;
}) {
  const sev = (inv.severity || "info").toLowerCase() as InvestigationSeverity;
  const statusStyle = STATUS_STYLES[inv.status] ?? STATUS_FALLBACK;
  const StatusIcon = statusStyle.icon;
  const sevStyle = SEVERITY_STYLES[sev] ?? SEVERITY_FALLBACK;
  const SevIcon = sevStyle.icon;
  const active = ACTIVE_STATUSES.includes(inv.status);
  return (
    <>
      {/* Meta — 4 cột tablet, 2 cột mobile. Mỗi ô có label uppercase tiny
          + value bold. Tách khối bằng divider mỏng. */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-slate-200 bg-slate-50/30 p-4 text-sm md:grid-cols-4">
        <MetaItem label="Trạng thái">
          <Badge className={statusStyle.badge}>
            <StatusIcon className={`size-3 ${active ? "animate-spin" : ""}`} />
            {statusStyle.label}
          </Badge>
        </MetaItem>
        <MetaItem label="Mức độ">
          <Badge className={sevStyle.badge}>
            <SevIcon className="size-3" />
            {sevStyle.label}
          </Badge>
        </MetaItem>
        <MetaItem label="Phát hiện">
          <span className="inline-flex items-center gap-1">
            <Sparkles className="size-3.5 text-amber-500" />
            {inv.findings_count ?? 0}
          </span>
        </MetaItem>
        <MetaItem label="Model">
          <span className="font-mono text-[12px]">{inv.llm_model ?? "—"}</span>
        </MetaItem>
        <MetaItem label="Tạo">{new Date(inv.created_at).toLocaleString("vi-VN")}</MetaItem>
        <MetaItem label="Bắt đầu">
          {inv.started_at ? new Date(inv.started_at).toLocaleString("vi-VN") : "—"}
        </MetaItem>
        <MetaItem label="Hoàn thành">
          {inv.completed_at ? new Date(inv.completed_at).toLocaleString("vi-VN") : "—"}
        </MetaItem>
        <MetaItem label="Tokens">
          {(inv.input_tokens ?? 0) + (inv.output_tokens ?? 0)}
        </MetaItem>
      </div>

      {inv.error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <div className="mb-1 flex items-center gap-1.5 font-semibold">
            <XCircle className="size-4" /> Lỗi
          </div>
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed">{inv.error}</pre>
        </div>
      )}

      {/* IoCs */}
      {inv.iocs && inv.iocs.length > 0 && (
        <Section title="Indicators of Compromise (IoC)" icon={<ShieldAlert className="size-4" />}>
          <div className="space-y-1.5">
            {inv.iocs.map((ioc: any, i: number) => (
              <div
                key={i}
                className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2 text-xs ring-1 ring-inset ring-slate-200"
              >
                <span className="rounded bg-violet-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-violet-700">
                  {ioc.type}
                </span>
                <code className="break-all font-mono text-slate-700">{ioc.value}</code>
                {ioc.source && (
                  <span className="text-[10px] text-slate-400">({ioc.source})</span>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Findings */}
      {inv.findings && inv.findings.length > 0 && (
        <Section title={`Findings (${inv.findings.length})`} icon={<AlertOctagon className="size-4" />}>
          <div className="space-y-2">
            {inv.findings.map((f: any, i: number) => {
              const fSev = (f.severity || "info").toLowerCase() as InvestigationSeverity;
              const fStyle = SEVERITY_STYLES[fSev] ?? SEVERITY_FALLBACK;
              return (
                <div
                  key={i}
                  className="rounded-xl border border-slate-200 bg-white p-3 transition-colors hover:border-slate-300"
                >
                  <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                    <Badge className={fStyle.badge}>{f.severity}</Badge>
                    {f.mitre_id && (
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                        {f.mitre_id}
                      </code>
                    )}
                  </div>
                  <div className="text-sm font-semibold tracking-tight text-slate-900">
                    {f.title}
                  </div>
                  {f.evidence && (
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">
                      <span className="font-semibold text-slate-600">Bằng chứng:</span>{" "}
                      {f.evidence}
                    </p>
                  )}
                  {f.recommendation && (
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">
                      <span className="font-semibold text-slate-600">Khuyến nghị:</span>{" "}
                      {f.recommendation}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Report markdown */}
      {inv.report_markdown && (
        <Section title="Báo cáo" icon={<Brain className="size-4" />}>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <InvestigationMarkdown content={inv.report_markdown} />
          </div>
        </Section>
      )}
    </>
  );
});

function MetaItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 text-[10.5px] font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="font-semibold text-slate-900">{children}</div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold tracking-tight text-slate-900">
        <span className="text-slate-400">{icon}</span>
        {title}
      </h3>
      {children}
    </div>
  );
}
