"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, ClipboardList, ShieldQuestion, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { EnrollAttempt, EnrollAttemptApproveResult } from "@/lib/types";
import { formatDateTime } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorBanner,
  Modal,
  PageHeader,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";

const TOKEN_STATUS_META: Record<string, { label: string; badge: string }> = {
  used: { label: "Token đã dùng", badge: "bg-amber-100 text-amber-700" },
  expired: { label: "Token hết hạn", badge: "bg-orange-100 text-orange-700" },
  revoked: { label: "Token đã thu hồi", badge: "bg-rose-100 text-rose-700" },
  unknown: { label: "Token lạ", badge: "bg-slate-200 text-slate-700" },
};

/** Máy "xin vào" bị từ chối ở cổng token (token cũ/hết hạn/lạ) — duyệt hoặc chặn. */
export default function EnrollRequestsPage() {
  const [attempts, setAttempts] = useState<EnrollAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [approved, setApproved] = useState<EnrollAttemptApproveResult | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<EnrollAttempt[]>("/enroll/attempts", { status: "pending", limit: 100 });
      setAttempts(Array.isArray(data) ? data : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách yêu cầu enroll");
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
      if (approve) {
        const res = await api.post<EnrollAttemptApproveResult>(`/enroll/attempts/${id}/approve`, {});
        setApproved(res);
      } else {
        await api.post(`/enroll/attempts/${id}/reject`, {});
      }
      await load();
    } catch (e) {
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
        title="Yêu cầu enroll bị từ chối"
        description={
          <>
            Máy chạy lệnh cài với <b>token đã dùng / hết hạn / lạ</b> — trước đây bị 401 im lặng,
            giờ hiện tại đây để duyệt.
            <br />
            <span className="text-xs text-slate-500">
              <b>Approve</b> = sinh token thay thế + lệnh cài mới gửi lại cho máy.
              <b> Reject</b> = chặn yêu cầu. Máy enroll <i>thành công</i> chờ duyệt nằm ở{" "}
              <Link href="/approvals" className="underline">Máy chờ duyệt</Link>.
            </span>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && attempts.length === 0 ? (
        <Spinner label="Đang tải…" />
      ) : attempts.length === 0 ? (
        <EmptyState
          icon={<ShieldQuestion className="size-10" />}
          title="Không có yêu cầu enroll bị từ chối"
          description="Khi 1 máy cố enroll bằng token cũ/lạ, yêu cầu sẽ xuất hiện tại đây."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th className={TH}>Máy / hostname</th>
                <th className={TH}>IP</th>
                <th className={TH}>Lý do bị từ chối</th>
                <th className={TH}>Tổ chức</th>
                <th className={TH}>Có thể là máy</th>
                <th className={TH}>Thời gian</th>
                <th className={TH}>Quyết định</th>
              </tr>
            </thead>
            <tbody>
              {attempts.map((a) => {
                const meta = TOKEN_STATUS_META[a.token_status] ?? TOKEN_STATUS_META.unknown;
                return (
                  <tr key={a.id} className={TR_HOVER}>
                    <td className={TD}>
                      <span className="font-medium">{a.hostname || "(không rõ tên)"}</span>
                      {a.token_prefix && (
                        <div className="text-xs text-slate-400">token {a.token_prefix}</div>
                      )}
                    </td>
                    <td className={TD}>{a.ip || "—"}</td>
                    <td className={TD}>
                      <Badge className={meta.badge}>{meta.label}</Badge>
                    </td>
                    <td className={TD}>{a.org_name || <span className="text-slate-400">Token lạ</span>}</td>
                    <td className={TD}>
                      {a.matched_machine_id ? (
                        <Link href={`/machines/${a.matched_machine_id}`} className="underline">
                          {a.matched_machine_hostname || a.matched_machine_id.slice(0, 8)}
                        </Link>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className={TD}>{formatDateTime(a.created_at)}</td>
                    <td className={TD}>
                      <div className="flex gap-2">
                        <Button
                          variant="primary"
                          disabled={busyId === a.id}
                          onClick={() => void decide(a.id, true)}
                        >
                          <CheckCircle2 className="size-4" /> Approve
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={busyId === a.id}
                          onClick={() => void decide(a.id, false)}
                        >
                          <XCircle className="size-4" /> Reject
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={approved !== null}
        onClose={() => setApproved(null)}
        title={
          <span className="flex items-center gap-2">
            <ClipboardList className="size-5 text-emerald-600" /> Đã sinh token thay thế
          </span>
        }
        width="md"
        footer={
          <Button variant="primary" onClick={() => setApproved(null)}>
            Đóng
          </Button>
        }
      >
        {approved && (
          <div className="space-y-3 text-sm">
            <p>
              Gửi lại <b>1 trong các lệnh</b> dưới đây cho máy vừa Approve (token có hạn đến{" "}
              {formatDateTime(approved.expires_at)}):
            </p>
            <div>
              <div className="mb-1 font-medium">Windows (PowerShell hoặc cmd):</div>
              <div className="flex items-start gap-2">
                <code className="flex-1 break-all rounded bg-slate-100 p-2 text-xs">{approved.install_command_windows}</code>
                <CopyButton text={approved.install_command_windows} />
              </div>
            </div>
            <div>
              <div className="mb-1 font-medium">Linux:</div>
              <div className="flex items-start gap-2">
                <code className="flex-1 break-all rounded bg-slate-100 p-2 text-xs">{approved.install_command_linux}</code>
                <CopyButton text={approved.install_command_linux} />
              </div>
            </div>
            {approved.install_url_warnings.length > 0 && (
              <div className="rounded bg-amber-50 p-2 text-xs text-amber-700">
                {approved.install_url_warnings.join(" ")}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
