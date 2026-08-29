"use client";

/**
 * Section "Sự kiện DFIR (Velociraptor)" — hiển thị TRONG panel
 * "Xem log" (VeloLogDrawer) của card Velociraptor — Live data, trang máy.
 *
 * Chuyển thể từ script "Velociraptor Top 10 DFIR Events Extractor":
 *   - Windows.Forensics.Prefetch — Top N binary được thực thi gần nhất
 *   - Windows.Network.Netstat      — Top N kết nối mạng / cổng đang mở
 *   - Windows.System.Pslist        — Top N tiến trình hệ thống
 *
 * Bảng hiển thị full nội dung (không cắt ngắn) — cuộn NGANG khi dữ liệu dài
 * (path / command line dài).
 *
 * Quy trình:
 *   1. GET  /admin/velociraptor/clients/{client_id}/top10?top_n=N — đọc dữ liệu
 *      đã có (tái sử dụng flow FINISHED gần nhất, KHÔNG collect mới).
 *   2. Artifact chưa có dữ liệu → nút "Thu thập dữ liệu còn thiếu"
 *      → POST /top10/collect (kick-off, không chờ) → poll GET tới khi flow
 *      FINISHED rồi hiển thị Top N.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Loader2,
  PlayCircle,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  VelociraptorTop10Artifact,
  VelociraptorTop10CollectResponse,
  VelociraptorTop10Response,
} from "@/lib/types";
import { Badge, Button, ErrorBanner, Select } from "@/components/ui";

/* ── Helpers hiển thị ─────────────────────────────────────── */

/** Số sự kiện Admin có thể chọn hiển thị cho mỗi artifact khi điều tra. */
export const TOP_N_OPTIONS = [10, 20, 50, 100];

