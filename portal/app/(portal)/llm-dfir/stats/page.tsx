"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertOctagon,
  Brain,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  Filter,
  ListTree,
  Loader2,
  RefreshCw,
  Search,
  ShieldAlert,
  StopCircle,
  Trash2,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  KpiCard,
  Select,
  Spinner,
} from "@/components/ui";
import {
  DfirInvestigation,
  DfirInvestigationListOut,
  DfirInvestigationStats,
  InvestigationSeverity,
  InvestigationStatus,
} from "@/lib/types";
import { formatDateTime } from "@/lib/format";

/* Pill tinted + fill + màu biểu đồ theo Design.md — màu remap trong globals.css */
const STATUS_STYLES: Record<InvestigationStatus, { label: string; chip: string; fill: string; icon: React.ElementType }> = {
  pending:    { label: "Chờ",          chip: "bg-slate-100 text-slate-700 ring-slate-600/20", fill: "bg-slate-400",    icon: Clock },
  running:    { label: "Khởi động",   chip: "bg-blue-100 text-blue-700 ring-blue-600/20",  fill: "bg-blue-500",    icon: Loader2 },
  collecting: { label: "Thu thập",     chip: "bg-sky-50 text-sky-700 ring-sky-600/20",    fill: "bg-sky-600",     icon: RefreshCw },
  analyzing:  { label: "Phân tích",    chip: "bg-violet-100 text-violet-700 ring-violet-600/20", fill: "bg-violet-600", icon: Brain },
  completed:  { label: "Hoàn thành",  chip: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", fill: "bg-emerald-500", icon: Activity },
  failed:     { label: "Lỗi",         chip: "bg-rose-100 text-rose-700 ring-rose-600/20", fill: "bg-rose-500",    icon: XCircle },
};

const SEVERITY_STYLES: Record<InvestigationSeverity, { label: string; chip: string; fill: string; icon: React.ElementType }> = {
  critical: { label: "Critical", chip: "bg-rose-100 text-rose-700 ring-rose-600/20",    fill: "bg-rose-500",    icon: AlertOctagon },
  high:     { label: "High",     chip: "bg-amber-100 text-amber-700 ring-amber-600/20", fill: "bg-amber-500",   icon: ShieldAlert },
  medium:   { label: "Medium",   chip: "bg-amber-50 text-amber-800 ring-amber-600/20", fill: "bg-amber-400",   icon: ShieldAlert },
  low:      { label: "Low",      chip: "bg-blue-100 text-blue-700 ring-blue-600/20",    fill: "bg-blue-500",    icon: Search },
  info:     { label: "Info",     chip: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", fill: "bg-emerald-500", icon: Activity },
};

const STATUS_FALLBACK = STATUS_STYLES.pending;
const SEVERITY_FALLBACK = SEVERITY_STYLES.info;

const PAGE_SIZE = 20;

// Màu segment cho biểu đồ tròn (dùng CSS var của token, không hardcode hex)
const STATUS_CHART: Record<string, string> = {
  pending:    "var(--color-slate-400)",
  running:    "var(--color-blue-500)",
  collecting: "var(--color-sky-600)",
  analyzing:  "var(--color-violet-600)",
  completed:  "var(--color-emerald-500)",
  failed:     "var(--color-rose-500)",
};
const SEVERITY_CHART: Record<string, string> = {
  critical: "var(--color-rose-500)",
  high:     "var(--color-amber-500)",
  medium:   "var(--color-amber-400)",
  low:      "var(--color-blue-500)",
  info:     "var(--color-emerald-500)",
};

export default function StatsPage() {
  const router = useRouter();

  // Stats state
  const [stats, setStats] = useState<DfirInvestigationStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  // List state
  const [listData, setListData] = useState<DfirInvestigationListOut | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [machineFilter, setMachineFilter] = useState<string>("");

  // Action state
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadStats = useCallback(async () => {
    try {
      setStatsLoading(true);
      const s = await api.get<DfirInvestigationStats>(
        `/admin/llm-dfir/stats?days=${days}`,
      );
      setStats(s);
      setStatsError(null);
    } catch (e) {
      setStatsError(e instanceof Error ? e.message : "Không tải được thống kê");
    } finally {
      setStatsLoading(false);
    }
  }, [days]);

  const loadList = useCallback(async () => {
    try {
      setListLoading(true);
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
      setListData(d);
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Không tải được danh sách");
    } finally {
      setListLoading(false);
    }
  }, [page, machineFilter, statusFilter, severityFilter]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // Tự làm mới mỗi 10s để theo dõi trạng thái investigation đang chạy.
  // Bỏ qua tick nếu lượt trước chưa xong (tránh request chồng lấn) hoặc tab đang ẩn.
  const pollingRef = useRef(false);
  useEffect(() => {
    const tick = () => {
      if (pollingRef.current || document.hidden) return;
      pollingRef.current = true;
      void Promise.allSettled([loadStats(), loadList()]).finally(() => {
        pollingRef.current = false;
      });
    };
    const id = setInterval(tick, 10_000);
    return () => clearInterval(id);
  }, [loadStats, loadList]);

  const handleStop = async () => {
    if (!confirmStop) return;
    setStopping(true);
    try {
      await api.post(`/admin/llm-dfir/investigations/${confirmStop}/stop`);
      setConfirmStop(null);
      void loadList();
      void loadStats();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Dừng thất bại");
    } finally {
      setStopping(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await api.delete(`/admin/llm-dfir/investigations/${confirmDelete}`);
      setConfirmDelete(null);
      void loadList();
      void loadStats();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Xoá thất bại");
    } finally {
      setDeleting(false);
    }
  };

  const hasFilter = machineFilter || statusFilter || severityFilter;

  return (
    <div className="max-w-7xl space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
            <Brain className="size-6" />
          </span>
          <div className="min-w-0">
            <h1 className="text-[22px] font-bold tracking-tight text-slate-900">
              Thống kê &amp; Điều tra AI
            </h1>
            <p className="mt-0.5 text-sm leading-snug text-slate-500">
              Tổng quan và danh sách các cuộc điều tra do AI (Velociraptor + LLM) thực hiện
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value))}
            className="w-28"
            aria-label="Khoảng thời gian"
          >
            <option value="7">7 ngày</option>
            <option value="30">30 ngày</option>
            <option value="90">90 ngày</option>
            <option value="365">1 năm</option>
          </Select>
          <Button variant="outline" size="md" onClick={() => { void loadStats(); void loadList(); }}>
            <RefreshCw className="size-3.5" /> Tải lại
          </Button>
        </div>
      </div>

      {/* KPI cards */}
      {statsLoading && !stats ? (
        <Spinner label="Đang tải thống kê..." />
      ) : statsError && !stats ? (
        <ErrorBanner message={statsError} onRetry={loadStats} />
      ) : stats ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KpiCard
            label="Tổng investigation"
            value={stats.total}
            icon={<Activity className="size-4 text-blue-600" />}
            accent="bg-blue-50"
          />
          <KpiCard
            label="24 giờ qua"
            value={stats.recent_24h}
            icon={<TrendingUp className="size-4 text-emerald-600" />}
            accent="bg-emerald-50"
          />
          <KpiCard
            label="7 ngày qua"
            value={stats.recent_7d}
            icon={<Clock className="size-4 text-violet-600" />}
            accent="bg-violet-50"
          />
          <KpiCard
            label="Thời gian xử lý TB"
            value={stats.avg_duration_seconds ? `${stats.avg_duration_seconds.toFixed(1)}s` : "—"}
            icon={<Loader2 className="size-4 text-amber-600" />}
            accent="bg-amber-50"
          />
        </div>
      ) : null}

      {/* Charts row */}
      {stats && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {/* By status — donut */}
          <Card title="Theo trạng thái">
            {renderStatusDonut(stats)}
          </Card>

          {/* By severity — donut */}
          <Card title="Theo mức độ">
            {renderSeverityDonut(stats)}
          </Card>

          {/* Top machines */}
          <Card title="Top máy có nhiều điều tra">
            {stats.by_machine.length === 0 ? (
              <p className="text-sm text-slate-500">Chưa có dữ liệu</p>
            ) : (
              <div className="divide-y divide-slate-100">
                {stats.by_machine.map((m) => (
                  <button
                    key={m.machine_id}
                    onClick={() => router.push(`/machines/${m.machine_id}`)}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left transition-colors duration-150 motion-reduce:transition-none hover:bg-slate-50/70"
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      {m.critical > 0 ? (
                        <AlertOctagon className="size-4 shrink-0 text-rose-600" />
                      ) : (
                        <ShieldAlert className="size-4 shrink-0 text-amber-500" />
                      )}
                      <span className="truncate text-sm text-slate-700">
                        {m.hostname || m.machine_id.slice(0, 8)}
                      </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2 text-xs">
                      {m.critical > 0 && (
                        <span className="rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700 ring-1 ring-inset ring-rose-600/20">
                          {m.critical} crit
                        </span>
                      )}
                      <span className="font-mono tabular-nums text-slate-500">{m.count}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Charts row: Daily trend & Top MITRE findings (cùng 1 hàng, đồng bộ Design.md) */}
      {stats && (
        <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
          {/* Daily trend */}
          <Card
            title={`Investigation theo ngày (${stats.daily_counts.length} ngày có dữ liệu)`}
            className="flex h-full flex-col"
            bodyClass="flex flex-1 flex-col justify-between"
          >
            {stats.daily_counts.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">Chưa có dữ liệu theo ngày</p>
            ) : (
              <>
                <div className="flex flex-1 flex-col justify-center">
                  <DailyLineChart points={stats.daily_counts} />
                </div>
                <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
                  <div className="flex items-center gap-4">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-0.5 w-4 rounded-full bg-brand-600" />
                      Investigation
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-0.5 w-4 rounded-full border-t-2 border-dashed border-rose-500" />
                      Critical
                    </span>
                  </div>
                  {stats.daily_counts.length === 1 && (
                    <span className="text-[11px] text-slate-400">Dữ liệu tích lũy theo ngày</span>
                  )}
                </div>
              </>
            )}
          </Card>

          {/* Top MITRE findings — edge-to-edge table theo Design.md §ex-data-table-cell */}
          <Card
            title="Top MITRE ATT&amp;CK techniques phát hiện"
            padded={false}
            className="flex h-full flex-col"
            bodyClass="flex flex-1 flex-col min-h-0"
          >
            {stats.top_findings.length === 0 ? (
              <div className="flex flex-1 items-center justify-center p-8">
                <p className="text-center text-sm text-slate-500">Chưa phát hiện kỹ thuật MITRE nào</p>
              </div>
            ) : (
              <div className="flex-1 overflow-x-auto overflow-y-auto max-h-[240px]">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 text-[11px] font-semibold uppercase tracking-wider text-slate-500 backdrop-blur-xs">
                    <tr>
                      <th className="px-4 py-2.5 text-left font-semibold">MITRE ID</th>
                      <th className="px-4 py-2.5 text-left font-semibold">Tên kỹ thuật</th>
                      <th className="px-4 py-2.5 text-right font-semibold">Số lần</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {stats.top_findings.map((f, i) => (
                      <tr key={i} className="transition-colors hover:bg-slate-50/70">
                        <td className="px-4 py-2.5">
                          <code className="rounded-xs bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                            {f.mitre_id}
                          </code>
                        </td>
                        <td className="px-4 py-2.5 text-slate-700">{f.title}</td>
                        <td className="px-4 py-2.5 text-right font-mono tabular-nums text-slate-700">
                          {f.count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Investigation list */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-bold tracking-tight text-slate-900">Danh sách điều tra</h2>
            {listData && (
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold text-slate-500">
                {listData.total}
              </span>
            )}
          </div>
        </div>

        {/* Filter bar */}
        <Card>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex h-9.5 items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500 shrink-0">
              <Filter className="size-3.5 text-slate-400" />
              <span>Lọc:</span>
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
                className="w-64 font-mono text-sm"
              />
            </Field>
            <Field label="Trạng thái">
              <Select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
                className="w-44 text-sm"
              >
                <option value="">Tất cả</option>
                {Object.entries(STATUS_STYLES).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
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
                className="w-36 text-sm"
              >
                <option value="">Tất cả</option>
                {(["critical", "high", "medium", "low", "info"] as InvestigationSeverity[]).map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </Select>
            </Field>
            {hasFilter && (
              <Button
                variant="ghost"
                size="sm"
                className="h-9.5 rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-800"
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
        {listLoading && !listData ? (
          <Spinner label="Đang tải danh sách..." />
        ) : listError && !listData ? (
          <ErrorBanner message={listError} onRetry={loadList} />
        ) : !listData || listData.items.length === 0 ? (
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
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {listData.items.map((inv) => (
                <InvestigationCard
                  key={inv.id}
                  inv={inv}
                  onOpen={() => router.push(`/llm-dfir/investigations/${inv.id}`)}
                  onStop={(id) => setConfirmStop(id)}
                  onDelete={(id) => setConfirmDelete(id)}
                  stoppingId={stoppingId}
                />
              ))}
            </div>

            {/* Pagination */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3 text-sm text-slate-500">
              <span>
                Hiển thị <b className="font-semibold text-slate-900">
                  {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, listData.total)}
                </b> / <b className="font-semibold text-slate-900">{listData.total}</b>
              </span>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  aria-label="Trang trước"
                >
                  <ChevronLeft className="size-3.5" />
                </Button>
                <span className="px-2">
                  Trang <b className="font-semibold text-slate-900">{page}</b> / {Math.max(1, Math.ceil(listData.total / PAGE_SIZE))}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={!listData.has_more}
                  aria-label="Trang sau"
                >
                  <ChevronRight className="size-3.5" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Stop confirm */}
      <ConfirmDialog
        open={!!confirmStop}
        onClose={() => setConfirmStop(null)}
        title="Dừng cuộc điều tra?"
        message="Investigation sẽ được đánh dấu là thất bại. Không thể hoàn tác."
        confirmLabel="Dừng lại"
        danger
        loading={stopping}
        onConfirm={handleStop}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        title="Xoá cuộc điều tra?"
        message="Báo cáo và toàn bộ lịch sử chat sẽ bị xoá vĩnh viễn. Không thể hoàn tác."
        confirmLabel="Xoá"
        danger
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}

/* ── Investigation card (2-col grid) ─────────────────────────── */
function InvestigationCard({
  inv,
  onOpen,
  onStop,
  onDelete,
  stoppingId,
}: {
  inv: DfirInvestigation;
  onOpen: () => void;
  onStop: (id: string) => void;
  onDelete: (id: string) => void;
  stoppingId: string | null;
}) {
  const statusStyle = STATUS_STYLES[inv.status] ?? STATUS_FALLBACK;
  const StatusIcon = statusStyle.icon;
  const isActive = ["pending", "running", "collecting", "analyzing"].includes(inv.status);
  const sevStyle = inv.severity ? SEVERITY_STYLES[inv.severity] ?? SEVERITY_FALLBACK : null;
  const SevIcon = sevStyle?.icon;
  const isStopping = stoppingId === inv.id;

  return (
    <Card className="group relative cursor-pointer transition-colors duration-150 motion-reduce:transition-none hover:border-slate-300 hover:bg-slate-50/40">
      {/* Action buttons — top right, outside the clickable area */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-1.5">
        {isActive ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-10 w-10 p-0 text-amber-600 hover:bg-amber-50 hover:text-amber-700"
            disabled={isStopping || stoppingId !== null}
            title="Dừng investigation"
          >
            {isStopping ? <Loader2 className="size-4 animate-spin" /> : <StopCircle className="size-4" />}
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="h-10 w-10 p-0 text-rose-400 hover:bg-rose-50 hover:text-rose-600"
            onClick={(e) => { e.stopPropagation(); onDelete(inv.id); }}
            title="Xoá investigation"
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>

      {/* Clickable card body */}
      <button onClick={onOpen} className="w-full text-left pr-16">
        {/* Hostname */}
        <div className="mb-2 pr-4">
          <p className="truncate text-[15px] font-bold tracking-tight text-slate-900">
            {inv.machine_hostname || inv.machine_id.slice(0, 8)}
          </p>
          <p className="truncate font-mono text-xs text-slate-400">{inv.machine_id.slice(0, 18)}…</p>
        </div>

        {/* Badges row */}
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <Badge className={statusStyle.chip}>
            <StatusIcon className={`size-3 ${isActive ? "animate-spin" : ""}`} />
            {statusStyle.label}
          </Badge>
          {sevStyle && SevIcon && (
            <Badge className={sevStyle.chip}>
              <SevIcon className="size-3" />
              {sevStyle.label}
            </Badge>
          )}
          {inv.external_orchestrator && (
            <Badge className="bg-violet-100 text-violet-700 ring-violet-600/20">
              ext:{inv.external_orchestrator}
            </Badge>
          )}
        </div>

        {/* Metadata grid */}
        <div className="mb-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-[13px] text-slate-500">
          <div className="flex items-center gap-1.5">
            <Clock className="size-3.5 shrink-0 text-slate-400" />
            <span className="truncate">{timeAgo(inv.created_at)}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Activity className="size-3.5 shrink-0 text-slate-400" />
            <span className="truncate">{inv.artifacts.length} artifact{inv.artifacts.length !== 1 ? "s" : ""}</span>
          </div>
          {inv.findings_count != null && (
            <div className="flex items-center gap-1.5">
              <ShieldAlert className="size-3.5 shrink-0 text-slate-400" />
              <span className="truncate">{inv.findings_count} phát hiện</span>
            </div>
          )}
          {inv.llm_model && (
            <div className="flex items-center gap-1.5">
              <Brain className="size-3.5 shrink-0 text-slate-400" />
              <span className="truncate">{inv.llm_model.split(":")[0]}</span>
            </div>
          )}
        </div>

        {/* Tokens + cost row */}
        {(inv.input_tokens != null || (inv.estimated_cost_usd != null && inv.estimated_cost_usd > 0)) && (
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] text-slate-500">
            {inv.input_tokens != null && (
              <span>{inv.input_tokens}→{inv.output_tokens ?? 0} tok</span>
            )}
            {inv.estimated_cost_usd != null && inv.estimated_cost_usd > 0 && (
              <span>${inv.estimated_cost_usd.toFixed(4)}</span>
            )}
          </div>
        )}

        {/* Error */}
        {inv.error && (
          <div className="mt-2 flex items-start gap-1.5 rounded-md border-l-2 border-rose-500 bg-rose-50 px-2.5 py-1.5 text-xs leading-relaxed text-rose-700">
            <XCircle className="mt-0.5 size-3.5 shrink-0 text-rose-500" />
            <span className="min-w-0">{inv.error}</span>
          </div>
        )}
      </button>
    </Card>
  );
}

/* ── Donut helpers (reused from original stats page) ── */
function renderStatusDonut(stats: DfirInvestigationStats) {
  const statusData = Object.entries(stats.by_status)
    .sort((a, b) => b[1] - a[1])
    .map(([status, count]) => ({
      label: STATUS_STYLES[status as InvestigationStatus]?.label ?? status,
      value: count,
      color: STATUS_CHART[status] ?? "var(--color-slate-400)",
    }));

  if (statusData.length === 0) return <p className="text-sm text-slate-500">Chưa có dữ liệu</p>;
  return (
    <div className="flex flex-col items-center">
      <DonutChart data={statusData} centerLabel={String(stats.total)} centerSub="tổng" />
      <DonutLegend data={statusData} />
    </div>
  );
}

function renderSeverityDonut(stats: DfirInvestigationStats) {
  const severityData = (["critical", "high", "medium", "low", "info"] as InvestigationSeverity[])
    .filter((s) => stats.by_severity[s] !== undefined)
    .map((sev) => ({
      label: sev,
      value: stats.by_severity[sev],
      color: SEVERITY_CHART[sev] ?? "var(--color-slate-400)",
    }));

  if (severityData.length === 0) return <p className="text-sm text-slate-500">Chưa có dữ liệu</p>;
  return (
    <div className="flex flex-col items-center">
      <DonutChart data={severityData} centerLabel={String(stats.total)} centerSub="tổng" />
      <DonutLegend data={severityData} />
    </div>
  );
}

/* ── Donut chart (SVG thuần, màu theo design token) ── */
function DonutChart({
  data,
  size = 150,
  thickness = 20,
  centerLabel,
  centerSub,
}: {
  data: { label: string; value: number; color: string }[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerSub?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return null;
  const cx = size / 2;
  const cy = size / 2;
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Biểu đồ tròn">
      <circle cx={cx} cy={cy} r={r} fill="none" className="stroke-slate-100" strokeWidth={thickness} />
      {data.map((d, i) => {
        if (d.value <= 0) return null;
        const frac = d.value / total;
        const len = frac * c;
        const el = (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={d.color}
            strokeWidth={thickness}
            strokeDasharray={`${len} ${Math.max(0, c - len)}`}
            strokeDashoffset={-acc}
            transform={`rotate(-90 ${cx} ${cy})`}
          >
            <title>{`${d.label}: ${d.value} (${(frac * 100).toFixed(1)}%)`}</title>
          </circle>
        );
        acc += len;
        return el;
      })}
      {centerLabel != null && (
        <text
          x={cx}
          y={centerSub ? cy - 7 : cy}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-slate-900 font-bold"
          style={{ fontSize: 24, letterSpacing: "-0.5px" }}
        >
          {centerLabel}
        </text>
      )}
      {centerSub != null && (
        <text
          x={cx}
          y={cy + 13}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-slate-400 font-semibold"
          style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}
        >
          {centerSub}
        </text>
      )}
    </svg>
  );
}

function DonutLegend({ data }: { data: { label: string; value: number; color: string }[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <ul className="mt-4 w-full space-y-1.5">
      {data.map((d) => (
        <li key={d.label} className="flex items-center justify-between gap-2 text-xs">
          <span className="flex min-w-0 items-center gap-2">
            <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: d.color }} />
            <span className="truncate text-slate-600">{d.label}</span>
          </span>
          <span className="shrink-0 font-mono tabular-nums text-slate-700">
            {d.value} ({total ? ((d.value / total) * 100).toFixed(1) : 0}%)
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ── Biểu đồ đường + vùng (line/area) hoặc cột (khi 1 ngày) theo ngày ── */
function DailyLineChart({ points }: { points: { date: string; total: number; critical: number }[] }) {
  const W = 600;
  const H = 210;
  const pad = { l: 36, r: 20, t: 28, b: 30 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const maxV = Math.max(1, ...points.map((p) => p.total));
  const n = points.length;

  // Trường hợp 1 ngày có dữ liệu: Hiển thị dạng cột + badge số lượng trực quan
  if (n === 1) {
    const p = points[0];
    const cx = pad.l + innerW / 2;
    const barW = 56;
    const barX = cx - barW / 2;
    const barH = Math.max(12, (p.total / maxV) * innerH);
    const barY = pad.t + innerH - barH;
    const gridVals = [0, Math.ceil(maxV / 2), maxV];

    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Biểu đồ điều tra theo ngày">
        <defs>
          <linearGradient id="singleDayBarGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-brand-500, #3391e5)" />
            <stop offset="100%" stopColor="var(--color-brand-600, #0075de)" />
          </linearGradient>
        </defs>

        {/* Đường lưới ngang (hairline: #e6e6e6) */}
        {gridVals.map((v) => {
          const gy = pad.t + innerH * (1 - v / maxV);
          return (
            <g key={v}>
              <line x1={pad.l} y1={gy} x2={W - pad.r} y2={gy} stroke="var(--color-slate-200, #e6e6e6)" strokeWidth={1} />
              <text x={pad.l - 8} y={gy} textAnchor="end" dominantBaseline="central" className="fill-slate-400" style={{ fontSize: 10 }}>
                {v}
              </text>
            </g>
          );
        })}

        {/* Cột mờ nền (canvas-soft / slate-50) */}
        <rect
          x={barX}
          y={pad.t}
          width={barW}
          height={innerH}
          rx={4}
          className="fill-slate-100/60"
        />

        {/* Cột chính (Investigation — brand blue) */}
        <rect
          x={barX}
          y={barY}
          width={barW}
          height={barH}
          rx={4}
          fill="url(#singleDayBarGrad)"
        />

        {/* Phần critical nếu có (rose-500) */}
        {p.critical > 0 && (
          <rect
            x={barX + 6}
            y={pad.t + innerH - Math.max(6, (p.critical / maxV) * innerH)}
            width={barW - 12}
            height={Math.max(6, (p.critical / maxV) * innerH)}
            rx={3}
            className="fill-rose-500"
          />
        )}

        {/* Điểm nhấn & Badge-pill số lượng (theo Design.md §badge-pill) */}
        <circle cx={cx} cy={barY} r={4} className="fill-white stroke-brand-600" strokeWidth={2} />
        <g transform={`translate(${cx}, ${barY - 14})`}>
          <rect
            x={-32}
            y={-11}
            width={64}
            height={22}
            rx={11}
            className="fill-white stroke-slate-200"
            strokeWidth={1}
          />
          <text
            x={0}
            y={0}
            textAnchor="middle"
            dominantBaseline="central"
            className="fill-brand-600 font-semibold"
            style={{ fontSize: 11, letterSpacing: "0.01em" }}
          >
            {p.total} lượt
          </text>
        </g>

        {/* Ngày ở trục hoành */}
        <text
          x={cx}
          y={H - pad.b + 18}
          textAnchor="middle"
          className="fill-slate-500 font-medium"
          style={{ fontSize: 11 }}
        >
          {p.date}
        </text>
      </svg>
    );
  }

  // Trường hợp n > 1: Biểu đồ đường (Line + Area)
  const x = (i: number) => pad.l + (i / (n - 1)) * innerW;
  const y = (v: number) => pad.t + innerH * (1 - v / maxV);
  const pts = points.map((p, i) => [x(i), y(p.total)] as const);
  const linePath = pts.map(([px, py], i) => `${i ? "L" : "M"}${px} ${py}`).join(" ");
  const areaPath = `${linePath} L${pts[pts.length - 1][0]} ${pad.t + innerH} L${pts[0][0]} ${pad.t + innerH} Z`;
  const critPath = points.map((p, i) => `${i ? "L" : "M"}${x(i)} ${y(p.critical)}`).join(" ");
  const gridVals = [0, 0.5, 1].map((f) => Math.round(f * maxV));
  const step = Math.max(1, Math.ceil(n / 6));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Biểu đồ đường theo ngày">
      {gridVals.map((v) => (
        <g key={v}>
          <line x1={pad.l} y1={y(v)} x2={W - pad.r} y2={y(v)} stroke="var(--color-slate-200, #e6e6e6)" strokeWidth={1} />
          <text x={pad.l - 8} y={y(v)} textAnchor="end" dominantBaseline="central" className="fill-slate-400" style={{ fontSize: 10 }}>
            {v}
          </text>
        </g>
      ))}
      <path d={areaPath} className="fill-brand-50/70" />
      <path d={critPath} className="stroke-rose-500" strokeWidth={1.75} strokeDasharray="4 3" fill="none" />
      <path d={linePath} className="stroke-brand-600" strokeWidth={2} fill="none" strokeLinejoin="round" strokeLinecap="round" />
      {pts.map(([px, py], i) => (
        <circle key={i} cx={px} cy={py} r={3} className="fill-brand-600">
          <title>{`${points[i].date}: ${points[i].total} investigation`}</title>
        </circle>
      ))}
      {points.map((p, i) =>
        i % step === 0 || i === n - 1 ? (
          <text key={i} x={x(i)} y={H - pad.b + 16} textAnchor="middle" className="fill-slate-500" style={{ fontSize: 10 }}>
            {p.date.slice(5)}
          </text>
        ) : null,
      )}
    </svg>
  );
}

/* ── Utility ── */
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
