"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CalendarClock, ChevronRight } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineDetail, MachineListItem } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  PageResponse,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { formatDate } from "@/lib/format";
import { EOL_STATUS_META, getWindowsEol, type EolInfo } from "@/lib/eol";

/** Nạp chi tiết máy giới hạn song song (backend chưa có endpoint EOL chuyên dụng). */
async function fetchDetailsSequential(list: MachineListItem[], limit = 400): Promise<MachineDetail[]> {
  const targets = list.slice(0, limit);
  const out: MachineDetail[] = [];
  let cursor = 0;
  const workers = Array.from({ length: 8 }, async () => {
    while (cursor < targets.length) {
      const i = cursor++;
      try {
        out.push(await api.get<MachineDetail>(`/machines/${targets[i].id}`));
      } catch {
        // bỏ qua máy lỗi — vẫn đi tiếp
      }
    }
  });
  await Promise.all(workers);
  return out;
}

function EolSummary({ expired, warning, ok, unknown }: { expired: number; warning: number; ok: number; unknown: number }) {
  return (
    <div className="mb-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
      {[
        { label: "Hết hạn hỗ trợ", n: expired, cls: "text-rose-600 bg-rose-50 ring-rose-600/20" },
        { label: "Sắp hết hạn (< 180 ngày)", n: warning, cls: "text-amber-600 bg-amber-50 ring-amber-600/20" },
        { label: "Còn hỗ trợ", n: ok, cls: "text-emerald-600 bg-emerald-50 ring-emerald-600/20" },
        { label: "Không xác định", n: unknown, cls: "text-slate-600 bg-slate-100 ring-slate-500/20" },
      ].map((b) => (
        <div
          key={b.label}
          className="flex h-24 flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-[11px] font-medium uppercase tracking-wide text-slate-400">{b.label}</p>
            <span className={`flex size-7 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset ${b.cls}`}>
              <CalendarClock className="size-4" />
            </span>
          </div>
          <p className="text-2xl font-bold tabular-nums text-slate-900">{b.n}</p>
        </div>
      ))}
    </div>
  );
}

export default function EolPage() {
  const [rows, setRows] = useState<Array<{ machine: MachineListItem; eol: EolInfo }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<PageResponse<MachineListItem>>("/machines", { status: undefined, limit: 50 });
      const list = data.items;
      const details = await fetchDetailsSequential(list);
      const mapped = details.map((d) => ({
        machine: d as MachineListItem,
        eol: getWindowsEol(d.latest_spec?.os_name, d.latest_spec?.os_build),
      }));
      mapped.sort((a, b) => (a.eol.daysLeft ?? 1e9) - (b.eol.daysLeft ?? 1e9));
      setRows(mapped);
      setGeneratedAt(new Date().toLocaleTimeString("vi-VN"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được dữ liệu EOL");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = useMemo(() => {
    return rows.reduce(
      (acc, r) => {
        acc[r.eol.status] += 1;
        return acc;
      },
      { expired: 0, warning: 0, ok: 0, unknown: 0 },
    );
  }, [rows]);

  return (
    <div>
      <PageHeader
        title="Báo cáo Windows EOL"
        description="Máy chạy Windows sắp/đã hết vòng đời hỗ trợ — cơ sở cho lộ trình nâng cấp (tính năng #5)"
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            <CalendarClock className="size-3.5" /> Tính lại
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && rows.length === 0 ? (
        <Spinner label="Đang thu thập cấu hình máy (nạp chi tiết từng máy)…" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<CalendarClock className="size-10" />}
          title="Chưa có dữ liệu cấu hình"
          description="Cần ít nhất 1 máy đã gửi inventory (os_name + os_build) để tính EOL."
        />
      ) : (
        <>
          <EolSummary {...summary} />
          <Card
            title={`Danh sách chi tiết (${rows.length} máy)`}
            subtitle={generatedAt ? `Tính lúc ${generatedAt}` : undefined}
            padded={false}
          >
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr>
                    <th scope="col" className={TH}>Hostname</th>
                    <th scope="col" className={TH}>Hệ điều hành</th>
                    <th scope="col" className={TH}>Ngày EOL</th>
                    <th scope="col" className={TH}>Còn lại</th>
                    <th scope="col" className={TH}>Trạng thái</th>
                    <th scope="col" className={TH}></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ machine, eol }) => (
                    <tr key={machine.id} className={TR_HOVER}>
                      <td className={`${TD} font-medium text-slate-800`}>
                        {machine.hostname ?? "(chưa đặt tên)"}
                      </td>
                      <td className={`${TD} text-xs text-slate-600`}>{eol.release}</td>
                      <td className={`${TD} text-xs`}>{formatDate(eol.eolDate)}</td>
                      <td className={`${TD} text-sm font-semibold ${
                        eol.daysLeft !== null && eol.daysLeft < 0
                          ? "text-rose-600"
                          : eol.daysLeft !== null && eol.daysLeft <= 180
                            ? "text-amber-600"
                            : "text-slate-600"
                      }`}>
                        {eol.daysLeft !== null ? `${eol.daysLeft} ngày` : "—"}
                      </td>
                      <td className={TD}>
                        <Badge className={EOL_STATUS_META[eol.status].badge}>
                          {EOL_STATUS_META[eol.status].label}
                        </Badge>
                      </td>
                      <td className={TD}>
                        <Link
                          href={`/machines/${machine.id}`}
                          className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-600 hover:underline"
                        >
                          Chi tiết <ChevronRight className="size-3.5" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}