"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, ChevronRight, ClipboardCheck, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem } from "@/lib/types";
import type { PageResponse } from "@/components/ui";
import {
  Badge,
  Button,
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
import { MACHINE_STATUS_META, formatDateTime } from "@/lib/format";

/** Pending approval cho máy mới enroll (#20, Phase 3). */
export default function ApprovalsPage() {
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<PageResponse<MachineListItem>>("/machines", { status: "pending", limit: 50 });
      setMachines(data.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách chờ duyệt");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (id: string, approve: boolean) => {
    setBusyId(id);
    try {
      await api.post(`/machines/${id}/${approve ? "approve" : "reject"}`, {});
      // Thành công: refresh list — máy đã duyệt sẽ biến mất khỏi /approvals.
      await load();
    } catch (e) {
      // Approve thất bại có thể vì:
      //  - Máy đã được duyệt bởi admin khác (status=online → 400)
      //  - Agent vừa re-enroll với fingerprint match → tự động online
      //  - Token đã bị revoke, máy bị decommission
      // Trong mọi trường hợp, refresh list để ẩn máy không còn pending.
      const msg = e instanceof Error ? e.message : "Thao tác thất bại";
      setError(`${msg} (đã tải lại danh sách)`);
      await load();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Máy chờ duyệt"
        description={
          <>
            Máy mới enroll có trạng thái <b>'Chờ duyệt'</b> — duyệt để tính chính thức (kèm audit log).
            <br />
            <span className="text-xs text-slate-500">
              Đây là máy đã agent enroll thành công (qua API enroll hoặc offline enroll), <b>không phải</b> token đã phát cho người dùng.
              Xem token đã phát ở Dashboard → <i>Token đã phát, chờ máy cài</i>.
            </span>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && (machines?.length ?? 0) === 0 ? (
        <Spinner label="Đang tải…" />
      ) : (machines?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<ClipboardCheck className="size-10" />}
          title="Không có máy nào chờ duyệt"
          description="Khi agent enroll máy mới, máy xuất hiện tại đây để admin duyệt."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Hostname</th>
                <th scope="col" className={TH}>UUID</th>
                <th scope="col" className={TH}>Trạng thái</th>
                <th scope="col" className={TH}>Enroll</th>
                <th scope="col" className={TH}>Lần cuối online</th>
                <th scope="col" className={`${TH} text-right`}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {(machines ?? []).map((m) => (
                <tr key={m.id} className={TR_HOVER}>
                  <td className={`${TD} font-medium text-slate-800`}>
                    <Link href={`/machines/${m.id}`} className="text-blue-600 hover:underline">
                      {m.hostname ?? "(chưa đặt tên)"}
                    </Link>
                  </td>
                  <td className={`${TD} font-mono text-xs text-slate-500`}>{m.machine_uuid.slice(0, 14)}…</td>
                  <td className={TD}>
                    <Badge className={MACHINE_STATUS_META.pending.badge}>
                      <StatusDot className={MACHINE_STATUS_META.pending.dot} />
                      Chờ duyệt
                    </Badge>
                  </td>
                  <td className={`${TD} text-xs`}>{formatDateTime(m.enrolled_at)}</td>
                  <td className={`${TD} text-xs`}>{formatDateTime(m.last_seen_at)}</td>
                  <td className={`${TD} text-right`}>
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        size="sm"
                        loading={busyId === m.id}
                        onClick={() => void decide(m.id, true)}
                      >
                        <CheckCircle2 className="size-3.5" /> Duyệt
                      </Button>
                      <Button variant="danger" size="sm" disabled={busyId === m.id} onClick={() => void decide(m.id, false)}>
                        <XCircle className="size-3.5" /> Từ chối
                      </Button>
                      <Link
                        href={`/machines/${m.id}`}
                        className="inline-flex items-center gap-0.5 rounded-lg px-2 py-1.5 text-xs font-medium text-blue-600 hover:underline"
                      >
                        Chi tiết <ChevronRight className="size-3.5" />
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}