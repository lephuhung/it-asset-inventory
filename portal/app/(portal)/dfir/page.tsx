"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  ExternalLink,
  FileUp,
  HardDriveDownload,
  Loader2,
  Pencil,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldAlert,
  Siren,
  Trash2,
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
import type {
  DfirHunt,
  VelociraptorAlert,
  VelociraptorArtifact,
  VelociraptorArtifactDetail,
  VelociraptorArtifactSyncResult,
  VelociraptorConfig,
  VelociraptorLink,
} from "@/lib/types";
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

  // Custom artifacts (chỉ Super Admin — endpoint yêu cầu super_admin)
  const [artifacts, setArtifacts] = useState<VelociraptorArtifact[]>([]);
  const [showArtifactModal, setShowArtifactModal] = useState(false);
  const [artifactYaml, setArtifactYaml] = useState("");
  const [artifactPlatforms, setArtifactPlatforms] = useState<Array<"windows" | "linux" | "macos">>(["windows"]);
  const [artifactPriority, setArtifactPriority] = useState(100);
  const [artifactSubmitting, setArtifactSubmitting] = useState(false);

  // Sync / Edit / Delete artifact state
  const [syncingArtifacts, setSyncingArtifacts] = useState(false);
  const [editingArtifact, setEditingArtifact] = useState<VelociraptorArtifact | null>(null);
  const [editYaml, setEditYaml] = useState("");
  const [editPlatforms, setEditPlatforms] = useState<Array<"windows" | "linux" | "macos">>(["windows"]);
  const [editPriority, setEditPriority] = useState(100);
  const [editEnabled, setEditEnabled] = useState(true);
  const [editLoading, setEditLoading] = useState(false);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [deletingArtifact, setDeletingArtifact] = useState<VelociraptorArtifact | null>(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);
  const [deleteForce, setDeleteForce] = useState(false);

  const load = useCallback(async () => {
    try {
      const [cfg, lk, hs, al, ar] = await Promise.all([
        api.get<VelociraptorConfig>("/admin/velociraptor/config"),
        api.get<VelociraptorLink[]>("/admin/velociraptor/links"),
        api.get<DfirHunt[]>("/admin/velociraptor/hunts", { limit: 20 }),
        api.get<VelociraptorAlert[]>("/admin/velociraptor/alerts", { limit: 10 }),
        // Endpoint artifacts yêu cầu super_admin — non-admin nhận [] để không phá Promise.all
        isSuperAdmin
          ? api.get<VelociraptorArtifact[]>("/admin/velociraptor/artifacts")
          : Promise.resolve([]),
      ]);
      setConfig(cfg);
      setLinks(lk);
      setHunts(hs);
      setAlerts(al);
      setArtifacts(ar);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được dữ liệu DFIR");
    } finally {
      setLoading(false);
    }
  }, [isSuperAdmin]);

  const submitArtifact = async () => {
    if (!artifactYaml.trim()) {
      setHuntError("Dán YAML artifact definition trước khi nạp");
      return;
    }
    setArtifactSubmitting(true);
    setHuntError(null);
    setHuntSuccess(null);
    try {
      const res = await api.post<VelociraptorArtifact>("/admin/velociraptor/artifacts", {
        definition_yaml: artifactYaml,
        supported_platforms: artifactPlatforms,
        selection_priority: artifactPriority,
      });
      setHuntSuccess(
        res.on_server
          ? `Đã nạp ${res.name} lên Velociraptor (sha256 ${res.sha256.slice(0, 12)}…).`
          : `Đã lưu ${res.name} nhưng chưa xác nhận được trên server — kiểm tra lại.`,
      );
      setShowArtifactModal(false);
      setArtifactYaml("");
      setArtifactPlatforms(["windows"]);
      setArtifactPriority(100);
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : "Nạp artifact thất bại");
    } finally {
      setArtifactSubmitting(false);
    }
  };

  const syncArtifactsFromServer = async () => {
    setSyncingArtifacts(true);
    setHuntError(null);
    setHuntSuccess(null);
    try {
      const res = await api.post<VelociraptorArtifactSyncResult>(
        "/admin/velociraptor/artifacts/sync-from-server",
      );
      setHuntSuccess(
        `Đồng bộ xong: Thêm mới ${res.imported}, cập nhật ${res.updated} (tổng ${res.total_on_server} artifact Custom.* trên server).`,
      );
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : "Đồng bộ từ Velociraptor thất bại");
    } finally {
      setSyncingArtifacts(false);
    }
  };

  const openEditModal = async (artifact: VelociraptorArtifact) => {
    setEditingArtifact(artifact);
    setEditPlatforms(artifact.supported_platforms as Array<"windows" | "linux" | "macos">);
    setEditPriority(artifact.selection_priority);
    setEditEnabled(artifact.enabled);
    setEditLoading(true);
    setHuntError(null);
    try {
      const detail = await api.get<VelociraptorArtifactDetail>(
        `/admin/velociraptor/artifacts/${encodeURIComponent(artifact.name)}`,
      );
      setEditYaml(detail.definition_yaml);
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : `Không tải được YAML của ${artifact.name}`);
      setEditingArtifact(null);
    } finally {
      setEditLoading(false);
    }
  };

  const submitEditArtifact = async () => {
    if (!editingArtifact) return;
    if (!editYaml.trim()) {
      setHuntError("Nội dung YAML không được để trống");
      return;
    }
    setEditSubmitting(true);
    setHuntError(null);
    try {
      await api.put<VelociraptorArtifactDetail>(
        `/admin/velociraptor/artifacts/${encodeURIComponent(editingArtifact.name)}`,
        {
          definition_yaml: editYaml,
          supported_platforms: editPlatforms,
          selection_priority: editPriority,
          enabled: editEnabled,
        },
      );
      setHuntSuccess(`Đã cập nhật thành công artifact ${editingArtifact.name}`);
      setEditingArtifact(null);
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : "Cập nhật artifact thất bại");
    } finally {
      setEditSubmitting(false);
    }
  };

  const toggleArtifactEnabled = async (artifact: VelociraptorArtifact) => {
    try {
      await api.put(`/admin/velociraptor/artifacts/${encodeURIComponent(artifact.name)}`, {
        enabled: !artifact.enabled,
      });
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : `Không thể cập nhật trạng thái của ${artifact.name}`);
    }
  };

  const confirmDeleteArtifact = async () => {
    if (!deletingArtifact) return;
    setDeleteSubmitting(true);
    setHuntError(null);
    try {
      await api.delete(
        `/admin/velociraptor/artifacts/${encodeURIComponent(deletingArtifact.name)}` +
          (deleteForce ? "?force=true" : ""),
      );
      setHuntSuccess(`Đã xóa artifact ${deletingArtifact.name}`);
      setDeletingArtifact(null);
      setDeleteForce(false);
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : `Xóa ${deletingArtifact.name} thất bại`);
    } finally {
      setDeleteSubmitting(false);
    }
  };

  const repushArtifact = async (name: string) => {
    setHuntError(null);
    setHuntSuccess(null);
    try {
      const res = await api.post<VelociraptorArtifact>(
        `/admin/velociraptor/artifacts/${encodeURIComponent(name)}/push`,
      );
      setHuntSuccess(`Đã push lại ${res.name} lên Velociraptor.`);
      await load();
    } catch (e) {
      setHuntError(e instanceof Error ? e.message : `Push lại ${name} thất bại`);
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  // Tự động đồng bộ hostname links và artifacts khi mở trang DFIR nếu Velociraptor đã kết nối (chỉ Super Admin)
  const autoSyncedRef = useRef(false);
  useEffect(() => {
    if (!config || autoSyncedRef.current || !isSuperAdmin) return;
    const isConfigured = config.enabled && (config.client_config_set || config.basic_auth_set);
    if (!isConfigured) return;

    autoSyncedRef.current = true;
    void (async () => {
      try {
        const syncPromises: Promise<unknown>[] = [
          api.post("/admin/velociraptor/sync"),
        ];
        if (isSuperAdmin) {
          syncPromises.push(api.post("/admin/velociraptor/artifacts/sync-from-server"));
        }
        await Promise.allSettled(syncPromises);
        // Refresh silently để hiển thị dữ liệu mới nhất
        const [lk, ar] = await Promise.all([
          api.get<VelociraptorLink[]>("/admin/velociraptor/links"),
          isSuperAdmin
            ? api.get<VelociraptorArtifact[]>("/admin/velociraptor/artifacts")
            : Promise.resolve([]),
        ]);
        setLinks(lk);
        if (isSuperAdmin) setArtifacts(ar);
      } catch (e) {
        console.warn("Auto-sync khi mở trang DFIR:", e);
      }
    })();
  }, [config, isSuperAdmin]);

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
            {isSuperAdmin && (
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

      {/* Custom artifacts — Super Admin nạp artifact mới lên Velociraptor */}
      {isSuperAdmin && (
        <Card title="Artifact tuỳ chỉnh (Custom.*)" className="overflow-hidden p-0">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <p className="text-xs leading-relaxed text-slate-500">
              Nạp artifact definition (YAML) lên Velociraptor server để mở rộng nguồn dữ liệu cho hunt/collect.
              Chỉ chấp nhận namespace <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">Custom.*</code>,
              không hỗ trợ section <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">tools:</code>. DeepAgent chỉ nhận artifact phù hợp nền tảng máy đích.
            </p>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void syncArtifactsFromServer()}
                disabled={!cfgOk || syncingArtifacts}
                title="Quét và tải các artifact Custom.* từ server Velociraptor về DB"
              >
                <RefreshCw className={`size-3.5 ${syncingArtifacts ? "animate-spin" : ""}`} />
                {syncingArtifacts ? "Đang đồng bộ…" : "Đồng bộ từ server"}
              </Button>
              <Button size="sm" onClick={() => setShowArtifactModal(true)} disabled={!cfgOk}>
                <FileUp className="size-3.5" /> Nạp artifact
              </Button>
            </div>
          </div>
          {artifacts.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<FileUp className="size-8" />}
                title="Chưa có artifact tuỳ chỉnh"
                description="Bấm 'Nạp artifact' để đẩy artifact YAML (namespace Custom.*) lên Velociraptor server, hoặc bấm 'Đồng bộ từ server' nếu đã tạo trên Velociraptor."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-4 py-2.5 text-left">Tên</th>
                    <th className="px-4 py-2.5 text-left">Type</th>
                    <th className="px-4 py-2.5 text-left">Nền tảng</th>
                    <th className="px-4 py-2.5 text-left">Ưu tiên</th>
                    <th className="px-4 py-2.5 text-left">Kích hoạt</th>
                    <th className="px-4 py-2.5 text-left">Trên server</th>
                    <th className="px-4 py-2.5 text-left">Push gần nhất</th>
                    <th className="px-4 py-2.5 text-left">Cập nhật</th>
                    <th className="px-4 py-2.5 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {artifacts.map((a) => (
                    <tr key={a.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-mono text-[12px] text-slate-900">{a.name}</td>
                      <td className="px-4 py-3">
                        <Badge className="bg-slate-100 text-slate-700 ring-slate-600/20">{a.artifact_type}</Badge>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {a.supported_platforms.map((platform) => (
                            <Badge key={platform} className="bg-sky-100 text-sky-700 ring-sky-600/20">
                              {platform === "macos" ? "macOS" : platform}
                            </Badge>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-700">{a.selection_priority}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => void toggleArtifactEnabled(a)}
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium transition-colors ${
                            a.enabled
                              ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
                              : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                          }`}
                          title={a.enabled ? "Bấm để tắt" : "Bấm để bật"}
                        >
                          {a.enabled ? "Bật" : "Tắt"}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        {a.on_server ? (
                          <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">Đã nạp</Badge>
                        ) : (
                          <Badge className="bg-amber-100 text-amber-700 ring-amber-600/20">Chưa thấy</Badge>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {a.last_push_status === "pushed" ? (
                          <span className="text-emerald-700">OK</span>
                        ) : a.last_push_status === "failed" ? (
                          <span className="text-rose-700" title={a.last_push_error ?? ""}>Lỗi — rê chuột xem chi tiết</span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[11px] text-slate-500">{timeAgo(a.updated_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => void openEditModal(a)}
                            className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-brand-600 px-1.5 py-1 rounded hover:bg-slate-100"
                            title="Sửa definition YAML & metadata"
                          >
                            <Pencil className="size-3" /> Sửa
                          </button>
                          <button
                            type="button"
                            onClick={() => void repushArtifact(a.name)}
                            className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline px-1.5 py-1"
                            title="Push lại definition lên Velociraptor"
                          >
                            Push lại
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setDeletingArtifact(a);
                              setDeleteForce(false);
                            }}
                            className="inline-flex items-center gap-1 text-xs font-medium text-rose-600 hover:text-rose-700 px-1.5 py-1 rounded hover:bg-rose-50"
                            title="Xóa artifact khỏi server và database"
                          >
                            <Trash2 className="size-3" /> Xóa
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

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

      {/* Modal nạp artifact */}
      <Modal
        open={showArtifactModal}
        title="Nạp artifact lên Velociraptor"
        onClose={() => setShowArtifactModal(false)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setShowArtifactModal(false)} disabled={artifactSubmitting}>
              Hủy
            </Button>
            <Button onClick={() => void submitArtifact()} disabled={artifactSubmitting || !artifactYaml.trim() || artifactPlatforms.length === 0}>
              {artifactSubmitting ? <Loader2 className="size-3.5 animate-spin" /> : <FileUp className="size-3.5" />}
              Nạp lên server
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <Field
            label="Artifact definition (YAML)"
            hint="Chỉ namespace Custom.*; tối đa 256KB; mọi sources entry phải có query/queries; không chấp nhận section tools:. Description trong YAML là thông tin LLM dùng để hiểu mục đích artifact."
          >
            <Textarea
              value={artifactYaml}
              onChange={(e) => setArtifactYaml(e.target.value)}
              rows={12}
              placeholder={"name: Custom.MyOrg.Pslist\ndescription: Danh sách tiến trình tuỳ chỉnh\ntype: CLIENT\nsources:\n  - query: SELECT * FROM pslist()"}
              className="font-mono text-xs"
            />
          </Field>
          <Field label="Nền tảng hỗ trợ" hint="Backend chỉ đưa artifact này cho DeepAgent khi máy đích thuộc nền tảng đã chọn.">
            <div className="flex gap-4">
              {(["windows", "linux", "macos"] as const).map((platform) => (
                <label key={platform} className="inline-flex items-center gap-1.5 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={artifactPlatforms.includes(platform)}
                    onChange={(e) => setArtifactPlatforms((current) => e.target.checked
                      ? [...current, platform]
                      : current.filter((item) => item !== platform))}
                  />
                  {platform === "macos" ? "macOS" : platform === "windows" ? "Windows" : "Linux"}
                </label>
              ))}
            </div>
          </Field>
          <Field label="Ưu tiên chọn catalog" hint="0–1000; số cao hơn được đưa vào catalog trước khi vượt giới hạn 20 artifact.">
            <input
              aria-label="Ưu tiên chọn catalog"
              type="number"
              min={0}
              max={1000}
              value={artifactPriority}
              onChange={(e) => setArtifactPriority(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))}
              className="w-28 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </Field>
          <div className="flex items-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline">
              <FileUp className="size-3.5" /> Hoặc nạp từ file .yaml
              <input
                type="file"
                accept=".yaml,.yml"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () => setArtifactYaml(String(reader.result ?? ""));
                  reader.readAsText(file);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
          {/^\s*type:\s*client_event\s*$/im.test(artifactYaml) && (
            <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
              <AlertTriangle className="mr-1 inline size-4 align-text-top" />
              Artifact loại <strong>CLIENT_EVENT</strong> thay đổi hành vi thu thập trên <em>toàn bộ</em> agent fleet ngay khi nạp. Chỉ dùng khi đã kiểm chứng truy vấn.
            </div>
          )}
        </div>
      </Modal>

      {/* Modal chỉnh sửa artifact */}
      <Modal
        open={!!editingArtifact}
        title={`Chỉnh sửa artifact: ${editingArtifact?.name ?? ""}`}
        onClose={() => setEditingArtifact(null)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setEditingArtifact(null)} disabled={editSubmitting}>
              Hủy
            </Button>
            <Button onClick={() => void submitEditArtifact()} disabled={editSubmitting || editLoading || !editYaml.trim() || editPlatforms.length === 0}>
              {editSubmitting ? <Loader2 className="size-3.5 animate-spin" /> : <Pencil className="size-3.5" />}
              Lưu thay đổi
            </Button>
          </div>
        }
      >
        {editLoading ? (
          <div className="flex flex-col items-center justify-center p-8 gap-2">
            <Spinner />
            <p className="text-xs text-slate-500">Đang tải nội dung YAML từ server…</p>
          </div>
        ) : (
          <div className="space-y-4">
            <Field
              label="Artifact definition (YAML)"
              hint={`Lưu ý: Không được đổi giá trị trường name (${editingArtifact?.name}) trong YAML. Mọi thay đổi sẽ được validate và push đè lên Velociraptor.`}
            >
              <Textarea
                value={editYaml}
                onChange={(e) => setEditYaml(e.target.value)}
                rows={12}
                className="font-mono text-xs"
              />
            </Field>
            <Field label="Nền tảng hỗ trợ" hint="DeepAgent chỉ gửi artifact này khi máy mục tiêu thuộc nền tảng phù hợp.">
              <div className="flex gap-4">
                {(["windows", "linux", "macos"] as const).map((platform) => (
                  <label key={platform} className="inline-flex items-center gap-1.5 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={editPlatforms.includes(platform)}
                      onChange={(e) => setEditPlatforms((current) => e.target.checked
                        ? [...current, platform]
                        : current.filter((item) => item !== platform))}
                    />
                    {platform === "macos" ? "macOS" : platform === "windows" ? "Windows" : "Linux"}
                  </label>
                ))}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Ưu tiên chọn catalog (0–1000)" hint="Số cao hơn được ưu tiên đưa vào catalog trước.">
                <input
                  aria-label="Ưu tiên chọn catalog"
                  type="number"
                  min={0}
                  max={1000}
                  value={editPriority}
                  onChange={(e) => setEditPriority(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))}
                  className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
              </Field>
              <Field label="Trạng thái kích hoạt" hint="Tắt để DeepAgent tạm thời không sử dụng artifact này.">
                <label className="mt-1.5 inline-flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editEnabled}
                    onChange={(e) => setEditEnabled(e.target.checked)}
                    className="size-4 rounded text-brand-600 focus:ring-brand-500"
                  />
                  <span>{editEnabled ? "Đang bật (Enabled)" : "Đang tắt (Disabled)"}</span>
                </label>
              </Field>
            </div>
            {/^\s*type:\s*client_event\s*$/im.test(editYaml) && (
              <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
                <AlertTriangle className="mr-1 inline size-4 align-text-top" />
                Artifact loại <strong>CLIENT_EVENT</strong> thay đổi hành vi thu thập trên <em>toàn bộ</em> agent fleet ngay khi nạp. Chỉ dùng khi đã kiểm chứng truy vấn.
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Modal xác nhận xóa artifact */}
      <Modal
        open={!!deletingArtifact}
        title="Xác nhận xóa artifact"
        onClose={() => setDeletingArtifact(null)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setDeletingArtifact(null)} disabled={deleteSubmitting}>
              Hủy
            </Button>
            <Button
              variant="danger"
              onClick={() => void confirmDeleteArtifact()}
              disabled={deleteSubmitting}
            >
              {deleteSubmitting ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
              Xác nhận xóa
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm text-slate-600">
          <p>
            Bạn có chắc chắn muốn xóa artifact <code className="font-mono font-bold text-rose-600">{deletingArtifact?.name}</code>?
          </p>
          <div className="rounded-md bg-rose-50 p-3 text-xs text-rose-800 ring-1 ring-inset ring-rose-200">
            <AlertTriangle className="mr-1 inline size-4 align-text-top text-rose-600" />
            Artifact sẽ bị xóa hoàn toàn khỏi <strong>Velociraptor Server</strong> và cơ sở dữ liệu. Thao tác này không thể hoàn tác.
          </div>
          <div className="pt-2 border-t border-slate-100">
            <label className="inline-flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
              <input
                type="checkbox"
                checked={deleteForce}
                onChange={(e) => setDeleteForce(e.target.checked)}
                className="size-3.5 rounded text-rose-600 focus:ring-rose-500"
              />
              <span>Buộc xóa trong DB nếu server Velociraptor không phản hồi (?force=true)</span>
            </label>
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
