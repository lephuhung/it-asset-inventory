"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, RefreshCw, ScrollText, ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Pagination,
  Select,
  Spinner,
  StatusDot,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { formatDateTime, shortUuid } from "@/lib/format";

interface AuditPageResponse {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}

interface VerifyResponse {
  ok: boolean;
  broken_index: number | null;
  checked: number;
  anchor_hash: string;
}

const PAGE_SIZE = 100;

/** Trang audit log read-only (Sprint 4, mục 7.2) — append-only + hash chain. */
export default function AuditPage() {
  const [data, setData] = useState<AuditPageResponse | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Bộ lọc
  const [action, setAction] = useState("");
  const [q, setQ] = useState("");
  const [actor, setActor] = useState("");
  const [offset, setOffset] = useState(0);

  // Verify hash chain
  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [verifyBusy, setVerifyBusy] = useState(false);

  const load = useCallback(
    async (silent = false, overrideOffset?: number) => {
      const useOffset = overrideOffset ?? offset;
      try {
        const res = await api.get<AuditPageResponse>("/audit", {
          limit: PAGE_SIZE,
          offset: useOffset,
          action: action || undefined,
          actor: actor || undefined,
          q: q || undefined,
        });
        setData(res);
        setError(null);
      } catch (e) {
        if (!silent) setError(e instanceof Error ? e.message : "Không tải được audit log");
      } finally {
        setLoading(false);
      }
    },
    [action, actor, q, offset],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .get<string[]>("/audit/actions")
      .then((list) => setActions(Array.isArray(list) ? list : []))
      .catch(() => setActions([]));
  }, []);

  useEffect(() => {
    setOffset(0);
  }, [action, q, actor]);

  const runVerify = async () => {
    setVerifyBusy(true);
    try {
      setVerify(await api.get<VerifyResponse>("/audit/verify"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kiểm tra hash chain thất bại");
    } finally {
      setVerifyBusy(false);
    }
  };

  const total = data?.total ?? 0;
  const pageStart = offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="Nhật ký chỉ ghi (append-only) có hash chain — mọi thao tác nhạy cảm: login, token, enroll, export, drift, xác nhận tuân thủ"
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* Kiểm tra hash chain */}
      <Card className="mb-4" padded={false}>
        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
          <ShieldCheck className="size-5 text-blue-600" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-800">Kiểm tra toàn vẹn hash chain</p>
            <p className="text-xs text-slate-400">
              {verify
                ? `Đã kiểm tra ${verify.checked} dòng — anchor: ${verify.anchor_hash.slice(0, 16)}…`
                : "Xác minh không dòng nào bị sửa/xóa giữa chuỗi (phát hiện ngay mọi can thiệp)."}
            </p>
          </div>
          {verify && (
            verify.ok ? (
              <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                <StatusDot className="bg-emerald-500" /> Chuỗi hợp lệ
              </Badge>
            ) : (
              <Badge className="bg-rose-50 text-rose-700 ring-rose-600/20">
                <StatusDot className="bg-rose-500" /> ĐỨT CHUỖI tại dòng #{verify.broken_index}
              </Badge>
            )
          )}
          <Button variant="secondary" size="sm" onClick={() => void runVerify()} loading={verifyBusy}>
            <ShieldAlert className="size-3.5" /> Kiểm tra
          </Button>
        </div>
      </Card>

      {/* Bộ lọc */}
      <Card className="mb-4" padded={false}>
        <div className="grid gap-3 p-4 sm:grid-cols-3">
          <Field label="Hành động (action)">
            <Select value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="">Tất cả</option>
              {actions.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Người thực hiện (actor)">
            <Input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="VD: agent:…, user id…" />
          </Field>
          <Field label="Tìm kiếm (action/target)">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="VD: token.create, enroll…" />
          </Field>
        </div>
      </Card>

      {loading && !data ? (
        <Spinner label="Đang tải audit log…" />
      ) : !data || (data.items?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<ScrollText className="size-10" />}
          title="Không có bản ghi audit khớp bộ lọc"
          description="Khi có hoạt động (đăng nhập, sinh token, enroll máy…), các bản ghi sẽ liệt kê tại đây."
        />
      ) : (
        <Card
          padded={false}
          title={`${total.toLocaleString("vi-VN")} bản ghi`}
          subtitle={`Hiển thị ${pageStart}–${pageEnd}`}
        >
          <div className={TABLE_WRAP}>
            <table className={TABLE}>
              <thead className={THEAD}>
                <tr>
                  <th scope="col" className={TH}>#</th>
                  <th scope="col" className={TH}>Thời gian</th>
                  <th scope="col" className={TH}>Người thực hiện</th>
                  <th scope="col" className={TH}>Hành động</th>
                  <th scope="col" className={TH}>Đối tượng</th>
                  <th scope="col" className={TH}>Máy liên quan</th>
                  <th scope="col" className={TH}>IP</th>
                  <th scope="col" className={TH}>Content hash</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id} className={TR_HOVER}>
                    <td className={`${TD} font-mono text-[11px] text-slate-400`}>{e.id}</td>
                    <td className={`${TD} text-xs whitespace-nowrap`}>{formatDateTime(e.ts)}</td>
                    <td className={`${TD} font-mono text-xs text-slate-600`} title={e.actor ?? ""}>
                      {shortUuid(e.actor, 20)}
                    </td>
                    <td className={`${TD} text-xs font-medium text-slate-800`}>{e.action}</td>
                    <td className={`${TD} font-mono text-xs text-slate-500`}>{shortUuid(e.target, 20)}</td>
                    <td className={`${TD} text-xs`}>
                      {e.machine_id ? (
                        <Link href={`/machines/${e.machine_id}`} className="font-mono text-blue-600 hover:underline">
                          {e.machine_id.slice(0, 8)}…
                        </Link>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className={`${TD} font-mono text-xs text-slate-500`}>{e.ip ?? "—"}</td>
                    <td className={`${TD} font-mono text-[11px] text-slate-400`} title={`prev: ${e.prev_hash}`}>
                      {e.content_hash.slice(0, 12)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Phân trang */}
          <Pagination
            page={{ items: data.items, total, limit: PAGE_SIZE, offset }}
            onChange={(newOffset) => {
              setOffset(newOffset);
              void load(true, newOffset);
            }}
          />

          <p className="flex items-center gap-1.5 border-t border-slate-100 bg-slate-50/50 px-4 py-2.5 text-xs text-slate-400">
            <CheckCircle2 className="size-3.5" />
            Append-only: chỉ INSERT qua service; hash chain nối qua <code>prev_hash</code> — mọi sửa
            đổi/xóa giữa chuỗi đều bị phát hiện bởi mục "Kiểm tra" phía trên.
          </p>
        </Card>
      )}
    </div>
  );
}