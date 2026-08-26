"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Power } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineTimeline } from "@/lib/types";
import { Badge, Card, ErrorBanner, Spinner } from "@/components/ui";

function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}g ${m}p`;
  return `${m} phút`;
}

function fmtHours(sec: number): string {
  const h = sec / 3600;
  return h >= 10 ? `${Math.round(h)}h` : `${h.toFixed(1)}h`;
}

/** yyyy-mm-dd theo giờ địa phương (tránh lệch múi của toISOString). */
function localIso(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Nhãn ngày ngắn cho tooltip/trục: "01/07". */
function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return m && d ? `${d}/${m}` : iso;
}

const WEEKDAY_LABELS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"] as const;

/* Thang nhiệt theo thương hiệu — chỉ dùng làm màu dữ liệu trên ô heatmap */
const HEAT_CLASSES = [
  "bg-slate-100", // 0 — không hoạt động
  "bg-brand-100",
  "bg-brand-200",
  "bg-brand-400",
  "bg-brand-600", // đậm nhất
] as const;

/**
 * Heat map bật/tắt máy (tính năng #1) — mỗi ngày 1 ô, đậm nhạt theo thời gian
 * online; sắp theo tuần (hàng = thứ, cột = tuần). Thay cho danh sách phiên.
 */
export function MachineTimelineSection({ machineId, days = 35 }: { machineId: string; days?: number }) {
  const [data, setData] = useState<MachineTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const t = await api.get<MachineTimeline>(`/machines/${machineId}/timeline`, { days });
      setData(t);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được timeline");
    } finally {
      setLoading(false);
    }
  }, [machineId, days]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Dải ngày liên tục (đủ ô cả khi backend chỉ trả ngày có heartbeat). */
  const grid = useMemo(() => {
    if (!data) return null;
    const byDate = new Map(data.daily.map((d) => [d.date, d]));
    const end = new Date();
    const cells: Array<{ date: string; online_sec: number; boots: number }> = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(end);
      d.setDate(end.getDate() - i);
      const iso = localIso(d);
      const hit = byDate.get(iso);
      cells.push({ date: iso, online_sec: hit?.online_sec ?? 0, boots: hit?.boots ?? 0 });
    }
    // Cột đầu bắt đầu từ Thứ 2 — đệm ô trống trước ngày đầu tiên
    // getDay(): CN=0 … T7=6 → đổi sang index T2=0
    const lead = (cells[0] ? new Date(cells[0].date + "T00:00:00").getDay() + 6 : 0) % 7;
    return { cells, lead };
  }, [data, days]);

  if (loading && !data) return <Spinner label="Đang tính timeline…" />;
  if (error) return <ErrorBanner message={error} onRetry={() => void load()} />;
  if (!data || !grid) return null;

  const activeDays = data.daily.filter((d) => d.online_sec > 0).length;
  const avgPerDay = data.daily.length > 0 ? data.total_online_sec / data.days : 0;

  /* Cột tuần: chèn ô trống đầu, cắt thành từng nhóm 7 */
  const padded: Array<(typeof grid.cells)[number] | null> = [...Array.from({ length: grid.lead }, () => null), ...grid.cells];
  const weeks: Array<Array<(typeof padded)[number]>> = [];
  for (let i = 0; i < padded.length; i += 7) weeks.push(padded.slice(i, i + 7));

  const maxSec = Math.max(1, ...data.daily.map((d) => d.online_sec));
  const heatLevel = (sec: number) => (sec <= 0 ? 0 : sec / maxSec > 0.75 ? 4 : sec / maxSec > 0.5 ? 3 : sec / maxSec > 0.25 ? 2 : 1);

  return (
    <Card
      title="Lịch sử bật/tắt máy"
      subtitle={`${data.days} ngày gần nhất — ô càng đậm thì máy online càng lâu (di chuột để xem chi tiết)`}
      actions={
        <Badge className="bg-brand-50 text-brand-700 ring-brand-600/20">
          <Power className="size-3" /> Heat map
        </Badge>
      }
    >
      {/* ── Chỉ số tổng hợp ── */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Tổng online", value: fmtHours(data.total_online_sec) },
          { label: "Phiên bật máy", value: `${data.sessions_count} phiên` },
          { label: "TB mỗi ngày", value: fmtHours(avgPerDay) },
          { label: "Ngày hoạt động", value: `${activeDays}/${data.days}` },
        ].map((s) => (
          <div key={s.label} className="rounded-md bg-slate-50 px-3 py-2">
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{s.label}</p>
            <p className="mt-0.5 text-lg font-bold tabular-nums tracking-tight text-slate-900">{s.value}</p>
          </div>
        ))}
      </div>

      {/* ── Heat map theo lịch ── */}
      <div className="overflow-x-auto pb-1">
        <div className="flex min-w-max gap-1.5">
          {/* Nhãn thứ */}
          <div className="flex flex-col gap-1 pr-1 pt-[18px] text-[10px] leading-none text-slate-400">
            {WEEKDAY_LABELS.map((w, i) => (
              <span key={w} className={`flex h-3.5 items-center ${i % 2 === 1 ? "opacity-0" : ""}`}>
                {w}
              </span>
            ))}
          </div>

          {/* Các cột tuần */}
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-1">
              <span className="h-[14px] text-center text-[10px] leading-none text-slate-400">
                {(() => {
                  const first = week.find(Boolean);
                  // Gắn nhãn tháng ở cột chứa ngày 1–7
                  return first && Number(first.date.slice(8, 10)) <= 7 ? `${first.date.slice(5, 7)}/` : "";
                })()}
              </span>
              {week.map((cell, di) =>
                cell === null ? (
                  <span key={`blank-${di}`} className="size-3.5 rounded-xs" aria-hidden />
                ) : (
                  <span
                    key={cell.date}
                    role="img"
                    aria-label={`${shortDate(cell.date)}: ${fmtDuration(cell.online_sec)} online`}
                    title={`${shortDate(cell.date)} — ${fmtDuration(cell.online_sec)} online · ${cell.boots} lần bật`}
                    className={`size-3.5 rounded-xs transition-colors duration-150 motion-reduce:transition-none hover:ring-2 hover:ring-brand-600/40 ${HEAT_CLASSES[heatLevel(cell.online_sec)]}`}
                  />
                ),
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Chú giải thang nhiệt */}
      <div className="mt-3 flex items-center justify-end gap-1.5 text-[11px] text-slate-400">
        <span>Ít</span>
        {HEAT_CLASSES.map((c) => (
          <span key={c} className={`size-3 rounded-xs ${c}`} aria-hidden />
        ))}
        <span>Nhiều</span>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
        Phiên = chuỗi heartbeat liên tiếp (ngắt quãng &gt; 5 phút tính là tắt). Dữ liệu từ bảng
        heartbeats partition theo ngày.
      </p>
    </Card>
  );
}
