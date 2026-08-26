"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Activity, Ghost, Monitor, Ticket, TrendingUp, Wifi, WifiOff } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem, Organization, StatsOverview } from "@/lib/types";
import { flattenOrgTree } from "@/lib/format";
import { Card, ErrorBanner, PageHeader, Spinner, StatusDot } from "@/components/ui";
import { MACHINE_STATUS_META } from "@/lib/format";

const DAY_MS = 86_400_000;

/** Dashboard lãnh đạo (#17, Phase 4) — read-only, số to, biểu đồ rõ ràng. */
export default function LeadershipPage() {
  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, m, o] = await Promise.all([
        api.get<StatsOverview>("/stats/overview"),
        api.get<MachineListItem[]>("/machines"),
        api.get<Organization[]>("/orgs").catch(() => [] as Organization[]),
      ]);
      setStats(s);
      setMachines(m);
      setOrgs(Array.isArray(o) ? o : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được dữ liệu");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const orgName = useMemo(() => {
    const map = new Map<string, string>();
    flattenOrgTree(orgs).forEach(({ org }) => map.set(org.id, org.name));
    return map;
  }, [orgs]);

  const perOrg = useMemo(() => {
    const acc = new Map<string, { total: number; online: number; offline: number; lost: number }>();
    for (const m of machines) {
      const entry = acc.get(m.org_id) ?? { total: 0, online: 0, offline: 0, lost: 0 };
      entry.total += 1;
      if (m.status === "online") entry.online += 1;
      else if (m.status === "lost") entry.lost += 1;
      else entry.offline += 1;
      acc.set(m.org_id, entry);
    }
    return [...acc.entries()]
      .map(([orgId, v]) => ({ orgId, name: orgName.get(orgId) ?? orgId.slice(0, 8), ...v }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 10);
  }, [machines, orgName]);

  const maxTotal = Math.max(1, ...perOrg.map((p) => p.total));

  const ghostBuckets = useMemo(() => {
    const now = Date.now();
    const count = (days: number) =>
      machines.filter((m) => {
        if (m.status !== "lost") return false;
        const last = m.last_seen_at ? new Date(m.last_seen_at).getTime() : now;
        return now - last >= days * DAY_MS;
      }).length;
    return { over30: count(30), over60: count(60), over90: count(90) };
  }, [machines]);

  if (loading && !stats) return <Spinner label="Đang tải dữ liệu tổng hợp…" />;

  const onlinePct = stats && stats.total_machines > 0 ? Math.round((stats.online / stats.total_machines) * 100) : 0;

  return (
    <div>
      <PageHeader
        title="Bảng điều khiển lãnh đạo"
        description="View read-only — số liệu tài sản máy tính toàn đơn vị (#17)"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* KPI lớn */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-2xl bg-slate-900 p-6 text-white shadow-lg">
          <p className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
            <Monitor className="size-3.5" /> Tổng máy tính
          </p>
          <p className="mt-2 text-5xl font-bold tabular-nums">{stats?.total_machines ?? 0}</p>
        </div>
        <div className="rounded-2xl bg-emerald-600 p-6 text-white shadow-lg">
          <p className="flex items-center gap-1.5 text-xs font-medium text-emerald-100">
            <Wifi className="size-3.5" /> Đang hoạt động
          </p>
          <p className="mt-2 text-5xl font-bold tabular-nums">{stats?.online ?? 0}</p>
          <p className="mt-1 text-sm text-emerald-100">Tỉ lệ online: {onlinePct}%</p>
        </div>
        <div className="rounded-2xl bg-slate-600 p-6 text-white shadow-lg">
          <p className="flex items-center gap-1.5 text-xs font-medium text-slate-200">
            <WifiOff className="size-3.5" /> Tạm ngừng
          </p>
          <p className="mt-2 text-5xl font-bold tabular-nums">{stats?.offline ?? 0}</p>
        </div>
        <div className="rounded-2xl bg-rose-600 p-6 text-white shadow-lg">
          <p className="flex items-center gap-1.5 text-xs font-medium text-rose-100">
            <Ghost className="size-3.5" /> Máy ma
          </p>
          <p className="mt-2 text-5xl font-bold tabular-nums">{stats?.lost ?? 0}</p>
          <p className="mt-1 text-sm text-rose-100">
            &gt;30 ngày: {ghostBuckets.over30} · &gt;60: {ghostBuckets.over60} · &gt;90: {ghostBuckets.over90}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        {/* Biểu đồ theo tổ chức */}
        <Card
          className="lg:col-span-2"
          title="Phân bố máy theo tổ chức"
          subtitle="Online / tạm ngừng / máy ma — 10 tổ chức lớn nhất"
          padded={false}
        >
          <div className="space-y-3 p-5">
            {perOrg.length === 0 && <p className="text-sm text-slate-500">Chưa có dữ liệu máy.</p>}
            {perOrg.map((p) => (
              <div key={p.orgId}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="font-medium text-slate-700">{p.name}</span>
                  <span className="tabular-nums text-slate-500">{p.total} máy</span>
                </div>
                <div className="flex h-4 w-full overflow-hidden rounded bg-slate-100">
                  <div className="h-full bg-emerald-500" style={{ width: `${(p.online / maxTotal) * 100}%` }} title={`Online: ${p.online}`} />
                  <div className="h-full bg-slate-300" style={{ width: `${(p.offline / maxTotal) * 100}%` }} title={`Tạm ngừng: ${p.offline}`} />
                  <div className="h-full bg-rose-400" style={{ width: `${(p.lost / maxTotal) * 100}%` }} title={`Máy ma: ${p.lost}`} />
                </div>
              </div>
            ))}
            {perOrg.length > 0 && (
              <div className="flex flex-wrap gap-4 pt-2 text-xs text-slate-500">
                <span className="inline-flex items-center gap-1.5"><StatusDot className="bg-emerald-500" /> Online</span>
                <span className="inline-flex items-center gap-1.5"><StatusDot className="bg-slate-300" /> Tạm ngừng</span>
                <span className="inline-flex items-center gap-1.5"><StatusDot className="bg-rose-400" /> Máy ma</span>
              </div>
            )}
          </div>
        </Card>

        {/* Tổng hợp nhanh */}
        <div className="space-y-6">
          <Card title="Tín hiệu triển khai" subtitle="Phễu token — còn bao nhiêu máy chưa cài">
            <div className="flex items-center gap-4">
              <div className="flex size-16 items-center justify-center rounded-2xl bg-amber-50 text-3xl font-bold text-amber-600">
                {stats?.pending_tokens ?? 0}
              </div>
              <div className="text-sm text-slate-600">
                <p className="font-medium">Token đã phát, chờ cài</p>
                <p className="text-xs text-slate-400">
                  {stats?.expired_tokens ?? 0} token hết hạn cần gửi lại
                </p>
                <Link href="/tokens" className="mt-1 inline-block text-xs font-medium text-blue-600 hover:underline">
                  Mở phễu triển khai →
                </Link>
              </div>
            </div>
          </Card>

          <Card title="Chỉ số vận hành">
            <ul className="space-y-2.5 text-sm">
              <li className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-slate-600">
                  <Activity className="size-4 text-emerald-500" /> Tỉ lệ online
                </span>
                <b className="tabular-nums">{onlinePct}%</b>
              </li>
              <li className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-slate-600">
                  <TrendingUp className="size-4 text-blue-500" /> Máy ma / tổng
                </span>
                <b className="tabular-nums">
                  {stats && stats.total_machines > 0 ? Math.round(((stats.lost ?? 0) / stats.total_machines) * 100) : 0}%
                </b>
              </li>
              <li className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-slate-600">
                  <Ticket className="size-4 text-amber-500" /> Token chờ cài
                </span>
                <b className="tabular-nums">{stats?.pending_tokens ?? 0}</b>
              </li>
            </ul>
          </Card>

          <Card title="Trạng thái chi tiết">
            <ul className="space-y-2 text-sm">
              {(["online", "offline", "lost", "pending", "decommissioned"] as const).map((s) => {
                const meta = MACHINE_STATUS_META[s];
                const count = machines.filter((m) => m.status === s).length;
                return (
                  <li key={s} className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 text-slate-600">
                      <StatusDot className={meta.dot} /> {meta.label}
                    </span>
                    <b className="tabular-nums">{count}</b>
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}