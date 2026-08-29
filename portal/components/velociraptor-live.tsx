"use client";

import { Activity, CheckCircle2, ExternalLink, Loader2, PlayCircle, RefreshCw, ScrollText, X, XCircle } from "lucide-react";
import type { VelociraptorClientMetadata } from "@/lib/types";
import { Badge, Button, Card, IconButton } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { VelociraptorTop10Section } from "@/components/velociraptor-top10";

/**
 * Card "Velociraptor — Live data" — dữ liệu realtime từ Velociraptor Server.
 * Trên trang máy: nằm cột 2/5 bên phải (heatmap chiếm 3/5 bên trái).
 * Có nút "Xem log" mở panel trượt từ phải sang trái (xem VeloLogDrawer).
 */
export function VelociraptorLiveCard({
  metadata,
  loading,
  error,
  active,
  result,
  busy,
  canCollect,
  guiUrl,
  onRefresh,
  onOpenLogs,
  onCollect,
  className = "",
}: {
  metadata: VelociraptorClientMetadata | null;
  loading: boolean;
  error: string | null;
  /** Velociraptor backend đang hoạt động (có cấu hình + creds hợp lệ). */
  active: boolean;
  /** Kết quả collect gần nhất (banner thành công / thất bại). */
  result: { ok: boolean; message: string; url: string | null } | null;
  /** Đang gửi collect tới Velociraptor. */
  busy: boolean;
  /** Hiện nút "Collect Artifact" (admin + đã cấu hình). */
  canCollect: boolean;
  /** Deep-link tới Velociraptor GUI cho client này (nếu có server_url). */
  guiUrl: string | null;
  onRefresh: () => void;
  onOpenLogs: () => void;
  onCollect: () => void;
  /** Class thêm cho Card — vd "lg:col-span-2 h-full" khi đặt trực tiếp trong grid. */
  className?: string;
}) {
  return (
    <Card
      className={className}
      title={
        <span className="inline-flex flex-wrap items-center gap-2">
          <Activity className="size-4 text-violet-600" /> Velociraptor — Live data
          {active ? (
            <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">
              <CheckCircle2 className="mr-1 size-3" /> Đang hoạt động
            </Badge>
          ) : (
            <Badge className="bg-amber-100 text-amber-700 ring-amber-600/20">Chưa bật</Badge>
          )}
          {loading && <Loader2 className="size-3.5 animate-spin text-slate-400" />}
        </span> as unknown as string
      }
      subtitle="Dữ liệu realtime từ Velociraptor Server (qua API). Có thể chậm ~5 phút so với máy thật."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onOpenLogs} title="Xem log từ Velociraptor">
            <ScrollText className="size-3.5" /> Xem log
          </Button>
          {canCollect && (
            <Button size="sm" onClick={onCollect} disabled={busy} title="Thu thập bằng chứng qua Velociraptor">
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : <PlayCircle className="size-3.5" />} Collect
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={onRefresh}
            disabled={loading}
            title="Tải lại từ Velociraptor Server"
          >
            <RefreshCw className={"size-3.5 " + (loading ? "animate-spin" : "")} /> Làm mới
          </Button>
        </div>
      }
    >
      {result && (
        <div
          className={`mb-3 flex items-start gap-2 rounded-lg px-4 py-3 text-sm ring-1 ring-inset ${
            result.ok
              ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
              : "bg-rose-50 text-rose-800 ring-rose-200"
          }`}
        >
          {result.ok ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          ) : (
            <XCircle className="mt-0.5 size-4 shrink-0 text-rose-600" />
          )}
          <div className="flex-1">
            <p>{result.message}</p>
            {result.url && (
              <a
                href={result.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1 font-mono text-[11px] text-brand-600 hover:underline"
              >
                Mở Velociraptor GUI
                <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        </div>
      )}

      {error && (
        <p className="mb-3 text-xs text-rose-700">⚠️ {error}</p>
      )}

      {metadata && (
        <div className="mb-4">
          <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Thông tin realtime (Velociraptor Server)
          </h4>
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <dt className="text-slate-500">Hostname (Velociraptor)</dt>
              <dd className="font-medium text-slate-900">
                {metadata.os_info?.hostname ?? "—"}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-slate-500">OS</dt>
              <dd className="font-medium text-slate-900">
                {metadata.os_info?.system ?? "—"}
                {metadata.os_info?.release ? ` (${metadata.os_info.release})` : ""}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-slate-500">Agent version</dt>
              <dd className="font-medium text-slate-900">
                {(metadata.agent_information?.version as string | undefined) ?? "—"}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-slate-500">Last seen (live)</dt>
              <dd className="font-medium text-slate-900">
                {metadata.last_seen_at
                  ? formatDateTime(
                      new Date(Number(metadata.last_seen_at) / 1e6).toISOString(),
                    )
                  : "—"}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-slate-500">Last IP</dt>
              <dd className="font-mono text-[11px] font-medium text-slate-900">
                {metadata.last_ip ?? "—"}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-slate-500">First seen</dt>
              <dd className="font-medium text-slate-900">
                {metadata.first_seen_at
                  ? formatDateTime(
                      new Date(Number(metadata.first_seen_at) * 1000).toISOString(),
                    )
                  : "—"}
              </dd>
            </div>
          </dl>
        </div>
      )}
    </Card>
  );
}

/**
 * Panel trượt vào từ bên phải (overlay lên màn hình) hiển thị
 * dữ liệu đầy đủ từ Velociraptor cho 1 client: metadata realtime +
 * Top 10 sự kiện DFIR (Prefetch / Netstat / Pslist) + toàn bộ flows.
 * Panel rộng ~1/2 màn hình (lg trở lên) để chứa được các bảng dữ liệu.
 */
export function VeloLogDrawer({
  open,
  onClose,
  metadata,
  loading,
  error,
  onRefresh,
  guiUrl,
  clientId = null,
  allowlist = [],
}: {
  open: boolean;
  onClose: () => void;
  metadata: VelociraptorClientMetadata | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  /** Deep-link tới Velociraptor GUI cho client này (nếu có server_url). */
  guiUrl: string | null;
  /** Velociraptor client_id — để trích xuất Top 10 sự kiện DFIR trong panel. */
  clientId?: string | null;
  /** Allowlist artifact đang hiệu lực — xác định artifact nào thu thập được. */
  allowlist?: string[];
}) {
  return (
    <>
      {/* Backdrop — panel overlay lên màn hình ở mọi kích thước (không ép card co lại) */}
      <div
        aria-hidden={!open}
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-slate-900/40 transition-opacity duration-300 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        aria-hidden={!open}
        aria-label="Log Velociraptor"
        className={`fixed inset-y-0 right-0 z-50 flex w-full transform flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-300 ease-in-out lg:w-1/2 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <h3 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight text-slate-800">
              <ScrollText className="size-4 text-violet-600" /> Velociraptor — Logs
            </h3>
            <p className="mt-0.5 text-[13px] leading-snug text-slate-500">
              Dữ liệu realtime từ Velociraptor Server (client {metadata?.client_id ?? "?"})
              {guiUrl && (
                <a
                  href={guiUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-2 inline-flex items-center gap-1 text-[11px] font-medium text-brand-600 hover:underline"
                  title="Mở Velociraptor GUI (tab mới)"
                >
                  <ExternalLink className="size-3" /> Velociraptor GUI
                </a>
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={onRefresh}
              disabled={loading}
              title="Tải lại từ Velociraptor Server"
            >
              <RefreshCw className={"size-3.5 " + (loading ? "animate-spin" : "")} /> Làm mới
            </Button>
            <IconButton label="Đóng" onClick={onClose} className="hover:bg-slate-100 hover:text-slate-600">
              <X className="size-4" />
            </IconButton>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {error && (
            <p className="mb-3 text-xs text-rose-700">⚠️ {error}</p>
          )}

          {metadata && (
            <div className="mb-5">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Thông tin realtime (Velociraptor Server)
              </h4>
              <dl className="grid gap-2 text-xs sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <dt className="text-slate-500">Hostname (Velociraptor)</dt>
                  <dd className="font-medium text-slate-900">
                    {metadata.os_info?.hostname ?? "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-slate-500">OS</dt>
                  <dd className="font-medium text-slate-900">
                    {metadata.os_info?.system ?? "—"}
                    {metadata.os_info?.release ? ` (${metadata.os_info.release})` : ""}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-slate-500">Agent version</dt>
                  <dd className="font-medium text-slate-900">
                    {(metadata.agent_information?.version as string | undefined) ?? "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-slate-500">Last seen (live)</dt>
                  <dd className="font-medium text-slate-900">
                    {metadata.last_seen_at
                      ? formatDateTime(
                          new Date(Number(metadata.last_seen_at) / 1e6).toISOString(),
                        )
                      : "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-slate-500">Last IP</dt>
                  <dd className="font-mono text-[11px] font-medium text-slate-900">
                    {metadata.last_ip ?? "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-slate-500">First seen</dt>
                  <dd className="font-medium text-slate-900">
                    {metadata.first_seen_at
                      ? formatDateTime(
                          new Date(Number(metadata.first_seen_at) * 1000).toISOString(),
                        )
                      : "—"}
                  </dd>
                </div>
              </dl>
            </div>
          )}

          {/* Top 10 sự kiện DFIR (Prefetch / Netstat / Pslist) — trích xuất từ Velociraptor */}
          {open && <VelociraptorTop10Section clientId={clientId} allowlist={allowlist} />}
        </div>
      </aside>
    </>
  );
}
