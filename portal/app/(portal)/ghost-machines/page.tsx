"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CalendarClock, ChevronRight, Ghost } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem } from "@/lib/types";
import type { PageResponse } from "@/components/ui";
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
import { DeleteButton } from "@/components/delete-button";

const DAY_MS = 86_400_000;

/** Phân nhóm máy mất kết nối theo thời gian offline (>15/>30/>60 ngày) cho kế hoạch kiểm tra.
 *  Server tự động chuyển OFFLINE → LOST sau `LOST_AFTER_DAYS` ngày (mặc định 15). */
export default function GhostMachinesPage() {
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<PageResponse<MachineListItem>>("/machines", {
        status: "lost",
        tag: "bmnn", // chỉ máy BMNN — máy công vụ/cá nhân mất kết nối không nằm trang này
        limit: 50,
      });
      setMachines(data.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách máy mất kết nối");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const buckets = useMemo(() => {
    const now = Date.now();
    const gone = (days: number) => (machines ?? []).filter((m) => {
      const last = m.last_seen_at ? new Date(m.last_seen_at).getTime() : now;
      return now - last >= days * DAY_MS;
    });
    return {
      over15: gone(15),
      over30: gone(30),
      over60: gone(60),
    };
  }, [machines]);

  return (
    <div>
      <PageHeader
        title="Máy mất kết nối"
        description="Máy BMNN đã enroll nhưng mất kết nối > 15 ngày — tự động chuyển 'lost' bởi monitor. Dùng để kiểm kê, phát hiện máy bỏ không / mất tích."
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        {[
          { label: "≥ 15 ngày", n: buckets.over15.length, cls: "text-amber-600 bg-amber-50 ring-amber-600/20" },
          { label: "≥ 30 ngày", n: buckets.over30.length, cls: "text-orange-600 bg-orange-50 ring-orange-600/20" },
          { label: "≥ 60 ngày (kiểm tra ngay)", n: buckets.over60.length, cls: "text-rose-600 bg-rose-50 ring-rose-600/20" },
        ].map((b) => (
          <div key={b.label} className="flex h-24 flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
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

      {loading && (machines?.length ?? 0) === 0 ? (
        <Spinner label="Đang tải danh sách máy mất kết nối…" />
      ) : (machines?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<Ghost className="size-10" />}
          title="Không có máy mất kết nối nào"
          description="Ngưỡng 'lost' do server xác định (mất liên lạc > N ngày)."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Hostname</th>
                <th scope="col" className={TH}>UUID</th>
                <th scope="col" className={TH}>Trạng thái</th>
                <th scope="col" className={TH}>Lần cuối online</th>
                <th scope="col" className={TH}>Enroll</th>
                <th scope="col" className={TH}>Mất liên lạc</th>
                <th scope="col" className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {(machines ?? []).map((m) => {
                const last = m.last_seen_at ? new Date(m.last_seen_at).getTime() : Date.now();
                const goneDays = Math.floor((Date.now() - last) / DAY_MS);
                return (
                  <tr key={m.id} className={TR_HOVER}>
                    <td className={`${TD} font-medium text-slate-800`}>{m.hostname ?? "(chưa đặt tên)"}</td>
                    <td className={`${TD} font-mono text-xs text-slate-500`}>{m.machine_uuid.slice(0, 12)}…</td>
                    <td className={TD}>
                      <Badge className={MACHINE_STATUS_META.lost.badge}>
                        <StatusDot className={MACHINE_STATUS_META.lost.dot} />
                        Mất kết nối
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
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/machines/${m.id}`}
                          className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-600 hover:underline"
                        >
                          Kiểm tra <ChevronRight className="size-3.5" />
                        </Link>
                        <DeleteButton
                          resource="máy"
                          itemName={m.hostname ?? m.machine_uuid}
                          deletePath={`/machines/${m.id}`}
                          onDeleted={() => void load()}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="flex items-center gap-1.5 border-t border-slate-100 px-4 py-2.5 text-xs text-slate-400">
            <Ghost className="size-3.5" />
            Thời gian 'mất kết nối' ước tính từ <code>last_seen_at</code>; ngưỡng chính xác do
            server cấu hình <code>LOST_AFTER_DAYS</code> (mặc định 15 ngày).
          </p>
        </div>
      )}
    </div>
  );
}