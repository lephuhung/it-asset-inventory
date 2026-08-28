"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Activity, Ghost, Monitor, Ticket, TrendingUp, Wifi, WifiOff } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem, MachineStatus, Organization, StatsOverview } from "@/lib/types";
import { flattenOrgTree } from "@/lib/format";
import { Card, ErrorBanner, PageHeader, PageResponse, Spinner, StatusDot } from "@/components/ui";
import { MACHINE_STATUS_META } from "@/lib/format";

const DAY_MS = 86_400_000;

/* Màu biểu đồ khớp chấm trạng thái (MACHINE_STATUS_META.dot) —
   chỉ dùng làm điểm chấm/thanh dữ liệu, không tô nền cấu trúc (Design.md). */
const STATUS_CHART: Record<MachineStatus, string> = {
  online: "#1aae39",
  offline: "#a39e98",
  lost: "#d44c47",
  pending: "#dd5b00",
  decommissioned: "#b8b4af",
};

/** Dashboard lãnh đạo (#17, Phase 4) — read-only, số to trên card trắng,
    biểu đồ donut + thanh xếp lớp rõ ràng. */
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
        api.get<PageResponse<MachineListItem>>("/machines", { limit: 50 }),
        api.get<Organization[]>("/orgs").catch(() => [] as Organization[]),
      ]);
      setStats(s);
      setMachines(m.items);
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

  /** Phân bố trạng thái toàn bộ máy — nguồn cho donut + legend. */
  const statusCounts = useMemo(() => {
    const order: MachineStatus[] = ["online", "offline", "lost", "pending", "decommissioned"];
    return order
      .map((s) => ({ status: s, count: machines.filter((m) => m.status === s).length }))
      .filter((x) => x.count > 0 || x.status !== "decommissioned");
  }, [machines]);

  const donutGradient = useMemo(() => {
    const total = machines.length || 1;
    let acc = 0;
    const stops = statusCounts
      .filter((x) => x.count > 0)
      .map(({ status, count }) => {
        const from = (acc / total) * 100;
        acc += count;
        const to = (acc / total) * 100;
        return `${STATUS_CHART[status]} ${from}% ${to}%`;
      });
    return stops.length > 0
      ? `conic-gradient(${stops.join(", ")})`
      : `conic-gradient(var(--color-slate-100) 0% 100%)`;
  }, [machines, statusCounts]);

  if (loading && !stats) return <Spinner label="Đang tải dữ liệu tổng hợp…" />;

  const onlinePct = stats && stats.total_machines > 0 ? Math.round((stats.online / stats.total_machines) * 100) : 0;

  /* KPI Notion-style: card trắng + hairline, màu chỉ là điểm nhấn icon/chấm */
  const kpis = [
    {
      label: "Tổng máy tính",
      value: stats?.total_machines ?? 0,
      sub: `${orgName.size} tổ chức`,
      icon: <Monitor className="size-4" />,
      chip: "bg-slate-100 text-slate-600",
      dot: "bg-slate-400",
    },
    {
      label: "Đang hoạt động",
      value: stats?.online ?? 0,
      sub: `Tỉ lệ online ${onlinePct}%`,
      icon: <Wifi className="size-4" />,
      chip: "bg-emerald-50 text-emerald-600",
      dot: "bg-emerald-500",
    },
    {
      label: "Tạm ngừng",
      value: stats?.offline ?? 0,
      sub: "Không heartbeat gần đây",
      icon: <WifiOff className="size-4" />,
      chip: "bg-slate-50 text-slate-500",
      dot: "bg-slate-400",
    },
    {
      label: "Máy mất kết nối",
      value: stats?.lost ?? 0,
      sub: `>30 ngày: ${ghostBuckets.over30} · >60: ${ghostBuckets.over60} · >90: ${ghostBuckets.over90}`,
      icon: <Ghost className="size-4" />,
      chip: "bg-rose-50 text-rose-500",
      dot: "bg-rose-500",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Bảng điều khiển lãnh đạo"
        description="View read-only — số liệu tài sản máy tính toàn đơn vị (#17)"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* ── KPI lớn — card trắng, số ink to, điểm nhấn màu ở icon/chấm ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
                <StatusDot className={k.dot} /> {k.label}
              </p>
              <span className={`flex size-8 items-center justify-center rounded-md ${k.chip}`}>{k.icon}</span>
            </div>
            <p className="mt-3 text-5xl font-bold tabular-nums tracking-tight text-slate-900">{k.value}</p>
            <p className="mt-1.5 truncate text-xs text-slate-400">{k.sub}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        {/* ── Biểu đồ donut trạng thái máy ── */}
        <Card title="Trạng thái máy tính" subtitle="Tỉ trọng từng trạng thái trên tổng số máy">
          <div className="flex items-center gap-5">
            {/* Donut CSS thuần (conic-gradient) — không cần thư viện */}
            <div
              role="img"
              aria-label="Biểu đồ tròn trạng thái máy tính"
              className="relative size-36 shrink-0 rounded-full transition-colors"
              style={{ background: donutGradient }}
            >
              <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-white shadow-sm">
                <span className="text-2xl font-bold tabular-nums tracking-tight text-slate-900">
                  {machines.length}
                </span>
                <span className="text-[10px] uppercase tracking-wide text-slate-400">máy</span>
              </div>
            </div>

            {/* Legend với số liệu + tỉ lệ */}
            <ul className="min-w-0 flex-1 space-y-2">
              {statusCounts.map(({ status, count }) => {
                const meta = MACHINE_STATUS_META[status];
                const pct = machines.length > 0 ? Math.round((count / machines.length) * 100) : 0;
                return (
                  <li key={status} className="flex items-center gap-2 text-sm">
                    <StatusDot className={`shrink-0 ${meta.dot}`} />
                    <span className="min-w-0 flex-1 truncate text-slate-600">{meta.label}</span>
                    <b className="tabular-nums text-slate-900">{count}</b>
                    <span className="w-9 shrink-0 text-right text-xs tabular-nums text-slate-400">{pct}%</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </Card>

        {/* ── Thanh xếp lớp theo tổ chức — mỗi bar chuẩn 100% theo tổng của org ── */}
        <Card
          className="lg:col-span-2"
          title="Phân bố máy theo tổ chức"
          subtitle="Online / tạm ngừng / máy mất kết nối — 10 tổ chức lớn nhất"
          padded={false}
        >
          <div className="space-y-3.5 p-5">
            {perOrg.length === 0 && <p className="text-sm text-slate-500">Chưa có dữ liệu máy.</p>}
            {perOrg.map((p) => {
              // Mỗi bar luôn đầy 100% — segment chiếm đúng tỉ lệ trong tổng của org đó
              const seg = (n: number) => `${p.total > 0 ? (n / p.total) * 100 : 0}%`;
              return (
                <div key={p.orgId}>
                  <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
                    <span className="min-w-0 truncate font-medium text-slate-700">{p.name}</span>
                    <span className="shrink-0 tabular-nums text-slate-400">
                      <b className="font-semibold text-emerald-600">{p.online}</b>
                      {" / "}
                      {p.total} máy
                    </span>
                  </div>
                  <div className="flex h-3.5 w-full overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full bg-emerald-500" style={{ width: seg(p.online) }} title={`Online: ${p.online}`} />
                    <div className="h-full bg-slate-400" style={{ width: seg(p.offline) }} title={`Tạm ngừng: ${p.offline}`} />
                    <div className="h-full bg-rose-500" style={{ width: seg(p.lost) }} title={`Máy mất kết nối: ${p.lost}`} />
                  </div>
                </div>
              );
            })}
            {perOrg.length > 0 && (
              <div className="flex flex-wrap gap-4 pt-1 text-xs text-slate-500">
                <span className="inline-flex items-center gap-1.5"><StatusDot className="bg-emerald-500" /> Online</span>
                <span className="inline-flex items-center gap-1.5"><StatusDot className="bg-slate-400" /> Tạm ngừng</span>
                <span className="inline-flex items-center gap-1.5"><StatusDot className="bg-rose-500" /> Máy mất kết nối</span>
              </div>
            )}
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {/* Tín hiệu triển khai */}
        <Card title="Tín hiệu triển khai" subtitle="Phễu token — còn bao nhiêu máy chưa cài">
          <div className="flex items-center gap-4">
            <div className="flex size-16 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-3xl font-bold tabular-nums text-amber-600">
              {stats?.pending_tokens ?? 0}
            </div>
            <div className="text-sm text-slate-600">
              <p className="font-medium">Token đã phát, chờ cài</p>
              <p className="text-xs text-slate-400">
                {stats?.expired_tokens ?? 0} token hết hạn cần gửi lại
              </p>
              <Link href="/tokens" className="mt-1 inline-block text-xs font-medium text-brand-600 hover:underline">
                Mở phễu triển khai →
              </Link>
            </div>
          </div>
        </Card>

        {/* Chỉ số vận hành — kèm thanh tỉ lệ trực quan */}
        <Card title="Chỉ số vận hành">
          <ul className="space-y-3.5 text-sm">
            <li>
              <div className="mb-1 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-slate-600">
                  <Activity className="size-4 text-emerald-500" /> Tỉ lệ online
                </span>
                <b className="tabular-nums">{onlinePct}%</b>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-emerald-500" style={{ width: `${onlinePct}%` }} />
              </div>
            </li>
            <li>
              <div className="mb-1 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-slate-600">
                  <Ghost className="size-4 text-rose-500" /> Máy mất kết nối / tổng
                </span>
                <b className="tabular-nums">
                  {stats && stats.total_machines > 0 ? Math.round(((stats.lost ?? 0) / stats.total_machines) * 100) : 0}%
                </b>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-rose-500"
                  style={{
                    width: `${stats && stats.total_machines > 0 ? Math.round(((stats.lost ?? 0) / stats.total_machines) * 100) : 0}%`,
                  }}
                />
              </div>
            </li>
            <li className="flex items-center justify-between pt-0.5">
              <span className="inline-flex items-center gap-1.5 text-slate-600">
                <Ticket className="size-4 text-amber-500" /> Token chờ cài
              </span>
              <b className="tabular-nums">{stats?.pending_tokens ?? 0}</b>
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
