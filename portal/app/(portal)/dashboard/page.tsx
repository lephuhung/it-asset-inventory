"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronRight, Ghost, Hourglass, Monitor, Timer, Ticket, Wifi, WifiOff, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineEvent, MachineListItem, StatsOverview } from "@/lib/types";
import { useRealtime } from "@/components/realtime-context";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Spinner,
  StatusDot,
  TABLE,
  TD,
  THEAD,
  TH,
  TR_HOVER,
  TABLE_WRAP,
} from "@/components/ui";
import { MACHINE_STATUS_META, timeAgo } from "@/lib/format";

function KpiCard({
  label,
  value,
  icon,
  accent,
  sub,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  accent: string;
  sub?: string;
}) {
  return (
    <div className="kpi-card flex h-24 flex-col justify-between p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{label}</p>
        <span className={`flex size-7 items-center justify-center rounded-lg ${accent}`}>{icon}</span>
      </div>
      <div>
        <p className="text-2xl font-bold tabular-nums text-slate-900">{value}</p>
        {sub && <p className="mt-0.5 text-[11px] text-slate-400">{sub}</p>}
      </div>
    </div>
  );
}

const EVENT_ICON: Record<string, string> = {
  online: "bg-emerald-500",
  offline: "bg-slate-400",
  lost: "bg-rose-500",
  decommissioned: "bg-zinc-400",
  pending: "bg-amber-500",
};

export default function DashboardPage() {
  const { connected, events } = useRealtime();
  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [recent, setRecent] = useState<MachineListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const [s, m] = await Promise.all([
        api.get<StatsOverview>("/stats/overview"),
        api.get<MachineListItem[]>("/machines"),
      ]);
      setStats(s);
      setRecent(m.slice(0, 10));
      setError(null);
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : "Không tải được dữ liệu");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(true), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  const lastEvent = useMemo(() => events[0] ?? null, [events]);
  useEffect(() => {
    if (!lastEvent) return;
    const t = setTimeout(() => void load(true), 1500);
    return () => clearTimeout(t);
  }, [lastEvent, load]);

  return (
    <div>
      <PageHeader
        title="Dashboard tổng quan"
        description="Số liệu dữ liệu sống theo thời gian thực — máy online/offline, phễu triển khai token"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && !stats ? (
        <Spinner label="Đang nạp số liệu…" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
            <KpiCard
              label="Tổng máy"
              value={stats?.total_machines ?? 0}
              icon={<Monitor className="size-4 text-[#635a5a]" />}
              accent="bg-[#f5f5f5]"
            />
            <KpiCard
              label="Online"
              value={stats?.online ?? 0}
              icon={<Wifi className="size-4 text-emerald-600" />}
              accent="bg-emerald-50"
              sub="Heartbeat trong chu kỳ"
            />
            <KpiCard
              label="Offline"
              value={stats?.offline ?? 0}
              icon={<WifiOff className="size-4 text-slate-500" />}
              accent="bg-slate-100"
              sub="Quá chu kỳ heartbeat"
            />
            <KpiCard
              label="Máy ma"
              value={stats?.lost ?? 0}
              icon={<Ghost className="size-4 text-rose-600" />}
              accent="bg-rose-50"
              sub="Mất liên lạc > N ngày"
            />
            <KpiCard
              label="Token chờ cài"
              value={stats?.pending_tokens ?? 0}
              icon={<Ticket className="size-4 text-amber-600" />}
              accent="bg-amber-50"
              sub="Đã phát, chưa enroll"
            />
            <KpiCard
              label="Token hết hạn"
              value={stats?.expired_tokens ?? 0}
              icon={<XCircle className="size-4 text-zinc-500" />}
              accent="bg-zinc-100"
              sub="Cần gửi lại lệnh"
            />
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <Card
                title="Máy enroll gần đây"
                subtitle="10 máy mới nhất theo thời gian enroll"
                actions={
                  <Link
                    href="/machines"
                    className="inline-flex items-center gap-0.5 text-xs font-medium text-[#635a5a] hover:underline"
                  >
                    Xem tất cả <ChevronRight className="size-3.5" />
                  </Link>
                }
                padded={false}
              >
                {recent.length === 0 ? (
                  <EmptyState
                    icon={<Monitor className="size-10" />}
                    title="Chưa có máy nào"
                    description="Tạo token triển khai để agent enroll — máy sẽ xuất hiện tại đây khi online."
                  />
                ) : (
                  <div className={TABLE_WRAP}>
                    <table className={TABLE}>
                      <thead className={THEAD}>
                        <tr>
                          <th className={TH}>Hostname</th>
                          <th className={TH}>Trạng thái</th>
                          <th className={TH}>Vòng đời</th>
                          <th className={TH}>Lần cuối online</th>
                          <th className={TH}>Enroll</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recent.map((m) => {
                          const meta = MACHINE_STATUS_META[m.status];
                          return (
                            <tr key={m.id} className={TR_HOVER}>
                              <td className={TD}>
                                <Link
                                  href={`/machines/${m.id}`}
                                  className="font-medium text-[#635a5a] hover:underline"
                                >
                                  {m.hostname ?? "(chưa đặt tên)"}
                                </Link>
                                <p className="text-xs text-slate-400">{m.machine_uuid.slice(0, 8)}</p>
                              </td>
                              <td className={TD}>
                                <Badge className={meta.badge}>
                                  <StatusDot className={meta.dot} />
                                  {meta.label}
                                </Badge>
                              </td>
                              <td className={TD}>{m.is_vm ? "Máy ảo" : "Vật lý"}</td>
                              <td className={TD}>{timeAgo(m.last_seen_at)}</td>
                              <td className={TD}>{timeAgo(m.enrolled_at)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>

            <Card
              title="Luồng realtime"
              subtitle={
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot className={connected ? "bg-emerald-500" : "bg-rose-500"} />
                  {connected ? "Đang nhận sự kiện WebSocket" : "Kết nối bị ngắt — nạp định kỳ"}
                </span>
              }
              padded={false}
            >
              {events.length === 0 ? (
                <EmptyState
                  icon={<Timer className="size-10" />}
                  title="Chưa có sự kiện"
                  description="Khi máy bật/tắt (hoặc chuyển trạng thái), sự kiện sẽ xuất hiện tại đây."
                />
              ) : (
                <ul className="max-h-[26rem] divide-y divide-slate-100 overflow-y-auto">
                  {events.slice(0, 30).map((ev: MachineEvent, idx) => {
                    const meta = MACHINE_STATUS_META[ev.status] ?? MACHINE_STATUS_META.offline;
                    return (
                      <li key={`${ev.machine_id}-${idx}`} className="flex items-center gap-3 px-5 py-2.5">
                        <StatusDot className={EVENT_ICON[ev.status] ?? "bg-slate-400"} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-slate-700">
                            {ev.hostname ?? ev.machine_id.slice(0, 8)}
                          </p>
                          <p className="text-xs text-slate-400">{timeAgo(ev.ts)}</p>
                        </div>
                        <Badge className={meta.badge}>{meta.label}</Badge>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
          </div>

          {(stats?.pending_tokens ?? 0) > 0 && (
            <Card className="mt-6" title="Hành động gợi ý">
              <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
                <Hourglass className="size-5 text-amber-500" />
                <span>
                  Có {stats?.pending_tokens} token đã phát nhưng máy chưa cài — đôn đốc người dùng
                  chạy lệnh cài đặt để máy xuất hiện online.
                </span>
                <Link href="/tokens" className="font-medium text-[#635a5a] hover:underline">
                  Mở phễu triển khai →
                </Link>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}