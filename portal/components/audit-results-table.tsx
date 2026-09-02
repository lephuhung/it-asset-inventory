"use client";

import { memo } from "react";
import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import {
  Card,
  PageResponse,
  Pagination,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { formatDateTime, shortUuid } from "@/lib/format";
import type { AuditLogEntry } from "@/lib/types";

export interface AuditPageResponse {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditResultsTableProps {
  data: AuditPageResponse;
  pageOffset: number;
  onPageChange: (offset: number) => void;
}

const PAGE_SIZE = 100;

function AuditResultsTableInner({
  data,
  pageOffset,
  onPageChange,
}: AuditResultsTableProps) {
  const total = data?.total ?? 0;
  const pageStart = pageOffset + 1;
  const pageEnd = Math.min(pageOffset + PAGE_SIZE, total);
  const page: PageResponse<AuditLogEntry> = {
    items: data.items,
    total,
    limit: PAGE_SIZE,
    offset: pageOffset,
  };
  return (
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
      <Pagination page={page} onChange={onPageChange} />

      <p className="flex items-center gap-1.5 border-t border-slate-100 bg-slate-50/50 px-4 py-2.5 text-xs text-slate-400">
        <CheckCircle2 className="size-3.5" />
        Append-only: chỉ INSERT qua service; hash chain nối qua <code>prev_hash</code> — mọi sửa
        đổi/xóa giữa chuỗi đều bị phát hiện bởi mục "Kiểm tra" phía trên.
      </p>
    </Card>
  );
}

/**
 * Bảng kết quả audit — tách riêng khỏi page để các lần re-render do gõ phím
 * vào `q`/`actor` không kéo theo re-render bảng khi `data` và callback props
 * ổn định. Page chỉ cần truyền `pageOffset` riêng để giữ tham chiếu ổn định
 * (vì state `offset` trong page có thể thay đổi nhưng `data.offset` chưa kịp
 * đồng bộ trong các request bị abort).
 */
export const AuditResultsTable = memo(AuditResultsTableInner);
