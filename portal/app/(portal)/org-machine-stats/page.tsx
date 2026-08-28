"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { HardDriveDownload, Monitor, Wifi } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Card, ErrorBanner, PageHeader, PageResponse, Spinner } from "@/components/ui";
import { ORG_TYPE_META } from "@/lib/format";

/** Thống kê số máy theo tổ chức — máy có agent vs máy BMNN (Vận hành dữ liệu offline). */

interface OrgMachineStat {
  org_id: string;
  org_name: string;
  org_type: string;
  total: number;
  with_agent: number;
  isolated: number;
  pending: number;
}

const COLORS = {
  agent: "var(--color-brand-600, #2563eb)",
  isolated: "#f59e0b",
  pending: "#cbd5e1",
};

export default function OrgMachineStatsPage() {
  const [stats, setStats] = useState<OrgMachineStat[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<PageResponse<OrgMachineStat>>("/orgs/machine-stats", { limit: 50 });
      setStats(data.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được thống kê theo tổ chức");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Tổng toàn hệ thống — nguồn cho donut tỉ lệ agent / cách ly. */
  const overall = useMemo(() => {
    const acc = { agent: 0, isolated: 0, pending: 0, total: 0 };
    for (const s of stats ?? []) {
      acc.agent += s.with_agent;
      acc.isolated += s.isolated;
      acc.pending += s.pending;
      acc.total += s.total;
    }
    return acc;
  }, [stats]);

  const donutSlices = useMemo(() => {
    if (!overall.total) return [];
    let acc = 0;
    return [
      { label: "Có agent", count: overall.agent, color: COLORS.agent },
      { label: "Máy BMNN", count: overall.isolated, color: COLORS.isolated },
      { label: "Chờ duyệt", count: overall.pending, color: COLORS.pending },
    ]
      .filter((s) => s.count > 0)
      .map((s) => {
        const from = (acc / overall.total) * 100;
        acc += s.count;
        const to = (acc / overall.total) * 100;
        return { ...s, from, to };
      });
  }, [overall]);

  const donutGradient =
    (donutSlices?.length ?? 0) > 0
      ? `conic-gradient(${donutSlices.map((s) => `${s.color} ${s.from}% ${s.to}%`).join(", ")})`
      : "conic-gradient(var(--color-slate-100) 0% 100%)";

  if (loading && !stats) return <Spinner label="Đang tải thống kê tổ chức…" />;

  const agentPct =
    overall.agent + overall.isolated > 0
      ? Math.round((overall.agent / (overall.agent + overall.isolated)) * 100)
      : 0;

  return (
    <div>
      <PageHeader
        title="Thống kê máy theo tổ chức"
        description="Số máy có agent và máy BMNN (import offline) của từng đơn vị — cập nhật realtime"
        actions={
          <button
            onClick={() => void load()}
            className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
          >
            Nạp lại
          </button>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {/* ── KPI tổng quan ── */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Tổng số máy", value: overall.total, icon: Monitor, chip: "bg-slate-100 text-slate-600" },
          { label: "Có agent", value: overall.agent, icon: Wifi, chip: "bg-blue-50 text-blue-600" },
          { label: "Máy BMNN", value: overall.isolated, icon: HardDriveDownload, chip: "bg-amber-50 text-amber-600" },
          { label: "Chờ duyệt", value: overall.pending, icon: null, chip: "bg-violet-50 text-violet-600" },
        ].map((kpi) => (
          <div key={kpi.label} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{kpi.label}</p>
              {kpi.icon && (
                <span className={`flex size-7 items-center justify-center rounded-md ${kpi.chip}`}>
                  <kpi.icon className="size-3.5" />
                </span>
              )}
            </div>
            <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-slate-900">{kpi.value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* ── Biểu đồ tròn tỉ lệ agent / cách ly toàn bộ ── */}
        <Card title="Tỉ lệ máy Agent và cách ly" subtitle={`Toàn bộ ${overall.total} máy của hệ thống`}>
          <div className="flex items-center gap-5">
            <div
              role="img"
              aria-label="Biểu đồ tròn tỉ lệ máy có agent và máy BMNN"
              className="relative size-36 shrink-0 rounded-full transition-colors"
              style={{ background: donutGradient }}
            >
              <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-white shadow-sm">
                <span className="text-2xl font-bold tabular-nums tracking-tight text-slate-900">{agentPct}%</span>
                <span className="text-[10px] uppercase tracking-wide text-slate-400">agent</span>
              </div>
            </div>
            <ul className="min-w-0 flex-1 space-y-2">
              {[...donutSlices].sort((a, b) => b.count - a.count).map((s) => (
                <li key={s.label} className="flex items-center gap-2 text-sm">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
                  <span className="min-w-0 flex-1 truncate text-slate-600">{s.label}</span>
                  <b className="tabular-nums text-slate-900">{s.count}</b>
                  <span className="w-9 shrink-0 text-right text-xs tabular-nums text-slate-400">
                    {overall.total > 0 ? Math.round((s.count / overall.total) * 100) : 0}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </Card>

        {/* ── Bảng chi tiết theo tổ chức ── */}
        <Card title="Chi tiết theo tổ chức" className="lg:col-span-2">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3 font-semibold whitespace-nowrap">Tổ chức</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Tổng</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Có agent</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Cách ly</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Tỉ lệ agent</th>
                </tr>
              </thead>
              <tbody>
                {(stats ?? []).map((s) => {
                  const base = s.with_agent + s.isolated;
                  const pct = base > 0 ? Math.round((s.with_agent / base) * 100) : 0;
                  return (
                    <tr key={s.org_id} className="transition-colors hover:bg-slate-50/70">
                      <td className="border-b border-slate-100 px-4 py-3 align-middle">
                        <Link href="/machines" className="font-medium text-slate-800 hover:text-brand-700">
                          {s.org_name}
                        </Link>
                        <Badge className="ml-2 bg-zinc-100 text-zinc-600 ring-zinc-500/20">
                          {ORG_TYPE_META[s.org_type as keyof typeof ORG_TYPE_META]?.label ?? s.org_type}
                        </Badge>
                      </td>
                      <td className="border-b border-slate-100 px-4 py-3 text-right font-semibold tabular-nums text-slate-900">{s.total}</td>
                      <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-slate-700">{s.with_agent}</td>
                      <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-amber-700">{s.isolated}</td>
                      <td className="border-b border-slate-100 px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100" aria-hidden>
                            <div className="h-full rounded-full bg-brand-600" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="w-9 text-right text-xs tabular-nums text-slate-500">{pct}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {(stats ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-400">
                      Chưa có dữ liệu máy
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
