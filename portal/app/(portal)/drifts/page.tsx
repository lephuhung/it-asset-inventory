"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Check, Fingerprint, X } from "lucide-react";
import { api } from "@/lib/api";
import type { FingerprintDrift } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Pagination,
  PageResponse,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { formatDateTime, timeAgo } from "@/lib/format";

const REASON_META: Record<string, { label: string; badge: string }> = {
  mainboard_changed: { label: "Đổi mainboard", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
  os_reinstall: { label: "Cài lại Win / ghost", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  other: { label: "Khác", badge: "bg-slate-100 text-slate-600 ring-slate-500/20" },
};

const STATUS_META: Record<string, { label: string; badge: string }> = {
  pending: { label: "Chờ duyệt", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  approved: { label: "Đã chấp nhận", badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  rejected: { label: "Đã từ chối", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
};

/** Fingerprint drift (#4, Phase 3) — duyệt khi đổi mainboard / ghost Win. */
export default function DriftsPage() {
  const [drifts, setDrifts] = useState<FingerprintDrift[]>([]);
  const [page, setPage] = useState<PageResponse<FingerprintDrift>>({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [offset, setOffset] = useState(0);

  const load = useCallback(async (overrideOffset?: number) => {
    const useOffset = overrideOffset ?? offset;
    try {
      const data = await api.get<PageResponse<FingerprintDrift>>("/drifts", {
        limit: 50,
        offset: useOffset,
      });
      setDrifts(data.items);
      setPage(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách drift");
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (id: string, approve: boolean) => {
    setBusyId(id);
    try {
      await api.post(`/drifts/${id}/${approve ? "approve" : "reject"}`, {});
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Thao tác thất bại");
    } finally {
      setBusyId(null);
    }
  };

  const visible = showAll ? drifts : drifts.filter((d) => d.status === "pending");

  return (
    <div>
      <PageHeader
        title="Fingerprint drift"
        description="Máy đổi mainboard / cài lại Windows → fingerprint mới lệch máy cũ; admin duyệt để chống gian lận định danh (#4)"
        actions={
          <Button variant="secondary" size="sm" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Chỉ xem chờ duyệt" : "Xem tất cả"}
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && (drifts?.length ?? 0) === 0 ? (
        <Spinner label="Đang tải…" />
      ) : (visible?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<Fingerprint className="size-10" />}
          title="Không có drift nào"
          description="Khi agent enroll với fingerprint lệch máy đã biết, cảnh báo sẽ xuất hiện tại đây."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Máy</th>
                <th scope="col" className={TH}>Lý do</th>
                <th scope="col" className={TH}>Fingerprint cũ → mới</th>
                <th scope="col" className={TH}>Phát hiện</th>
                <th scope="col" className={TH}>Trạng thái</th>
                <th scope="col" className={`${TH} text-right`}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((d) => {
                const reason = REASON_META[d.reason] ?? REASON_META.other;
                const st = STATUS_META[d.status] ?? STATUS_META.pending;
                return (
                  <tr key={d.id} className={TR_HOVER}>
                    <td className={`${TD} font-medium text-slate-800`}>
                      <Link href={`/machines/${d.machine_id}`} className="text-blue-600 hover:underline">
                        {d.hostname ?? d.machine_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className={TD}>
                      <Badge className={reason.badge}>{reason.label}</Badge>
                    </td>
                    <td className={`${TD} max-w-md`}>
                      <div className="flex items-start gap-1 font-mono text-[11px] leading-relaxed text-slate-600">
                        <span className="min-w-0 flex-1 truncate" title={JSON.stringify(d.old_fingerprint)}>
                          {JSON.stringify(d.old_fingerprint)}
                        </span>
                        <span className="shrink-0 px-1 text-slate-300">→</span>
                        <span className="min-w-0 flex-1 truncate text-blue-700" title={JSON.stringify(d.new_fingerprint)}>
                          {JSON.stringify(d.new_fingerprint)}
                        </span>
                      </div>
                    </td>
                    <td className={`${TD} text-xs`} title={formatDateTime(d.created_at)}>
                      {timeAgo(d.created_at)}
                    </td>
                    <td className={TD}>
                      <Badge className={st.badge}>{st.label}</Badge>
                    </td>
                    <td className={`${TD} text-right`}>
                      {d.status === "pending" ? (
                        <div className="flex items-center justify-end gap-1.5">
                          <Button size="sm" loading={busyId === d.id} onClick={() => void decide(d.id, true)}>
                            <Check className="size-3.5" /> Chấp nhận
                          </Button>
                          <Button variant="danger" size="sm" disabled={busyId === d.id} onClick={() => void decide(d.id, false)}>
                            <X className="size-3.5" /> Từ chối
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">Đã xử lý</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination
            page={page}
            onChange={(newOffset) => {
              setOffset(newOffset);
              void load(newOffset);
            }}
          />
          <p className="border-t border-slate-100 bg-slate-50/50 px-4 py-2.5 text-xs text-slate-400">
            Chấp nhận = cập nhật fingerprint + machine_uuid của máy (máy đổi thật sự). Từ chối = giữ
            fingerprint cũ (nghi gian lận định danh). Mọi quyết định ghi audit log.
          </p>
        </div>
      )}
    </div>
  );
}