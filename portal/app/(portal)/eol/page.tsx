"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
async function fetchMachineDetails(
  list: MachineListItem[],
  signal: AbortSignal,
  concurrency = 4,
): Promise<MachineDetail[]> {
  const targets = list.slice(0, 400);
  const results: Array<MachineDetail | null> = Array(targets.length).fill(null);
  let cursor = 0;

  const worker = async () => {
    while (true) {
      if (signal.aborted) return;
      const index = cursor++;
      if (index >= targets.length) return;
      try {
        results[index] = await api.get<MachineDetail>(
          `/machines/${targets[index].id}`,
          undefined,
          { signal },
        );
      } catch (error) {
        if (signal.aborted || (error as { name?: string })?.name === "AbortError") return;
      }
    }
  };

  await Promise.all(
    Array.from({ length: Math.min(concurrency, targets.length) }, () => worker()),
  );
  return results.filter((item): item is MachineDetail => item !== null);
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
  const loadAbortRef = useRef<AbortController | null>(null);
  const loadInFlightRef = useRef(false);

  const load = useCallback(async () => {
    if (loadInFlightRef.current) return;
    loadInFlightRef.current = true;
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    setLoading(true);
    try {
      const data = await api.get<PageResponse<MachineListItem>>(
        "/machines",
        { status: undefined, limit: 50 },
        { signal: controller.signal },
      );
      const details = await fetchMachineDetails(data.items, controller.signal, 4);
      if (controller.signal.aborted || loadAbortRef.current !== controller) return;
      const mapped = details.map((d) => ({
        machine: d as MachineListItem,
        eol: getWindowsEol(d.latest_spec?.os_name, d.latest_spec?.os_build),
      }));
      mapped.sort((a, b) => (a.eol.daysLeft ?? 1e9) - (b.eol.daysLeft ?? 1e9));
      setRows(mapped);
      setGeneratedAt(new Date().toLocaleTimeString("vi-VN"));
      setError(null);
    } catch (error) {
      if (controller.signal.aborted || (error as { name?: string })?.name === "AbortError") return;
      if (loadAbortRef.current === controller) {
        setError(error instanceof Error ? error.message : "Không tải được dữ liệu EOL");
      }
    } finally {
      if (loadAbortRef.current === controller) {
        loadInFlightRef.current = false;
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      // React StrictMode chạy effect mount → cleanup → mount trong dev.
      // Nếu cleanup chỉ abort mà không reset in-flight/abort ref, lần mount
      // thứ hai sẽ thấy `loadInFlightRef.current = true` và bị chặn ngay
      // từ đầu `load()` — trang kẹt ở EmptyState cho tới khi user bấm Tính lại.
      // Đặt cả hai ref về trạng thái ban đầu để drop stale controller và cho
      // phép mount kế tiếp (kể cả khi abort xảy ra giữa chừng) khởi động lại.
      loadAbortRef.current?.abort();
      loadInFlightRef.current = false;
      loadAbortRef.current = null;
    };
  }, [load]);

  const summary = useMemo(() => {
    return (rows ?? []).reduce(
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
        title="Báo cáo Windows hết hỗ trợ"
        description="Máy chạy Windows sắp/đã hết vòng đời hỗ trợ — cơ sở cho lộ trình nâng cấp (tính năng #5)"
        actions={
          <Button variant="secondary" size="sm" disabled={loading} onClick={() => void load()}>
            <CalendarClock className="size-3.5" /> Tính lại
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && (rows?.length ?? 0) === 0 ? (
        <Spinner label="Đang thu thập cấu hình máy (nạp chi tiết từng máy)…" />
      ) : (rows?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<CalendarClock className="size-10" />}
          title="Chưa có dữ liệu cấu hình"
          description="Cần ít nhất 1 máy đã gửi inventory (os_name + os_build) để tính EOL."
        />
      ) : (
        <>
          <EolSummary {...summary} />
          <Card
            title={`Danh sách chi tiết (${rows?.length ?? 0} máy)`}
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
                  {(rows ?? []).map(({ machine, eol }) => (
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