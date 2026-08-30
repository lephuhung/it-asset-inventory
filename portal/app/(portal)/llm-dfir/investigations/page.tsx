"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertOctagon,
  ArrowLeft,
  Brain,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  Filter,
  Loader2,
  RefreshCcw,
  Search,
  ShieldAlert,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Select,
  Spinner,
} from "@/components/ui";
import type {
  DfirInvestigation,
  DfirInvestigationListOut,
  InvestigationSeverity,
  InvestigationStatus,
} from "@/lib/types";

/* Pill tinted theo Design.md — màu đã remap trong globals.css
   (đồng bộ với trang /admin/llm-dfir/investigations) */
const STATUS_STYLES: Record<
  InvestigationStatus,
  { label: string; badge: string; icon: any }
> = {
  pending: { label: "Chờ", badge: "bg-slate-100 text-slate-700 ring-slate-600/20", icon: Clock },
  running: { label: "Khởi động", badge: "bg-blue-100 text-blue-700 ring-blue-600/20", icon: Loader2 },
  collecting: { label: "Thu thập", badge: "bg-sky-50 text-sky-700 ring-sky-600/20", icon: RefreshCcw },
  analyzing: { label: "Phân tích", badge: "bg-violet-100 text-violet-700 ring-violet-600/20", icon: Brain },
  completed: { label: "Hoàn thành", badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", icon: CheckCircle2 },
  failed: { label: "Lỗi", badge: "bg-rose-100 text-rose-700 ring-rose-600/20", icon: XCircle },
};

const SEVERITY_STYLES: Record<
  InvestigationSeverity,
  { label: string; badge: string; icon: any }
> = {
  critical: { label: "Critical", badge: "bg-rose-100 text-rose-700 ring-rose-600/20", icon: AlertOctagon },
  high: { label: "High", badge: "bg-amber-100 text-amber-700 ring-amber-600/20", icon: ShieldAlert },
  medium: { label: "Medium", badge: "bg-amber-50 text-amber-800 ring-amber-600/20", icon: ShieldAlert },
  low: { label: "Low", badge: "bg-blue-100 text-blue-700 ring-blue-600/20", icon: Search },
  info: { label: "Info", badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", icon: CheckCircle2 },
};

const STATUS_FALLBACK = STATUS_STYLES.pending;
const SEVERITY_FALLBACK = SEVERITY_STYLES.info;

const PAGE_SIZE = 20;

export default function InvestigationsListPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filterMachine = searchParams.get("machine_id") || "";
  const filterStatus = searchParams.get("status") || "";
  const filterSeverity = searchParams.get("severity") || "";
  const pageFromUrl = parseInt(searchParams.get("page") || "1", 10);

  const [data, setData] = useState<DfirInvestigationListOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(pageFromUrl);
  const [statusFilter, setStatusFilter] = useState<string>(filterStatus);
  const [severityFilter, setSeverityFilter] = useState<string>(filterSeverity);
  const [machineFilter, setMachineFilter] = useState<string>(filterMachine);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const params: Record<string, string> = {
        page: String(page),
        limit: String(PAGE_SIZE),
      };
      if (machineFilter) params.machine_id = machineFilter;
      if (statusFilter) params.status = statusFilter;
      if (severityFilter) params.severity = severityFilter;
      const d = await api.get<DfirInvestigationListOut>(
        "/admin/llm-dfir/investigations",
        params,
      );
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được");
    } finally {
      setLoading(false);
    }
  }, [page, machineFilter, statusFilter, severityFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  // Sync URL khi filter thay đổi
  useEffect(() => {
    const sp = new URLSearchParams();
    if (machineFilter) sp.set("machine_id", machineFilter);
    if (statusFilter) sp.set("status", statusFilter);
    if (severityFilter) sp.set("severity", severityFilter);
    if (page > 1) sp.set("page", String(page));
    const qs = sp.toString();
    router.replace(qs ? `/llm-dfir/investigations?${qs}` : "/llm-dfir/investigations", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, machineFilter, statusFilter, severityFilter]);

  const hasFilter = machineFilter || statusFilter || severityFilter;

  return (
    <div className="max-w-6xl space-y-5">
      <div className="space-y-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/llm-dfir/stats")}
          className="-ml-2"
        >
          <ArrowLeft className="size-4" /> Quay lại thống kê
        </Button>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
              <Brain className="size-6" />
            </span>
            <div className="min-w-0">
              <h1 className="text-[22px] font-bold tracking-tight text-slate-900">
                Danh sách điều tra AI
              </h1>
              <p className="mt-0.5 text-sm leading-snug text-slate-500">
                {data
                  ? `Tổng ${data.total} cuộc điều tra${hasFilter ? " (đang lọc)" : ""}`
                  : "Các cuộc điều tra do AI (Velociraptor + LLM) thực hiện"}
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => router.push("/llm-dfir/stats")}>
            <TrendingUp className="size-3.5" /> Xem thống kê
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="mb-0.5 flex items-center gap-2 text-sm font-medium text-slate-600">
            <Filter className="size-4 text-slate-400" />
            Lọc:
          </div>
          <Field label="Máy (UUID)">
            <Input
              type="text"
              value={machineFilter}
              onChange={(e) => {
                setMachineFilter(e.target.value);
                setPage(1);
              }}
              placeholder="vd: 3f436e4d-3ff9-..."
              className="w-64 font-mono"
            />
          </Field>
          <Field label="Trạng thái">
            <Select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="w-44"
            >
              <option value="">Tất cả</option>
              {Object.entries(STATUS_STYLES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Mức độ">
            <Select
              value={severityFilter}
              onChange={(e) => {
                setSeverityFilter(e.target.value);
                setPage(1);
              }}
              className="w-36"
            >
              <option value="">Tất cả</option>
              {["critical", "high", "medium", "low", "info"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          {hasFilter && (
            <Button
              variant="ghost"
              size="sm"
              className="mb-0.5"
              onClick={() => {
                setMachineFilter("");
                setStatusFilter("");
                setSeverityFilter("");
                setPage(1);
              }}
            >
              <X className="size-3.5" /> Xoá lọc
            </Button>
          )}
        </div>
      </Card>

      {/* List */}
      {loading && !data ? (
        <Spinner label="Đang tải danh sách..." />
      ) : error && !data ? (
        <ErrorBanner message={error} onRetry={load} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<Search className="size-8" />}
          title="Chưa có investigation nào"
          description={
            hasFilter
              ? "Thử bỏ bộ lọc hoặc tạo investigation mới."
              : "Vào trang chi tiết máy và bấm 'Điều tra AI' để bắt đầu."
          }
        />
      ) : (
        <>
          <ul className="space-y-3">
            {data.items.map((inv) => (
              <InvestigationRow
                key={inv.id}
                inv={inv}
                onOpen={() => {
                  router.push(`/llm-dfir/investigations/${inv.id}`);
                }}
              />
            ))}
          </ul>

          {/* Pagination */}
          <Pagination
            page={data.page}
            limit={data.limit}
            total={data.total}
            hasMore={data.has_more}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}

function InvestigationRow({
  inv,
  onOpen,
}: {
  inv: DfirInvestigation;
  onOpen: () => void;
}) {
  const statusStyle = STATUS_STYLES[inv.status] ?? STATUS_FALLBACK;
  const StatusIcon = statusStyle.icon;
  const active = ["pending", "running", "collecting", "analyzing"].includes(inv.status);
  const sevStyle = inv.severity ? SEVERITY_STYLES[inv.severity] ?? SEVERITY_FALLBACK : null;
  const SevIcon = sevStyle?.icon;
  return (
    <li>
      <Card className="group cursor-pointer transition-colors duration-150 motion-reduce:transition-none hover:border-slate-300 hover:bg-slate-50/40">
        <button onClick={onOpen} className="w-full text-left">
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <Badge className={statusStyle.badge}>
                  <StatusIcon className={`size-3 ${active ? "animate-spin" : ""}`} />
                  {statusStyle.label}
                </Badge>
                {sevStyle && SevIcon && (
                  <Badge className={sevStyle.badge}>
                    <SevIcon className="size-3" />
                    {sevStyle.label}
                  </Badge>
                )}
                {inv.external_orchestrator && (
                  <Badge className="bg-violet-100 text-violet-700 ring-violet-600/20">
                    ext:{inv.external_orchestrator}
                  </Badge>
                )}
                <span className="truncate text-[15px] font-semibold tracking-tight text-slate-900">
                  {inv.machine_hostname || inv.machine_id.slice(0, 8)}
                </span>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
                <span>{timeAgo(inv.created_at)}</span>
                <span>{inv.artifacts.length} artifacts</span>
                {inv.findings_count != null && <span>{inv.findings_count} phát hiện</span>}
                {inv.llm_model && <span>model: {inv.llm_model}</span>}
                {inv.input_tokens != null && (
                  <span>
                    {inv.input_tokens}→{inv.output_tokens ?? 0} tok
                  </span>
                )}
                {inv.estimated_cost_usd != null && inv.estimated_cost_usd > 0 && (
                  <span>${inv.estimated_cost_usd.toFixed(4)}</span>
                )}
              </div>
              {inv.error && (
                <div className="mt-1 truncate text-xs text-rose-600">Lỗi: {inv.error}</div>
              )}
            </div>
            <ExternalLink className="size-4 shrink-0 text-slate-300 transition-colors duration-150 group-hover:text-brand-600" />
          </div>
        </button>
      </Card>
    </li>
  );
}

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
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3 text-sm text-slate-500">
      <span>
        Hiển thị <b className="font-semibold text-slate-900">{start}–{end}</b> /{" "}
        <b className="font-semibold text-slate-900">{total}</b>
      </span>
      <div className="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page === 1}
          aria-label="Trang trước"
        >
          <ChevronLeft className="size-3.5" />
        </Button>
        <span className="px-2">
          Trang <b className="font-semibold text-slate-900">{page}</b> / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={!hasMore}
          aria-label="Trang sau"
        >
          <ChevronRight className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s trước`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}ph trước`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}giờ trước`;
  const d = Math.floor(h / 24);
  return `${d}ngày trước`;
}