/** Format timestamp Velociraptor (ns | ISO string | array) → "YYYY-MM-DD HH:MM:SS". */
export function fmtTs(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return fmtTs(value[0]);
  if (typeof value === "number") {
    let v = value;
    if (v > 10 ** 11) v = v / 1_000_000; // ns → s
    const d = new Date(v * 1000);
    if (Number.isNaN(d.getTime())) return "—";
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
  const s = String(value);
  return s.length >= 19 ? s.slice(0, 19).replace("T", " ") : s;
}

function kv(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

type ColSpec = {
  key?: string;
  label: string;
  mono?: boolean;
  align?: "right";
  render?: (row: Record<string, unknown>) => React.ReactNode;
};

/** Cột hiển thị cho từng artifact — khớp output script gốc. */
const ARTIFACT_COLUMNS: Record<string, ColSpec[]> = {
  "Windows.Forensics.Prefetch": [
    { key: "ModificationTime", label: "Sửa lần cuối", render: (r) => fmtTs(r.ModificationTime) },
    { key: "Executable", label: "Executable", mono: true },
    { key: "LastRunTimes", label: "Chạy gần nhất", render: (r) => fmtTs(r.LastRunTimes) },
    { key: "RunCount", label: "Số lần", align: "right" },
    {
      key: "OSPath",
      label: "File",
      render: (r) => (
        <span title={kv(r.OSPath)} className="block">
          {kv(r.OSPath)}
        </span>
      ),
    },
  ],
  "Windows.Network.Netstat": [
    { key: "Pid", label: "PID" },
    { key: "Name", label: "Tiến trình" },
    { label: "Local", mono: true, render: (r) => `${kv(r["Laddr.IP"])}:${kv(r["Laddr.Port"])}` },
    { label: "Remote", mono: true, render: (r) => `${kv(r["Raddr.IP"])}:${kv(r["Raddr.Port"])}` },
    { key: "Status", label: "Status" },
  ],
  "Windows.System.Pslist": [
    { key: "Pid", label: "PID" },
    { key: "Ppid", label: "PPID" },
    { key: "Name", label: "Tên tiến trình" },
    {
      key: "Exe",
      label: "Đường dẫn / lệnh",
      mono: true,
      render: (r) => (
        <span title={kv(r.Exe ?? r.CommandLine)} className="block">
          {kv(r.Exe ?? r.CommandLine)}
        </span>
      ),
    },
  ],
};

/** Badge trạng thái dữ liệu của 1 artifact. */
function sourceBadge(a: VelociraptorTop10Artifact) {
  switch (a.source) {
    case "reused":
      return (
        <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
          <CheckCircle2 className="mr-1 size-3" /> Dữ liệu gần nhất
        </Badge>
      );
    case "running":
      return (
        <Badge className="bg-blue-100 text-blue-700 ring-blue-600/20">
          <Loader2 className="mr-1 size-3 animate-spin" /> Đang thu thập…
        </Badge>
      );
    case "collected":
      return (
        <Badge className="bg-violet-50 text-violet-700 ring-violet-600/20">
          <CheckCircle2 className="mr-1 size-3" /> Mới thu thập
        </Badge>
      );
    case "error":
      return (
        <Badge className="bg-rose-50 text-rose-700 ring-rose-600/20">
          <XCircle className="mr-1 size-3" /> Lỗi
        </Badge>
      );
    default:
      return (
        <Badge className="bg-slate-100 text-slate-500 ring-slate-500/20">
          Chưa có dữ liệu
        </Badge>
      );
  }
}

function ArtifactTable({ rows, cols }: { rows: Array<Record<string, unknown>>; cols: ColSpec[] }) {
  return (
    <div className="overflow-x-auto rounded-md ring-1 ring-inset ring-slate-200">
      <table className="w-full min-w-max whitespace-nowrap text-xs">
        <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">#</th>
            {cols.map((c) => (
              <th
                key={c.label}
                className={`px-3 py-2 whitespace-nowrap ${c.align === "right" ? "text-right" : "text-left"}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-slate-50">
              <td className="px-3 py-2 text-[10px] text-slate-400">{i + 1}</td>
              {cols.map((c) => (
                <td
                  key={c.label}
                  className={`px-3 py-2 whitespace-nowrap align-top text-slate-700 ${
                    c.align === "right" ? "text-right" : ""
                  } ${c.mono ? "font-mono text-[11px]" : ""}`}
                >
                  {c.render ? c.render(r) : kv(c.key ? r[c.key] : "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Section chính (nhúng trong VeloLogDrawer) ─────────────── */

export function VelociraptorTop10Section({
  clientId,
  allowlist = [],
}: {
  /** Velociraptor client_id (C.xxxx) của máy đang xem; null = chưa link → ẩn. */
  clientId: string | null;
  /** Allowlist artifact đang hiệu lực — xác định artifact nào thu thập được. */
  allowlist?: string[];
}) {
  /** Số sự kiện hiển thị mỗi artifact — Admin chọn khi điều tra. */
  const [topN, setTopN] = useState(10);
  const [data, setData] = useState<VelociraptorTop10Response | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [notAllowed, setNotAllowed] = useState<string[]>([]);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    setPolling(false);
  }, []);

  const load = useCallback(async () => {
    if (!clientId) return null;
    try {
      const d = await api.get<VelociraptorTop10Response>(
        `/admin/velociraptor/clients/${clientId}/top10`,
        { top_n: topN },
      );
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được Top sự kiện DFIR");
      return null;
    }
  }, [clientId, topN]);

  // Load ngay khi section được mount (panel "Xem log" mở)
  useEffect(() => {
    if (!clientId) return;
    setLoading(true);
    void load().finally(() => setLoading(false));
    return () => stopPoll();
  }, [clientId, load, stopPoll]);

  /** Kick-off collect các artifact còn thiếu rồi poll tới khi có dữ liệu. */
  const startCollect = async () => {
    if (!clientId || collecting || polling) return;
    setCollecting(true);
    setError(null);
    setNotAllowed([]);
    // Artifact không thể thu thập (ngoài allowlist / lỗi) — không chờ poll
    const skipped = new Set<string>();
    try {
      const res = await api.post<VelociraptorTop10CollectResponse>(
        `/admin/velociraptor/clients/${clientId}/top10/collect`,
      );
      res.artifacts
        .filter((a) => a.status === "not_allowed" || a.status === "error")
        .forEach((a) => skipped.add(a.artifact));
      setNotAllowed(
        res.artifacts.filter((a) => a.status === "not_allowed").map((a) => a.artifact),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Collect thất bại");
      setCollecting(false);
      return;
    }
    setCollecting(false);

    // Poll GET cho tới khi không còn artifact đang thu thập/chờ (tối đa ~2 phút)
    setPolling(true);
    let tries = 0;
    let active = true;
    const tick = async () => {
      if (!active) return;
      tries += 1;
      const d = await load();
      const pending =
        d !== null &&
        d.artifacts.some(
          (a) =>
            !skipped.has(a.artifact) &&
            (a.source === "missing" || a.source === "running"),
        );
      if (!pending || tries >= 30) {
        active = false;
        stopPoll();
      }
    };
    await tick();
    if (active) {
      pollTimer.current = setInterval(() => void tick(), 4000);
    }
  };

  if (!clientId) return null;

  const busy = loading || collecting || polling;
  const canCollect = allowlist.length > 0;
  const hasAnyData = (data?.artifacts ?? []).some((a) => a.rows.length > 0);

  return (
    <div className="mb-6 border-t border-slate-100 pt-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          <Activity className="size-3 text-violet-600" /> Sự kiện DFIR (Velociraptor)
          {polling && (
            <Badge className="bg-blue-100 text-blue-700 ring-blue-600/20">
              <Loader2 className="mr-1 size-3 animate-spin" /> Đang cập nhật…
            </Badge>
          )}
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={String(topN)}
            onChange={(e) => setTopN(Number(e.target.value))}
            disabled={busy}
            className="h-8 w-28 text-xs"
            title="Số sự kiện hiển thị cho mỗi artifact (điều tra sâu hơn khi cần)"
            aria-label="Số sự kiện hiển thị"
          >
            {TOP_N_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} sự kiện
              </option>
            ))}
          </Select>
          {canCollect && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void startCollect()}
              disabled={busy}
              title="Chạy artifact chưa có dữ liệu trên Velociraptor"
            >
              {collecting || polling ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <PlayCircle className="size-3.5" />
              )}
              Thu thập dữ liệu còn thiếu
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setLoading(true);
              void load().finally(() => setLoading(false));
            }}
            disabled={loading}
            title="Tải lại sự kiện từ Velociraptor Server"
          >
            <RefreshCw className={"size-3.5 " + (loading ? "animate-spin" : "")} /> Làm mới
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-3">
          <ErrorBanner message={error} onRetry={() => void load()} />
        </div>
      )}

      {notAllowed.length > 0 && (
        <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-800 ring-1 ring-inset ring-amber-200">
          ⚠️ Artifact chưa nằm trong allowlist nên <strong>không được thu thập</strong>:{" "}
          <code className="font-mono">{notAllowed.join(", ")}</code>. Super Admin bổ sung tại{" "}
          <em>/dfir/settings</em> để chạy được artifact này.
        </div>
      )}

      {loading && !data ? (
        <p className="flex items-center gap-2 py-2 text-xs text-slate-500">
          <Loader2 className="size-3.5 animate-spin" /> Đang tải sự kiện từ Velociraptor…
        </p>
      ) : data ? (
        <div>
          {data.artifacts.map((a) => (
            <div key={a.artifact} className="mb-4 last:mb-0">
              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                <h5 className="text-[11px] font-semibold text-slate-600">{a.label}</h5>
                <div className="flex items-center gap-2">
                  {sourceBadge(a)}
                  {a.flow_id && (
                    <span className="font-mono text-[10px] text-slate-400" title={a.flow_id}>
                      {a.flow_id.slice(0, 16)}
                    </span>
                  )}
                  {a.total_rows > 0 && (
                    <span className="text-[10px] text-slate-400">
                      {a.rows.length}/{a.total_rows} dòng
                    </span>
                  )}
                </div>
              </div>

              {a.source === "error" ? (
                <ErrorBanner message={a.error ?? "Lỗi khi đọc dữ liệu từ Velociraptor"} />
              ) : a.source === "missing" ? (
                <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500 ring-1 ring-inset ring-slate-200">
                  Chưa có dữ liệu cho artifact này trên client.{" "}
                  {canCollect ? (
                    <button
                      className="font-medium text-brand-600 hover:underline"
                      onClick={() => void startCollect()}
                    >
                      Bấm "Thu thập dữ liệu còn thiếu"
                    </button>
                  ) : (
                    "Cấu hình Velociraptor ở /dfir/settings để thu thập."
                  )}{" "}
                  để chạy artifact trên Velociraptor.
                </p>
              ) : a.source === "running" ? (
                <p className="rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-700 ring-1 ring-inset ring-blue-200">
                  Flow đang chạy trên Velociraptor… dữ liệu sẽ hiện ở đây sau khi hoàn tất.
                </p>
              ) : a.rows.length === 0 ? (
                <p className="text-xs text-slate-500">
                  Artifact đã chạy nhưng không có dòng dữ liệu nào.
                </p>
              ) : (
                <ArtifactTable
                  rows={a.rows}
                  cols={ARTIFACT_COLUMNS[a.artifact] ?? [{ key: undefined, label: "Dữ liệu" }]}
                />
              )}
            </div>
          ))}

          {!hasAnyData && !error && (
            <p className="rounded-md bg-slate-50 px-3 py-2.5 text-xs leading-relaxed text-slate-500 ring-1 ring-inset ring-slate-200">
              Chưa có sự kiện nào được trích xuất cho client này.{" "}
              {canCollect
                ? 'Bấm "Thu thập dữ liệu còn thiếu" để chạy Prefetch / Netstat / Pslist trên Velociraptor (có thể mất tới ~2 phút).'
                : "Cấu hình Velociraptor ở /dfir/settings để thu thập."}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
