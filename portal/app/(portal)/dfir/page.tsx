"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  ExternalLink,
  HardDriveDownload,
  Loader2,
  Pencil,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldAlert,
  Siren,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-context";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  Textarea,
} from "@/components/ui";
import type { DfirHunt, VelociraptorAlert, VelociraptorConfig, VelociraptorLink } from "@/lib/types";
import { formatDateTime, timeAgo } from "@/lib/format";

/** Dashboard DFIR (Digital Forensics & Incident Response).
 *
 *  - Trạng thái Velociraptor (configured / disabled / unreachable).
 *  - Số máy đã link Velociraptor (mapping hostname ↔ client_id qua manual sync).
 *  - Hunt/Collect gần đây (audit log local).
 *  - Nút "Run Hunt" mở modal chọn artifact + scope.
 *
 *  FULL ON-DEMAND: Không có background cron. Admin trigger:
 *  - /admin/velociraptor/sync (manual hostname mapping)
 *  - /admin/velociraptor/alerts/scan (manual alert detection)
 *  - "Run Hunt" / "Collect Artifact" (per machine)
 *  - Mở máy /machines/[id] → tự động lookup hostname live qua Velociraptor API.
 */
export default function DfirPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";
  const isAdmin = user?.role === "super_admin" || user?.role === "admin_global"
    || user?.role === "org_admin" || user?.role === "admin_org";

  const [config, setConfig] = useState<VelociraptorConfig | null>(null);
  const [links, setLinks] = useState<VelociraptorLink[]>([]);
  const [hunts, setHunts] = useState<DfirHunt[]>([]);
  const [alerts, setAlerts] = useState<VelociraptorAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showHuntModal, setShowHuntModal] = useState(false);
  const [confirmSync, setConfirmSync] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [huntArtifact, setHuntArtifact] = useState("");
  const [huntScope, setHuntScope] = useState<"all" | "single">("all");
  const [huntName, setHuntName] = useState("");
  const [huntDescription, setHuntDescription] = useState("");
  const [huntSubmitting, setHuntSubmitting] = useState(false);
  const [huntError, setHuntError] = useState<string | null>(null);
  const [huntSuccess, setHuntSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [cfg, lk, hs, al] = await Promise.all([
        api.get<VelociraptorConfig>("/admin/velociraptor/config"),
        api.get<VelociraptorLink[]>("/admin/velociraptor/links"),
        api.get<DfirHunt[]>("/admin/velociraptor/hunts", { limit: 20 }),
        api.get<VelociraptorAlert[]>("/admin/velociraptor/alerts", { limit: 10 }),
      ]);
      setConfig(cfg);
      setLinks(lk);
      setHunts(hs);
      setAlerts(al);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được dữ liệu DFIR");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await api.post<{ linked?: number; total_clients?: number; skipped?: boolean; error?: string }>(
        "/admin/velociraptor/sync",
      );
      if (res.skipped) {
        setHuntError(`Sync bỏ qua: ${res.error ?? "chưa cấu hình Velociraptor"}`);
      } else {
        setHuntSuccess(`Sync xong: ${res.linked ?? 0}/${res.total_clients ?? 0} client đã link.`);
      }
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : "Sync thất bại");
    } finally {
      setSyncing(false);
      setConfirmSync(false);
    }
  };

  const openHuntModal = () => {
    setHuntArtifact(config?.allowlist[0] ?? "");
    setHuntScope("all");
    setHuntName("");
    setHuntDescription("");
    setHuntError(null);
    setHuntSuccess(null);
    setShowHuntModal(true);
  };

  const submitHunt = async () => {
    if (!huntArtifact) {
      setHuntError("Chọn artifact");
      return;
    }
    setHuntSubmitting(true);
    setHuntError(null);
    setHuntSuccess(null);
    try {
      const res = await api.post<DfirHunt>("/admin/velociraptor/hunt", {
        artifact: huntArtifact,
        scope: huntScope,
        name: huntName.trim() || null,
        description: huntDescription.trim() || null,
      });
      setHuntSuccess(
        `Đã gửi Velociraptor: ${res.client_count ?? "?"} client. Xem kết quả tại /machines/[id] → DFIR section.`,
      );
      setShowHuntModal(false);
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : "Hunt thất bại");
    } finally {
      setHuntSubmitting(false);
    }
  };

  if (loading) return <Spinner label="Đang tải DFIR dashboard…" />;

  // Trạng thái tổng thể
  const hasCreds = config?.basic_auth_set || config?.client_config_set || config?.api_token_set;
  const cfgOk = config?.enabled && !!config?.server_url && hasCreds;
  const syncOk = !config?.last_sync_error;
  const cfgMissing = !config?.server_url || !hasCreds;

  return (
    <div className="space-y-6">
      <PageHeader
        title="DFIR — Digital Forensics & Incident Response"
        description="Thu thập bằng chứng từ xa qua Velociraptor. Backend đồng bộ hostname ↔ client_id mỗi 5 phút — không phụ thuộc agent."
        actions={
          <div className="flex gap-2">
            {isSuperAdmin && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setConfirmSync(true)}
                disabled={syncing || !cfgOk}
                title="Manual sync hostname ↔ client_id mapping (cho cả fleet — cập nhật bảng veloLink)"
              >
                {syncing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                Sync mapping
              </Button>
            )}
            {isSuperAdmin && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    setHuntError(null);
                    setHuntSuccess(null);
                    try {
                      const res = await api.post<{ scanned: boolean; alerts_count: number; latest_alerts: { severity: string; artifact_pattern: string }[] }>(
                        "/admin/velociraptor/alerts/scan",
                      );
                      setHuntSuccess(`Scan xong: ${res.alerts_count} alerts (mới nhất: ${res.latest_alerts.map(a => a.artifact_pattern + " (" + a.severity + ")").join(", ") || "không có"}).`);
                      void load();
                    } catch (e) {
                      setHuntError(e instanceof Error ? e.message : "Scan thất bại");
                    }
                  }}
                  disabled={!cfgOk}
                  title="Manual scan Velociraptor recent flows cho sensitive patterns"
                >
                  <Activity className="size-3.5" /> Scan alerts
                </Button>
                <Button size="sm" onClick={openHuntModal} disabled={!cfgOk || config?.allowlist.length === 0}>
                  <PlayCircle className="size-3.5" /> Chạy Hunt / Collect
                </Button>
              </>
            )}
          </div>
        }
      />

      {error && <ErrorBanner message={error} />}

      {!isSuperAdmin && (
        <p className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500 ring-1 ring-inset ring-slate-200">
          Bạn đang ở chế độ chỉ đọc — chỉ Super Admin được chạy hunt/collect. Vẫn có thể xem kết quả & deep-link sang Velociraptor GUI.
        </p>
      )}

      {huntSuccess && (
        <div className="flex items-start gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          <span>{huntSuccess}</span>
        </div>
      )}

      {huntError && (
        <div className="flex items-start gap-2 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800 ring-1 ring-inset ring-rose-200">
          <XCircle className="mt-0.5 size-4 shrink-0 text-rose-600" />
          <span>{huntError}</span>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Trạng thái cấu hình */}
        <Card title="Trạng thái Velociraptor">
          {cfgMissing ? (
            <EmptyState
              icon={<Siren className="size-8" />}
              title="Chưa cấu hình"
              description="Super Admin cần nhập Velociraptor Server URL + Username/Password (hoặc mTLS YAML) ở /dfir/settings."
              action={
                isSuperAdmin ? (
                  <Link href="/dfir/settings" className="text-sm font-medium text-brand-600 hover:underline">
                    Mở cài đặt →
                  </Link>
                ) : null
              }
            />
          ) : (
            <dl className="space-y-2.5 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Trạng thái</dt>
                <dd>
                  {cfgOk ? (
                    <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">
                      <Activity className="mr-1 size-3" /> Đang hoạt động
                    </Badge>
                  ) : (
                    <Badge className="bg-amber-100 text-amber-700 ring-amber-600/20">
                      <AlertTriangle className="mr-1 size-3" /> Đã cấu hình nhưng disabled
                    </Badge>
                  )}
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-slate-500">Server URL</dt>
                <dd className="break-all font-mono text-[12px] font-medium text-slate-900" title={config?.server_url ?? ""}>
                  {config?.server_url ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Auth</dt>
                <dd className="font-medium text-slate-900">
                  {config?.client_config_set
                    ? "mTLS (client cert)"
                    : config?.basic_auth_set
                      ? "HTTP Basic (username/password)"
                      : config?.api_token_set
                        ? "Bearer API token (legacy)"
                        : "Chưa có"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Allowlist</dt>
                <dd className="font-medium text-slate-900">{config?.allowlist.length ?? 0} artifact</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Sync lần cuối</dt>
                <dd className="font-medium text-slate-900">
                  {config?.last_sync_at
                    ? `${timeAgo(config.last_sync_at)} (${formatDateTime(config.last_sync_at)})`
                    : "—"}
                </dd>
              </div>
              {config?.last_sync_error && (
                <div className="rounded-md bg-rose-50 p-2 text-[12px] text-rose-700 ring-1 ring-inset ring-rose-200">
                  {config.last_sync_error}
                </div>
              )}
              {isSuperAdmin && (
                <div className="flex items-center justify-between border-t border-slate-100 pt-2">
                  <Link
                    href="/dfir/settings"
                    className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
                  >
                    <Pencil className="size-3" /> Chỉnh sửa cấu hình
                  </Link>
                  <span className="text-[11px] text-slate-400">/dfir/settings</span>
                </div>
              )}
            </dl>
          )}
        </Card>

        {/* Số link */}
        <Card title="Số máy đã link Velociraptor">
          <div className="flex flex-col gap-3">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold text-slate-900">{links.length}</span>
              <span className="text-sm text-slate-500">mapping</span>
            </div>
            {syncOk && cfgOk && (
              <p className="text-xs text-slate-500">
                {config?.last_sync_total ?? 0} client Velociraptor trả về lần sync gần nhất.
                {config?.last_sync_linked != null && config?.last_sync_total
                  ? ` Match: ${Math.round((100 * config.last_sync_linked) / Math.max(1, config.last_sync_total))}%`
                  : null}
              </p>
            )}
            <div className="max-h-48 overflow-y-auto rounded-md ring-1 ring-inset ring-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-2 py-1.5 text-left">Hostname</th>
                    <th className="px-2 py-1.5 text-left">Client ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {links.slice(0, 10).map((l) => (
                    <tr key={l.machine_id} className="hover:bg-slate-50">
                      <td className="px-2 py-1.5 font-medium text-slate-800">{l.hostname}</td>
                      <td className="px-2 py-1.5 font-mono text-[10px] text-slate-500">{l.client_id.slice(0, 12)}…</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Card>

        {/* Hành động nhanh */}
        <Card title="Hành động">
          <ul className="space-y-2 text-sm">
            <li>
              <Link href="/dfir/hunts" className="group flex items-center justify-between rounded-md px-2 py-1.5 text-slate-700 hover:bg-slate-50">
                Lịch sử hunt / collect
                <span className="text-xs text-slate-400 group-hover:text-brand-600">→</span>
              </Link>
            </li>
            {isAdmin && (
              <li>
                <Link href="/dfir/settings" className="group flex items-center justify-between rounded-md px-2 py-1.5 text-slate-700 hover:bg-slate-50">
                  Cài đặt Velociraptor
                  <span className="text-xs text-slate-400 group-hover:text-brand-600">→</span>
                </Link>
              </li>
            )}
            {config?.server_url && (
              <li>
                <a
                  href={config.server_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center justify-between rounded-md px-2 py-1.5 text-slate-700 hover:bg-slate-50"
                >
                  Mở Velociraptor GUI
                  <ExternalLink className="size-3 text-slate-400 group-hover:text-brand-600" />
                </a>
              </li>
            )}
          </ul>
          <p className="mt-3 border-t border-slate-100 pt-3 text-[11px] leading-relaxed text-slate-500">
            <ShieldAlert className="mr-1 inline size-3 align-text-top" />
            Kết quả hunt lưu trên Velociraptor Server. Chi tiết xem tại
            <em className="mx-1">/machines/[id]</em>
            (DFIR section).
          </p>
        </Card>
      </div>

      {/* Hunt gần đây */}
      <Card title="DFIR Alerts (chưa xử lý)" className="overflow-hidden p-0">
        {alerts.filter((a) => !a.resolved).length === 0 ? (
          <div className="p-6">
            <p className="text-sm text-slate-500">
              Chưa có alert nào. Alert tự động tạo khi có flow/artifact sensitive chạy trên Velociraptor
              (vd <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">Windows.Persistence.*</code>,
              {" "}
              <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">Generic.Detection.FIM.High</code>).
              Bấm "Scan alerts" ở trên để detect thủ công sau khi chạy hunt/collect.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 text-left">Severity</th>
                  <th className="px-4 py-2.5 text-left">Pattern</th>
                  <th className="px-4 py-2.5 text-left">Flow ID</th>
                  <th className="px-4 py-2.5 text-left">Message</th>
                  <th className="px-4 py-2.5 text-left">When</th>
                  <th className="px-4 py-2.5 text-left"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {alerts.filter((a) => !a.resolved).map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Badge
                        className={
                          a.severity === "critical"
                            ? "bg-rose-100 text-rose-700 ring-rose-600/20"
                            : a.severity === "warning"
                              ? "bg-amber-100 text-amber-700 ring-amber-600/20"
                              : "bg-blue-100 text-blue-700 ring-blue-600/20"
                        }
                      >
                        {a.severity}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-slate-700">
                      {a.artifact_pattern}
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-600">
                      {a.flow_id.slice(0, 16)}…
                    </td>
                    <td className="px-4 py-3 text-slate-600 max-w-md truncate" title={a.message}>
                      {a.message}
                    </td>
                    <td className="px-4 py-3 text-[11px] text-slate-500">
                      {timeAgo(a.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={async () => {
                          await api.patch(`/admin/velociraptor/alerts/${a.id}/resolve`);
                          void load();
                        }}
                        className="text-xs font-medium text-brand-600 hover:underline"
                      >
                        Đánh dấu đã xử lý
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Hunt / Collect gần đây" className="overflow-hidden p-0">
        {hunts.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={<Search className="size-8" />}
              title="Chưa chạy hunt nào"
              description="Bấm 'Chạy Hunt / Collect' ở góc trên để thu thập bằng chứng từ xa qua Velociraptor."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 text-left">Thời điểm</th>
                  <th className="px-4 py-2.5 text-left">Artifact</th>
                  <th className="px-4 py-2.5 text-left">Scope</th>
                  <th className="px-4 py-2.5 text-left">Trạng thái</th>
                  <th className="px-4 py-2.5 text-left">Velociraptor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {hunts.map((h) => (
                  <tr key={h.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 text-slate-600">{formatDateTime(h.created_at)}</td>
                    <td className="px-4 py-3 font-mono text-[12px] text-slate-900">{h.artifact}</td>
                    <td className="px-4 py-3">
                      {h.scope === "all" ? (
                        <Badge className="bg-slate-100 text-slate-700 ring-slate-600/20">Tất cả client</Badge>
                      ) : (
                        <Badge className="bg-violet-100 text-violet-700 ring-violet-600/20">1 máy</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {h.status === "completed" ? (
                        <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">OK</Badge>
                      ) : h.status === "error" ? (
                        <Badge className="bg-rose-100 text-rose-700 ring-rose-600/20">Lỗi</Badge>
                      ) : (
                        <Badge className="bg-amber-100 text-amber-700 ring-amber-600/20">Pending</Badge>
                      )}
                      {h.error && (
                        <p className="mt-1 text-[11px] text-rose-600" title={h.error}>
                          {h.error.slice(0, 60)}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {h.machine_id ? (
                        <Link
                          href={`/machines/${h.machine_id}`}
                          className="inline-flex items-center gap-1 font-mono text-[11px] text-brand-600 hover:underline"
                          title="Xem chi tiết tại /machines/[id]"
                        >
                          {h.hunt_id?.slice(0, 12) ?? "—"}…
                        </Link>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Modal tạo hunt */}
      <Modal
        open={showHuntModal}
        title="Chạy Hunt / Collect Artifact qua Velociraptor"
        onClose={() => setShowHuntModal(false)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setShowHuntModal(false)} disabled={huntSubmitting}>
              Hủy
            </Button>
            <Button onClick={submitHunt} disabled={huntSubmitting || !huntArtifact}>
              {huntSubmitting ? <Loader2 className="size-3.5 animate-spin" /> : <PlayCircle className="size-3.5" />}
              Gửi Velociraptor
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
            {huntError && <ErrorBanner message={huntError} />}

            <Field label="Artifact" hint="Chỉ chạy được artifact có trong allowlist (cấu hình ở /dfir/settings).">
              <Select value={huntArtifact} onChange={(e) => setHuntArtifact(e.target.value)}>
                {(config?.allowlist ?? []).map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </Select>
            </Field>

            <Field label="Phạm vi" hint="all = hunt trên toàn bộ client Velociraptor trả về; single = collect trên 1 máy đã link.">
              <Select value={huntScope} onChange={(e) => setHuntScope(e.target.value as "all" | "single")}>
                <option value="all">Tất cả client Velociraptor (hunt)</option>
                <option value="single">1 máy cụ thể (collect — cần chọn từ trang máy)</option>
              </Select>
            </Field>

            {huntScope === "single" && (
              <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
                Collect trên 1 máy cụ thể nên dùng nút <strong>DFIR</strong> ngay tại trang chi tiết máy (chọn artifact + click).
                Modal này chỉ hỗ trợ <code className="rounded bg-amber-100 px-1 font-mono text-xs">scope=all</code>.
              </div>
            )}

            <Field label="Tên hunt (tùy chọn)">
              <Input
                value={huntName}
                onChange={(e) => setHuntName(e.target.value)}
                placeholder="VD: Thu thập thông tin client toàn cơ quan"
              />
            </Field>

            <Field label="Mô tả (tùy chọn)">
              <Textarea
                value={huntDescription}
                onChange={(e) => setHuntDescription(e.target.value)}
                rows={3}
                placeholder="Mục đích điều tra, scope, ai duyệt…"
              />
            </Field>

            <div className="rounded-md bg-slate-50 p-3 text-xs leading-relaxed text-slate-600 ring-1 ring-inset ring-slate-200">
              <HardDriveDownload className="mr-1 inline size-3 align-text-top" />
              Kết quả lưu trên Velociraptor Server (notebook / collected flows). Portal chỉ deep-link sang GUI — không cache payload.
            </div>
          </div>
      </Modal>

      <ConfirmDialog
        open={confirmSync}
        title="Sync hostname ↔ Velociraptor client_id"
        message="Thao tác này gọi Velociraptor API ngay lập tức (không đợi 5 phút). Velociraptor có rate-limit nhẹ ở fleet lớn — đợi kết quả."
        confirmLabel="Đồng bộ ngay"
        onClose={() => setConfirmSync(false)}
        onConfirm={() => void handleSync()}
      />
    </div>
  );
}
