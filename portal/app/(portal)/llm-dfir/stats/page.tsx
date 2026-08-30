"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertOctagon,
  Brain,
  Clock,
  ListTree,
  Loader2,
  RefreshCw,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, ErrorBanner, KpiCard, Select, Spinner } from "@/components/ui";
import type { DfirInvestigationStats } from "@/lib/types";

/* Pill tinted + fill + màu biểu đồ theo Design.md — màu remap trong globals.css */
const STATUS_STYLES: Record<string, { label: string; chip: string; fill: string }> = {
  pending: { label: "Chờ", chip: "bg-slate-100 text-slate-700 ring-slate-600/20", fill: "bg-slate-400" },
  running: { label: "Đang khởi động", chip: "bg-blue-100 text-blue-700 ring-blue-600/20", fill: "bg-blue-500" },
  collecting: { label: "Đang thu thập", chip: "bg-sky-50 text-sky-700 ring-sky-600/20", fill: "bg-sky-600" },
  analyzing: { label: "Đang phân tích", chip: "bg-violet-100 text-violet-700 ring-violet-600/20", fill: "bg-violet-600" },
  completed: { label: "Hoàn thành", chip: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", fill: "bg-emerald-500" },
  failed: { label: "Lỗi", chip: "bg-rose-100 text-rose-700 ring-rose-600/20", fill: "bg-rose-500" },
};

const SEVERITY_STYLES: Record<string, { chip: string; fill: string }> = {
  critical: { chip: "bg-rose-100 text-rose-700 ring-rose-600/20", fill: "bg-rose-500" },
  high: { chip: "bg-amber-100 text-amber-700 ring-amber-600/20", fill: "bg-amber-500" },
  medium: { chip: "bg-amber-50 text-amber-800 ring-amber-600/20", fill: "bg-amber-400" },
  low: { chip: "bg-blue-100 text-blue-700 ring-blue-600/20", fill: "bg-blue-500" },
  info: { chip: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", fill: "bg-emerald-500" },
};

// Màu segment cho biểu đồ tròn (dùng CSS var của token, không hardcode hex)
const STATUS_CHART: Record<string, string> = {
  pending: "var(--color-slate-400)",
  running: "var(--color-blue-500)",
  collecting: "var(--color-sky-600)",
  analyzing: "var(--color-violet-600)",
  completed: "var(--color-emerald-500)",
  failed: "var(--color-rose-500)",
};
const SEVERITY_CHART: Record<string, string> = {
  critical: "var(--color-rose-500)",
  high: "var(--color-amber-500)",
  medium: "var(--color-amber-400)",
  low: "var(--color-blue-500)",
  info: "var(--color-emerald-500)",
};

export default function StatsPage() {
  const router = useRouter();
  const [stats, setStats] = useState<DfirInvestigationStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const s = await api.get<DfirInvestigationStats>(
        `/admin/llm-dfir/stats?days=${days}`,
      );
      setStats(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được thống kê");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !stats) return <Spinner label="Đang tải thống kê..." />;
  if (error && !stats) return <ErrorBanner message={error} onRetry={load} />;
  if (!stats) return null;

  const statusData = Object.entries(stats.by_status)
    .sort((a, b) => b[1] - a[1])
    .map(([status, count]) => ({
      label: STATUS_STYLES[status]?.label ?? status,
      value: count,
      color: STATUS_CHART[status] ?? "var(--color-slate-400)",
    }));

  const severityData = ["critical", "high", "medium", "low", "info"]
    .filter((s) => stats.by_severity[s] !== undefined)
    .map((sev) => ({
      label: sev,
      value: stats.by_severity[sev],
      color: SEVERITY_CHART[sev] ?? "var(--color-slate-400)",
    }));

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
              Thống kê điều tra AI
            </h1>
            <p className="mt-0.5 text-sm leading-snug text-slate-500">
              Tổng quan về các cuộc điều tra do AI (Velociraptor + LLM)
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
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-3.5" /> Tải lại
          </Button>
          <Button variant="outline" size="sm" onClick={() => router.push("/llm-dfir/investigations")}>
            <ListTree className="size-3.5" /> Danh sách
          </Button>
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          label="Tổng investigation"
          value={stats.total}
          icon={<Activity className="size-4" />}
          accent="bg-blue-100 text-blue-700"
        />
        <KpiCard
          label="24 giờ qua"
          value={stats.recent_24h}
          icon={<TrendingUp className="size-4" />}
          accent="bg-emerald-100 text-emerald-700"
        />
        <KpiCard
          label="7 ngày qua"
          value={stats.recent_7d}
          icon={<Clock className="size-4" />}
          accent="bg-violet-100 text-violet-700"
        />
        <KpiCard
          label="Thời gian xử lý TB"
          value={stats.avg_duration_seconds ? `${stats.avg_duration_seconds.toFixed(1)}s` : "—"}
          icon={<Loader2 className="size-4" />}
          accent="bg-amber-100 text-amber-700"
        />
      </div>

      {/* Status + Severity (biểu đồ tròn) + Top machines */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* By status — donut */}
        <Card title="Theo trạng thái">
          {statusData.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có dữ liệu</p>
          ) : (
            <div className="flex flex-col items-center">
              <DonutChart
                data={statusData}
                centerLabel={String(stats.total)}
                centerSub="tổng"
              />
              <DonutLegend data={statusData} />
            </div>
          )}
        </Card>

        {/* By severity — donut */}
        <Card title="Theo mức độ">
          {severityData.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có dữ liệu</p>
          ) : (
            <div className="flex flex-col items-center">
              <DonutChart
                data={severityData}
                centerLabel={String(stats.total)}
                centerSub="tổng"
              />
              <DonutLegend data={severityData} />
            </div>
          )}
        </Card>

        {/* Top machines */}
        <Card title="Top máy có nhiều điều tra">
          {stats.by_machine.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có dữ liệu</p>
          ) : (
            <div className="space-y-1">
              {stats.by_machine.map((m) => (
                <button
                  key={m.machine_id}
                  onClick={() => router.push(`/machines/${m.machine_id}`)}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-150 motion-reduce:transition-none hover:bg-slate-50/70"
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

      {/* Daily trend — line/area chart */}
      <Card
        title={`Investigation theo ngày (${stats.daily_counts.length} ngày có dữ liệu)`}
      >
        {stats.daily_counts.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-500">Chưa có dữ liệu</p>
        ) : (
          <DailyLineChart points={stats.daily_counts} />
        )}
        <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full bg-brand-600" />
            Investigation
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full border-t-2 border-dashed border-rose-500" />
            Critical
          </span>
        </div>
      </Card>

      {/* Top findings (MITRE ATT&CK) */}
      {stats.top_findings.length > 0 && (
        <Card title="Top MITRE ATT&CK techniques phát hiện">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold">MITRE ID</th>
                  <th className="px-4 py-3 text-left font-semibold">Tên</th>
                  <th className="px-4 py-3 text-right font-semibold">Số lần</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {stats.top_findings.map((f, i) => (
                  <tr key={i} className="transition-colors hover:bg-slate-50/70">
                    <td className="px-4 py-2.5">
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
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
        </Card>
      )}
    </div>
  );
}

/* ── Biểu đồ tròn (donut) — SVG thuần, màu theo design token ── */
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
          y={cy}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-slate-900"
          style={{ fontSize: 26, fontWeight: 700 }}
        >
          {centerLabel}
        </text>
      )}
      {centerSub != null && (
        <text
          x={cx}
          y={cy + 18}
          textAnchor="middle"
          className="fill-slate-400"
          style={{ fontSize: 11 }}
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
            <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: d.color }} />
            <span className="truncate text-slate-600">{d.label}</span>
          </span>
          <span className="shrink-0 font-mono tabular-nums text-slate-600">
            {d.value} ({total ? ((d.value / total) * 100).toFixed(1) : 0}%)
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ── Biểu đồ đường + vùng (line/area) theo ngày ── */
function DailyLineChart({ points }: { points: { date: string; total: number; critical: number }[] }) {
  const W = 660;
  const H = 220;
  const pad = { l: 36, r: 16, t: 18, b: 30 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const maxV = Math.max(1, ...points.map((p) => p.total));
  const n = points.length;
  const x = (i: number) => pad.l + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
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
          <line
            x1={pad.l}
            y1={y(v)}
            x2={W - pad.r}
            y2={y(v)}
            className="stroke-slate-100"
            strokeWidth={1}
          />
          <text
            x={pad.l - 8}
            y={y(v)}
            textAnchor="end"
            dominantBaseline="central"
            className="fill-slate-400"
            style={{ fontSize: 10 }}
          >
            {v}
          </text>
        </g>
      ))}
      <path d={areaPath} className="fill-brand-100" />
      <path d={critPath} className="stroke-rose-500" strokeWidth={1.75} strokeDasharray="4 3" fill="none" />
      <path d={linePath} className="stroke-brand-600" strokeWidth={2.25} fill="none" strokeLinejoin="round" strokeLinecap="round" />
      {pts.map(([px, py], i) => (
        <circle key={i} cx={px} cy={py} r={3.5} className="fill-brand-600">
          <title>{`${points[i].date}: ${points[i].total} investigation`}</title>
        </circle>
      ))}
      {points.map((p, i) =>
        i % step === 0 || i === n - 1 ? (
          <text
            key={i}
            x={x(i)}
            y={H - pad.b + 16}
            textAnchor="middle"
            className="fill-slate-400"
            style={{ fontSize: 10 }}
          >
            {p.date.slice(5)}
          </text>
        ) : null,
      )}
    </svg>
  );
}
