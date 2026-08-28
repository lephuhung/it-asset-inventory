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
  KpiCard,
  PageHeader,
  PageResponse,
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
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const [s, m] = await Promise.all([
        api.get<StatsOverview>("/stats/overview"),
        api.get<PageResponse<MachineListItem>>("/machines", { limit: 50 }),
      ]);
      setStats(s);
      setRecent(m.items.slice(0, 10));
      setUpdatedAt(new Date());
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
        description={
          <>
            Số liệu dữ liệu sống theo thời gian thực — máy online/offline, phễu triển khai token
            {updatedAt && (
              <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                <Timer className="size-3" />
                Cập nhật {updatedAt.toLocaleTimeString("vi-VN")}
              </span>
            )}
          </>
        }
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
              icon={<Monitor className="size-4 text-brand-600" />}
              accent="bg-brand-50"
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
              label="Máy mất kết nối"
              value={stats?.lost ?? 0}
              icon={<Ghost className="size-4 text-rose-600" />}
              accent="bg-rose-50"
              sub="Mất liên lạc > N ngày"
            />
            <KpiCard
              label="Token đã phát, chờ máy cài"
              value={stats?.pending_tokens ?? 0}
              icon={<Ticket className="size-4 text-amber-600" />}
              accent="bg-amber-50"
              sub="Đã cấp lệnh, máy chưa chạy"
              hint="Đếm token đã phát cho người dùng (qua form self-service, bulk CSV hoặc admin tạo) nhưng máy chưa chạy lệnh cài agent. KHÁC với 'Máy ch� duyệt' ở trang Approvals — đó là máy đã enroll thành công và cần admin duyệt."
            />
            <KpiCard
              label="Token hết hạn"
              value={stats?.expired_tokens ?? 0}
              icon={<XCircle className="size-4 text-zinc-500" />}
              accent="bg-zinc-100"
              sub="Cần gửi lại lệnh"
              hint="Token đã quá 72h mà máy chưa cài agent — cần phát lại lệnh mới cho người dùng."
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
                    className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-600 hover:underline"
                  >
                    Xem tất cả <ChevronRight className="size-3.5" />
                  </Link>
                }
                padded={false}
              >
                {(recent?.length ?? 0) === 0 ? (
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
                          <th scope="col" className={TH}>Hostname</th>
                          <th scope="col" className={TH}>Trạng thái</th>
                          <th scope="col" className={TH}>Vòng đời</th>
                          <th scope="col" className={TH}>Lần cuối online</th>
                          <th scope="col" className={TH}>Enroll</th>
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
                                  className="font-medium text-brand-600 hover:underline"
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
              {(events?.length ?? 0) === 0 ? (
                <EmptyState
                  icon={<Timer className="size-10" />}
                  title="Chưa có sự kiện"
                  description="Khi máy bật/tắt (hoặc chuyển trạng thái), sự kiện sẽ xuất hiện tại đây."
                />
              ) : (
                <ul
                  role="log"
                  aria-live="polite"
                  aria-label="Luồng sự kiện realtime"
                  className="max-h-[26rem] divide-y divide-slate-100 overflow-y-auto"
                >
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
                  Có {stats?.pending_tokens} token đã phát nhưng máy chưa cài agent — đôn đốc người dùng
                  chạy lệnh cài đặt để máy xuất hiện online.
                </span>
                <Link href="/tokens" className="font-medium text-brand-600 hover:underline">
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