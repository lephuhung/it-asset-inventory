"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Power } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineTimeline } from "@/lib/types";
import { Badge, Card, ErrorBanner, Spinner, TABLE, TABLE_WRAP, TD, TH, THEAD, TR_HOVER } from "@/components/ui";
import { formatDateTime } from "@/lib/format";

function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h} giờ ${m} phút`;
  return `${m} phút`;
}

/** Timeline bật/tắt máy (tính năng #1) — daily bars + phiên gần nhất. */
export function MachineTimelineSection({ machineId, days = 30 }: { machineId: string; days?: number }) {
  const [data, setData] = useState<MachineTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const t = await api.get<MachineTimeline>(`/machines/${machineId}/timeline`, { days });
      setData(t);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được timeline");
    } finally {
      setLoading(false);
    }
  }, [machineId, days]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !data) return <Spinner label="Đang tính timeline…" />;
  if (error) return <ErrorBanner message={error} onRetry={() => void load()} />;
  if (!data) return null;

  const maxSec = Math.max(1, ...data.daily.map((d) => d.online_sec));
  const hoursOnline = Math.round(data.total_online_sec / 3600);

  return (
    <Card
      title="Lịch sử bật/tắt máy"
      subtitle={`${data.days} ngày gần nhất — tổng ${hoursOnline} giờ online, ${data.sessions_count} phiên bật máy`}
      actions={
        <Badge className="bg-sky-50 text-sky-700 ring-sky-600/20">
          <Power className="size-3" /> Timeline
        </Badge>
      }
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Thời gian online theo ngày
          </p>
          {data.daily.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có heartbeat trong khoảng thời gian này.</p>
          ) : (
            <ul className="space-y-1.5">
              {data.daily.slice(0, 14).map((d) => (
                <li key={d.date} className="flex items-center gap-2 text-xs">
                  <span className="w-20 shrink-0 text-slate-500">{d.date}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100">
                    <div
                      className="h-full rounded bg-blue-500"
                      style={{ width: `${Math.max(2, (d.online_sec / maxSec) * 100)}%` }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right tabular-nums text-slate-600">
                    {fmtDuration(d.online_sec)}
                  </span>
                  <span className="w-8 shrink-0 text-right tabular-nums text-slate-400">
                    {d.boots}×
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Phiên bật máy gần nhất ({Math.min(data.sessions.length, 20)})
          </p>
          {data.sessions.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có phiên bật máy.</p>
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr>
                    <th className={TH}>Bắt đầu</th>
                    <th className={TH}>Kết thúc</th>
                    <th className={TH}>Thời lượng</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.sessions].reverse().slice(0, 20).map((s, i) => (
                    <tr key={i} className={TR_HOVER}>
                      <td className={`${TD} text-xs`}>{formatDateTime(s.start)}</td>
                      <td className={`${TD} text-xs`}>{formatDateTime(s.end)}</td>
                      <td className={`${TD} text-xs font-medium`}>{fmtDuration(s.duration_sec)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      <p className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-400">
        <CalendarClock className="size-3.5" />
        Phiên = chuỗi heartbeat liên tiếp (ngắt quãng &gt; 5 phút tính là tắt). Dữ liệu từ bảng
        heartbeats partition theo ngày.
      </p>
    </Card>
  );
}