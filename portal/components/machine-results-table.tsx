"use client";

import { memo } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import {
  Badge,
  PageResponse,
  Pagination,
  StatusDot,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import {
  LIFECYCLE_META,
  MACHINE_STATUS_META,
  classificationTag,
  formatDateTime,
  purposeTags,
  tagBadgeClass,
  timeAgo,
} from "@/lib/format";
import type { MachineListItem, MachineStatus } from "@/lib/types";
import { DeleteButton } from "@/components/delete-button";

export interface MachineResultsTableProps {
  machines: MachineListItem[];
  page: PageResponse<MachineListItem>;
  countByStatus: Record<string, number>;
  onReload: () => void;
  onPageChange: (offset: number) => void;
}

const OSLogo = ({
  platform,
  className = "size-3.5",
}: {
  platform: string | null | undefined;
  className?: string;
}) => {
  const p = (platform ?? "").toLowerCase();

  if (p.includes("win")) {
    // Windows logo (4 ô vuông — Windows 8/10/11 mark)
    return (
      <svg viewBox="0 0 24 24" className={`inline align-middle ${className}`} aria-label="Windows" role="img">
        <title>Windows</title>
        <path fill="#0078D4" d="M0 3.5L10.5 2v9H0zM11.5 1.9L24 0v11h-12.5zM0 12.5h10.5v9L0 20.5zM11.5 12.5H24V24l-12.5-1.9z" />
      </svg>
    );
  }
  if (p.includes("linux") || p.includes("ubuntu") || p.includes("debian") || p.includes("rhel") || p.includes("rocky")) {
    // Tux — con cánh cụt đơn giản (penguin silhouette). Mắt trắng + body đen.
    return (
      <svg viewBox="0 0 24 24" className={`inline align-middle ${className}`} aria-label="Linux" role="img">
        <title>Linux</title>
        {/* đầu */}
        <ellipse cx="12" cy="9" rx="4" ry="5" fill="#000" />
        {/* bụng trắng + cằm trắng */}
        <ellipse cx="12" cy="10.5" rx="2.4" ry="3" fill="#fff" />
        {/* mắt */}
        <circle cx="10.6" cy="7.6" r="0.85" fill="#fff" />
        <circle cx="13.4" cy="7.6" r="0.85" fill="#fff" />
        <circle cx="10.6" cy="7.7" r="0.35" fill="#000" />
        <circle cx="13.4" cy="7.7" r="0.35" fill="#000" />
        {/* mỏ cam */}
        <path fill="#F4A100" d="M11 9.6l1 0.6 1-0.6 -1 1.2z" />
        {/* thân + chân */}
        <path fill="#000" d="M8 13c0 4 1.8 6 4 6s4-2 4-6c0 0-1 1.2-4 1.2S8 13 8 13z" />
        {/* chân (chỉ 2 ngón) */}
        <ellipse cx="10" cy="20" rx="1.6" ry="0.9" fill="#F4A100" />
        <ellipse cx="14" cy="20" rx="1.6" ry="0.9" fill="#F4A100" />
      </svg>
    );
  }
  if (p.includes("mac") || p.includes("darwin") || p.includes("osx")) {
    // Apple logo (đơn giản)
    return (
      <svg viewBox="0 0 24 24" className={`inline align-middle ${className}`} aria-label="macOS" role="img">
        <title>macOS</title>
        <path fill="#000" d="M17.05 12.04c-.02-2.16 1.76-3.2 1.84-3.25-1-1.46-2.57-1.66-3.13-1.69-1.32-.13-2.59.78-3.27.78-.68 0-1.72-.76-2.83-.74-1.45.02-2.79.85-3.54 2.15-1.51 2.62-.39 6.5 1.08 8.62.72 1.05 1.57 2.21 2.69 2.17 1.08-.04 1.49-.7 2.79-.7 1.31 0 1.67.7 2.81.68 1.16-.02 1.9-1.06 2.61-2.11.83-1.2 1.17-2.37 1.19-2.43-.03-.01-2.27-.87-2.29-3.46zM14.95 5.84c.6-.72 1-1.73.89-2.74-.86.04-1.91.57-2.53 1.29-.55.64-1.04 1.67-.91 2.66.96.08 1.95-.49 2.55-1.21z" />
      </svg>
    );
  }
  // Unknown — hiển thị dấu hỏi giúp admin biết máy chưa gửi v4 envelope.
  return (
    <svg viewBox="0 0 24 24" className={`inline align-middle ${className}`} aria-label="Unknown OS" role="img">
      <title>Unknown OS (chưa gửi platform)</title>
      <circle cx="12" cy="12" r="11" fill="#94a3b8" />
      <text x="12" y="17" textAnchor="middle" fontFamily="sans-serif" fontSize="14" fontWeight="bold" fill="#fff">?</text>
    </svg>
  );
};

function MachineResultsTableInner({
  machines,
  page,
  countByStatus,
  onReload,
  onPageChange,
}: MachineResultsTableProps) {
  return (
    <div className={TABLE_WRAP}>
      <table className={TABLE}>
        <thead className={THEAD}>
          <tr>
            <th scope="col" className={TH}>Hostname</th>
            <th scope="col" className={TH}>Trạng thái</th>
            <th scope="col" className={TH}>Vòng đời</th>
            <th scope="col" className={TH}>Phân loại</th>
            <th scope="col" className={TH}>Lần cuối online</th>
            <th scope="col" className={TH}>Enroll</th>
            <th scope="col" className={TH}></th>
          </tr>
        </thead>
        <tbody>
          {(machines ?? []).map((m) => {
            const meta = MACHINE_STATUS_META[m.status];
            const life = LIFECYCLE_META[m.lifecycle] ?? { label: m.lifecycle, badge: "bg-slate-100 text-slate-500 ring-slate-500/20" };
            return (
              <tr key={m.id} className={TR_HOVER}>
                <td className={`${TD} font-medium text-slate-800`}>
                  <div className="flex items-center gap-1.5">
                    <OSLogo platform={m.platform} />
                    <span>{m.hostname ?? "(chưa đặt tên)"}</span>
                    {m.velociraptor_client_id && (
                      <span
                        className="ml-1 inline-flex items-center gap-0.5 rounded border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-700"
                        title={`DFIR: Velociraptor đã enroll\nclient_id: ${m.velociraptor_client_id}\nLast seen: ${m.velociraptor_last_seen_at || "unknown"}`}
                      >
                        <svg viewBox="0 0 24 24" className="inline size-3" aria-hidden="true">
                          <path fill="currentColor" d="M12 2L4 6v6c0 5 3.5 9.5 8 10.5 4.5-1 8-5.5 8-10.5V6l-8-4zm0 2.2l6 3v4.8c0 4-2.7 7.7-6 8.7-3.3-1-6-4.7-6-8.7V7.2l6-3z" />
                        </svg>
                        DFIR
                      </span>
                    )}
                  </div>
                </td>
                <td className={TD}>
                  <Badge className={meta.badge}>
                    <StatusDot className={meta.dot} />
                    {meta.label}
                  </Badge>
                  {m.status !== "online" && m.last_seen_at && (
                    <p className="mt-1 text-[11px] text-slate-400">Cuối: {timeAgo(m.last_seen_at)}</p>
                  )}
                </td>
                <td className={TD}>
                  <Badge className={life.badge}>{life.label}</Badge>
                </td>
                <td className={TD}>
                  {/* Tag nổi bật theo type (classification) + kind (purpose) của máy */}
                  <div className="flex flex-wrap items-center gap-1">
                    {(() => {
                      const cls = classificationTag(m.tags);
                      return cls ? (
                        <Badge className={tagBadgeClass(cls)}>{cls.label}</Badge>
                      ) : (
                        <Badge className="bg-slate-100 text-slate-500 ring-slate-500/20">Chưa phân loại</Badge>
                      );
                    })()}
                    {purposeTags(m.tags).map((t) => (
                      <Badge key={t.key} className={tagBadgeClass(t)}>{t.label}</Badge>
                    ))}
                    <Badge
                      className={
                        m.is_vm
                          ? "bg-sky-50 text-sky-700 ring-sky-600/20"
                          : "bg-slate-100 text-slate-700 ring-slate-600/20"
                      }
                    >
                      {m.is_vm ? "Máy ảo" : "Vật lý"}
                    </Badge>
                  </div>
                </td>
                <td className={`${TD} text-xs`}>{formatDateTime(m.last_seen_at)}</td>
                <td className={`${TD} text-xs`}>{formatDateTime(m.enrolled_at)}</td>
                <td className={TD}>
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/machines/${m.id}`}
                      className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-600 hover:underline"
                    >
                      Chi tiết <ChevronRight className="size-3.5" />
                    </Link>
                    <DeleteButton
                      resource="máy"
                      itemName={m.hostname ?? m.machine_uuid}
                      deletePath={`/machines/${m.id}`}
                      onDeleted={onReload}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <Pagination page={page} onChange={onPageChange} />
      {Object.keys(countByStatus).length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
          {Object.entries(countByStatus).map(([s, n]) => (
            <span key={s} className="inline-flex items-center gap-1">
              <StatusDot className={MACHINE_STATUS_META[s as MachineStatus]?.dot ?? "bg-slate-400"} />
              {MACHINE_STATUS_META[s as MachineStatus]?.label ?? s}: <b>{n}</b>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Bảng kết quả máy — tách riêng khỏi page để các lần re-render do gõ phím
 * vào ô tìm kiếm (`q`) không kéo theo re-render bảng khi `machines`/`page`/
 * callback props ổn định. Page chỉ cần truyền `countByStatus` đã memoized
 * theo `machines` để giữ tham chiếu ổn định qua các keystroke.
 */
export const MachineResultsTable = memo(MachineResultsTableInner);
