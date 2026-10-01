"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, ChevronRight, ClipboardCheck, ClipboardList, ShieldAlert, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { EnrollAttempt, EnrollAttemptApproveResult, MachineListItem } from "@/lib/types";
import type { PageResponse } from "@/components/ui";
import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ErrorBanner,
  Modal,
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

type Tab = "machines" | "attempts";

const TOKEN_STATUS_META: Record<string, { label: string; badge: string }> = {
  used: { label: "Token đã dùng", badge: "bg-amber-100 text-amber-700" },
  expired: { label: "Token hết hạn", badge: "bg-orange-100 text-orange-700" },
  revoked: { label: "Token đã thu hồi", badge: "bg-rose-100 text-rose-700" },
  unknown: { label: "Token lạ", badge: "bg-slate-200 text-slate-700" },
};

/** Hàng đợi duyệt (#20, Phase 3):
 *  - Tab "Máy chờ duyệt": máy đã enroll THÀNH CÔNG với token hợp lệ (status=pending).
 *  - Tab "Yêu cầu bị từ chối": máy chạy lệnh cài với token đã dùng/hết hạn/lạ —
 *    server ghi enroll_attempts, admin Approve (sinh token thay thế) hoặc Reject. */
export default function ApprovalsPage() {
  const [tab, setTab] = useState<Tab>("machines");
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [attempts, setAttempts] = useState<EnrollAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [approved, setApproved] = useState<EnrollAttemptApproveResult | null>(null);

  const load = useCallback(async () => {
    try {
      const [machinesRes, attemptsRes] = await Promise.all([
        api.get<PageResponse<MachineListItem>>("/machines", { status: "pending", limit: 50 }),
        api.get<EnrollAttempt[]>("/enroll/attempts", { status: "pending", limit: 100 }),
      ]);
      setMachines(machinesRes.items);
      setAttempts(Array.isArray(attemptsRes) ? attemptsRes : []);
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

  const decideMachine = async (id: string, approve: boolean) => {
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

  const decideAttempt = async (id: string, approve: boolean) => {
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

  const tabs: Array<{ key: Tab; label: string; count: number; icon: React.ReactNode }> = [
    { key: "machines", label: "Máy chờ duyệt", count: machines.length, icon: <ClipboardCheck className="size-4" /> },
    { key: "attempts", label: "Yêu cầu bị từ chối", count: attempts.length, icon: <ShieldAlert className="size-4" /> },
  ];

  return (
    <div>
      <PageHeader
        title="Chờ duyệt"
        description={
          <>
            <b>Máy chờ duyệt</b>: máy agent enroll thành công (qua API enroll hoặc offline enroll) — duyệt để tính chính thức (kèm audit log).
            <br />
            <span className="text-xs text-slate-500">
              <b>Yêu cầu bị từ chối</b>: máy chạy lệnh cài với token đã dùng/hết hạn/lạ — server ghi lại để duyệt hoặc chặn.
              Token đã phát cho người dùng xem ở Dashboard → <i>Token đã phát, chờ máy cài</i>.
            </span>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* Tab strip — underline tabs theo Design.md: chrome im lặng (hairline),
          tab active đánh dấu bằng ĐÚNG MỘT vạch primary (màu cấu trúc duy nhất),
          label active = ink đậm, tab khác = stone. */}
      <div className="mb-6 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Hàng đợi duyệt">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
              tab === t.key
                ? "border-brand-600 text-slate-900"
                : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
            }`}
          >
            {t.icon}
            {t.label}
            {t.count > 0 && (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-semibold tabular-nums text-slate-600">
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading && machines.length === 0 && attempts.length === 0 ? (
        <Spinner label="Đang tải…" />
      ) : tab === "machines" ? (
        machines.length === 0 ? (
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
                {machines.map((m) => (
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
                          onClick={() => void decideMachine(m.id, true)}
                        >
                          <CheckCircle2 className="size-3.5" /> Duyệt
                        </Button>
                        <Button variant="danger" size="sm" disabled={busyId === m.id} onClick={() => void decideMachine(m.id, false)}>
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
        )
      ) : attempts.length === 0 ? (
        <EmptyState
          icon={<ShieldAlert className="size-10" />}
          title="Không có yêu cầu enroll bị từ chối"
          description="Khi 1 máy cố enroll bằng token cũ/lạ, yêu cầu sẽ xuất hiện tại đây."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Máy / hostname</th>
                <th scope="col" className={TH}>IP</th>
                <th scope="col" className={TH}>Lý do bị từ chối</th>
                <th scope="col" className={TH}>Tổ chức</th>
                <th scope="col" className={TH}>Có thể là máy</th>
                <th scope="col" className={TH}>Thời gian</th>
                <th scope="col" className={`${TH} text-right`}>Quyết định</th>
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
                    <td className={`${TD} text-xs`}>{formatDateTime(a.created_at)}</td>
                    <td className={`${TD} text-right`}>
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          size="sm"
                          loading={busyId === a.id}
                          onClick={() => void decideAttempt(a.id, true)}
                        >
                          <CheckCircle2 className="size-3.5" /> Duyệt
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={busyId === a.id}
                          onClick={() => void decideAttempt(a.id, false)}
                        >
                          <XCircle className="size-3.5" /> Chặn
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
              Gửi lại <b>1 trong các lệnh</b> dưới đây cho máy vừa duyệt (token có hạn đến{" "}
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
