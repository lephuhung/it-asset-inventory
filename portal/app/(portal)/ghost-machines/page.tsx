"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CalendarClock, ChevronRight, Ghost } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem } from "@/lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Spinner,
  StatusDot,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { MACHINE_STATUS_META, formatDateTime, timeAgo } from "@/lib/format";

const DAY_MS = 86_400_000;

/** Phân nhóm máy ma theo thời gian mất liên lạc (>30/>60/>90 ngày) cho kế hoạch kiểm tra. */
export default function GhostMachinesPage() {
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.get<MachineListItem[]>("/machines", { status: "lost" });
      setMachines(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách máy ma");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const buckets = useMemo(() => {
    const now = Date.now();
    const gone = (days: number) => machines.filter((m) => {
      const last = m.last_seen_at ? new Date(m.last_seen_at).getTime() : now;
      return now - last >= days * DAY_MS;
    });
    return {
      over30: gone(30),
      over60: gone(60),
      over90: gone(90),
    };
  }, [machines]);

  return (
    <div>
      <PageHeader
        title="Máy ma"
        description="Máy đã enroll nhưng mất liên lạc > N ngày — dùng để kiểm kê, phát hiện máy bỏ không / mất tích"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        {[
          { label: "> 30 ngày", n: buckets.over30.length, cls: "text-amber-600 bg-amber-50 ring-amber-600/20" },
          { label: "> 60 ngày", n: buckets.over60.length, cls: "text-orange-600 bg-orange-50 ring-orange-600/20" },
          { label: "> 90 ngày (kiểm tra ngay)", n: buckets.over90.length, cls: "text-rose-600 bg-rose-50 ring-rose-600/20" },
        ].map((b) => (
          <div key={b.label} className="flex h-24 flex-col justify-between rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{b.label}</p>
              <span className={`flex size-7 items-center justify-center rounded-lg ring-1 ring-inset ${b.cls}`}>
                <Ghost className="size-4" />
              </span>
            </div>
            <p className="text-2xl font-bold tabular-nums text-slate-900">{b.n}</p>
          </div>
        ))}
      </div>

      {loading && machines.length === 0 ? (
        <Spinner label="Đang tải danh sách máy ma…" />
      ) : machines.length === 0 ? (
        <EmptyState
          icon={<Ghost className="size-10" />}
          title="Không có máy ma nào"
          description="Ngưỡng 'lost' do server xác định (mất liên lạc > N ngày)."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th className={TH}>Hostname</th>
                <th className={TH}>UUID</th>
                <th className={TH}>Trạng thái</th>
                <th className={TH}>Lần cuối online</th>
                <th className={TH}>Enroll</th>
                <th className={TH}>Mất liên lạc</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {machines.map((m) => {
                const last = m.last_seen_at ? new Date(m.last_seen_at).getTime() : Date.now();
                const goneDays = Math.floor((Date.now() - last) / DAY_MS);
                return (
                  <tr key={m.id} className={TR_HOVER}>
                    <td className={`${TD} font-medium text-slate-800`}>{m.hostname ?? "(chưa đặt tên)"}</td>
                    <td className={`${TD} font-mono text-xs text-slate-500`}>{m.machine_uuid.slice(0, 12)}…</td>
                    <td className={TD}>
                      <Badge className={MACHINE_STATUS_META.lost.badge}>
                        <StatusDot className={MACHINE_STATUS_META.lost.dot} />
                        Máy ma
                      </Badge>
                    </td>
                    <td className={`${TD} text-xs`}>{formatDateTime(m.last_seen_at)}</td>
                    <td className={`${TD} text-xs`}>{formatDateTime(m.enrolled_at)}</td>
                    <td className={`${TD} text-sm font-semibold text-rose-600`}>
                      <span className="inline-flex items-center gap-1">
                        <CalendarClock className="size-3.5" />
                        {goneDays} ngày
                      </span>
                    </td>
                    <td className={TD}>
                      <Link
                        href={`/machines/${m.id}`}
                        className="inline-flex items-center gap-0.5 text-xs font-medium text-[#635a5a] hover:underline"
                      >
                        Kiểm tra <ChevronRight className="size-3.5" />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="flex items-center gap-1.5 border-t border-slate-100 px-4 py-2.5 text-xs text-slate-400">
            <Ghost className="size-3.5" />
            Thời gian 'mất liên lạc' ước tính từ <code>last_seen_at</code>; ngưỡng chính xác do
            server cấu hình (30/60/90 ngày).
          </p>
        </div>
      )}
    </div>
  );
}