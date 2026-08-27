"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Fingerprint,
  HardDrive,
  Monitor,
  Network,
  Package,
  RefreshCw,
  ShieldCheck,
  StickyNote,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type { MachineDetail, NetworkInterface } from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import {
  Badge,
  BoolSwitch,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  StatusDot,
} from "@/components/ui";
import {
  LIFECYCLE_META,
  MACHINE_STATUS_META,
  formatBytes,
  formatDateTime,
  timeAgo,
} from "@/lib/format";
import { EOL_STATUS_META, getWindowsEol } from "@/lib/eol";
import { MachineTimelineSection } from "@/components/machine-timeline";

/** "—" nếu rỗng; object → JSON. */
function kv(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** True nếu giá trị "rỗng" (null/undefined/chuỗi trống/"—") → ẩn dòng. */
function isEmptyValue(v: unknown): boolean {
  if (v === null || v === undefined) return true;
  if (typeof v === "string") return v.trim() === "" || v.trim() === "—";
  return false;
}

/** Tóm tắt một object info (mainboard/BIOS) theo nhãn — chỉ lấy field không rỗng, bỏ null. */
function infoSummary(value: unknown, labels: Record<string, string>): string {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "object") return kv(value);
  const parts: string[] = [];
  for (const [key, label] of Object.entries(labels)) {
    const v = (value as Record<string, unknown>)[key];
    const text = v === null || v === undefined || v === "" ? "" : String(v).trim();
    if (text) parts.push(label ? `${label} ${text}` : text);
  }
  return parts.length > 0 ? parts.join(" · ") : "—";
}

const MAINBOARD_LABELS: Record<string, string> = {
  manufacturer: "NSX:",
  product: "Model:",
  serial: "S/N:",
  version: "Rev:",
};
const BIOS_LABELS: Record<string, string> = {
  vendor: "Hãng:",
  version: "Phiên bản:",
  release_date: "Ngày phát hành:",
  smbios_version: "SMBIOS:",
};

/** Cổng đang mở — gọn theo dạng chip, có nút bung/thu khi danh sách dài.
 *  Mỗi chip chỉ hiện port + protocol; địa chỉ lắng nghe có ở tooltip khi hover.
 *  Chip listen trên 0.0.0.0 / :: / * (mọi interface → public) tô amber cảnh báo. */
function CompactPortList({ ports }: { ports: Array<Record<string, unknown>> }) {
  const [expanded, setExpanded] = useState(false);
  const PREVIEW = 20;
  const sorted = useMemo(
    () => [...ports].sort((a, b) => Number(a.port ?? 0) - Number(b.port ?? 0)),
    [ports],
  );
  const visible = expanded ? sorted : sorted.slice(0, PREVIEW);
  const remaining = sorted.length - PREVIEW;

  return (
    <div className="py-2 text-sm">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-slate-500">Cổng đang mở ({sorted.length})</span>
        {remaining > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] font-medium text-brand-600 hover:underline"
          >
            {expanded ? "Thu gọn" : `Xem tất cả (${sorted.length})`}
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {visible.map((p, i) => {
          const addr = String(p.address ?? "").trim();
          const port = String(p.port ?? "").trim() || "—";
          const isPublic = addr === "0.0.0.0" || addr === "::" || addr === "*";
          return (
            <span
              key={i}
              className={
                "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] " +
                (isPublic
                  ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200"
                  : "bg-slate-100 text-slate-700")
              }
              title={`${addr || "?"}:${port} (${kv(p.protocol)})`}
            >
              <span className="font-semibold">{port}</span>
              <span
                className={
                  "text-[10px] uppercase " + (isPublic ? "text-amber-600" : "text-slate-400")
                }
              >
                {kv(p.protocol)}
              </span>
            </span>
          );
        })}
        {!expanded && remaining > 0 && (
          <span className="inline-flex items-center rounded bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-400">
            +{remaining}
          </span>
        )}
      </div>
    </div>
  );
}

/** Khởi động cùng Windows — 1 dòng/item (name · location · command-truncated),
 *  gom theo location để dễ quét (HKLM\Run, HKCU\Run, Startup folder…).
 *  Bung/thu khi > 5 chương trình. */
function CompactStartupList({ programs }: { programs: Array<Record<string, unknown>> }) {
  const [expanded, setExpanded] = useState(false);
  const PREVIEW = 5;
  const sorted = useMemo(
    () =>
      [...programs].sort((a, b) => {
        const locCmp = String(a.location ?? "").localeCompare(String(b.location ?? ""));
        return locCmp !== 0
          ? locCmp
          : String(a.name ?? "").localeCompare(String(b.name ?? ""));
      }),
    [programs],
  );
  const visible = expanded ? sorted : sorted.slice(0, PREVIEW);
  const remaining = sorted.length - PREVIEW;

  return (
    <div className="py-2 text-sm">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-slate-500">Khởi động cùng Windows ({sorted.length})</span>
        {remaining > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] font-medium text-brand-600 hover:underline"
          >
            {expanded ? "Thu gọn" : `Xem tất cả (${sorted.length})`}
          </button>
        )}
      </div>
      <ul className="space-y-0.5">
        {visible.map((p, i) => (
          <li
            key={i}
            className="flex items-center gap-1.5 rounded bg-slate-50 px-2 py-1 text-xs"
          >
            <span
              className="shrink-0 max-w-[40%] truncate font-medium text-slate-700"
              title={kv(p.name)}
            >
              {kv(p.name)}
            </span>
            <span className="shrink-0 truncate rounded bg-slate-200 px-1 py-px text-[10px] uppercase text-slate-500">
              {kv(p.location)}
            </span>
            <span
              className="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-400"
              title={kv(p.command)}
            >
              {kv(p.command)}
            </span>
          </li>
        ))}
      </ul>
      {!expanded && remaining > 0 && (
        <p className="mt-1 text-[11px] text-slate-400">+{remaining} chương trình khác</p>
      )}
    </div>
  );
}

/** Phần mềm đã cài — gọn, có nút bung/thu khi danh sách dài.
 *  - Mặc định hiện 10 dòng phẳng, không scroll.
 *  - Khi bấm "Xem tất cả" → list `flex-1 min-h-0 overflow-y-auto` lấp đầy body Card
 *    (Card được truyền `bodyClass="flex flex-col min-h-0 flex-1"`), khớp chiều cao
 *    với card "Trạng thái bảo mật" bên trái trong cùng grid row → không khoảng trắng thừa.
 *    Nội dung dài hơn khung thì scroll trong list. */
function CompactSoftwareList({ software }: { software: Array<Record<string, unknown>> }) {
  const [expanded, setExpanded] = useState(false);
  const PREVIEW = 10;
  const sorted = useMemo(
    () =>
      [...software].sort((a, b) =>
        String(a.display_name ?? a.name ?? "").localeCompare(
          String(b.display_name ?? b.name ?? ""),
        ),
      ),
    [software],
  );
  const visible = expanded ? sorted : sorted.slice(0, PREVIEW);
  const remaining = sorted.length - PREVIEW;

  return (
    <>
      <p className="mb-2 text-xs text-slate-400">
        {sorted.length} phần mềm — phát hiện phần mềm không phép / không bản quyền.
        {remaining > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="ml-2 text-[11px] font-medium text-brand-600 hover:underline"
          >
            {expanded ? "Thu gọn" : `Xem tất cả (${sorted.length})`}
          </button>
        )}
      </p>
      <div
        className={
          expanded
            ? "flex-1 min-h-0 overflow-y-auto divide-y divide-slate-50"
            : "divide-y divide-slate-50"
        }
      >
        {visible.map((s, i) => (
          <div key={i} className="flex items-center justify-between gap-3 py-1.5 text-sm">
            <span className="flex min-w-0 items-center gap-1.5 text-slate-700">
              <Package className="size-3.5 shrink-0 text-slate-400" />
              <span className="truncate">{kv(s.display_name ?? s.name ?? "(không có tên)")}</span>
            </span>
            <span className="shrink-0 text-xs text-slate-400">{kv(s.version)}</span>
          </div>
        ))}
      </div>
      {!expanded && remaining > 0 && (
        <p className="mt-1 text-[11px] text-slate-400">+{remaining} phần mềm khác</p>
      )}
    </>
  );
}

/** Dòng thông tin — TỰ ẨN khi không có dữ liệu (không hiển thị dòng "—" thừa). */
function SpecRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (isEmptyValue(value)) return null;
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-50 py-2 text-sm last:border-0">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-slate-800">{value}</span>
    </div>
  );
}

/** Dòng boolean — hiển thị công tắc + nhãn trạng thái; ẩn khi null/undefined. */
function BoolRow({
  label,
  on,
  onLabel = "Bật",
  offLabel = "Tắt",
  warnWhenOn = false,
}: {
  label: string;
  on: boolean | null | undefined;
  onLabel?: string;
  offLabel?: string;
  warnWhenOn?: boolean;
}) {
  if (on === null || on === undefined) return null;
  const textClass = on
    ? warnWhenOn
      ? "text-rose-600"
      : "text-emerald-700"
    : "text-slate-400";
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-50 py-2 text-sm last:border-0">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="flex items-center gap-2">
        <span className={`text-xs font-medium ${textClass}`}>{on ? onLabel : offLabel}</span>
        <BoolSwitch on={Boolean(on)} label={`${label}: ${on ? onLabel : offLabel}`} />
      </span>
    </div>
  );
}

export default function MachineDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { user } = useAuth();

  const [machine, setMachine] = useState<MachineDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [lifecycle, setLifecycle] = useState<string>("");
  const [note, setNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [adminOpen, setAdminOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const m = await api.get<MachineDetail>(`/machines/${id}`);
      setMachine(m);
      setLifecycle(m.lifecycle);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được chi tiết máy");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const isAdmin = user?.role === "super_admin" || user?.role === "org_admin" || user?.role === "admin_global" || user?.role === "admin_org";

  const runAction = async (action: string, body?: unknown) => {
    if (!machine) return;
    setActionBusy(action);
    setActionError(null);
    try {
      await api.post(`/machines/${machine.id}/${action}`, body ?? {});
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Thao tác thất bại");
    } finally {
      setActionBusy(null);
    }
  };

  const saveLifecycle = async () => {
    if (!machine || !lifecycle) return;
    setActionBusy("lifecycle");
    setActionError(null);
    try {
      await api.patch(`/machines/${machine.id}/lifecycle`, {
        lifecycle,
        note: note || null,
      });
      setNote("");
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Cập nhật vòng đời thất bại");
    } finally {
      setActionBusy(null);
    }
  };

  if (loading && !machine) return <Spinner label="Đang tải chi tiết máy…" />;
  if (error)
    return <ErrorBanner message={error} onRetry={() => void load()} />;
  if (!machine) return <EmptyState icon={<Monitor className="size-10" />} title="Máy không tồn tại" />;

  const meta = MACHINE_STATUS_META[machine.status];
  const life = LIFECYCLE_META[machine.lifecycle] ?? { label: machine.lifecycle, badge: "bg-slate-100 text-slate-500 ring-slate-500/20" };
  const spec = machine.latest_spec;
  const eol = spec ? getWindowsEol(spec.os_name, spec.os_build) : null;
  const disks = (spec?.disks ?? []) as Array<Record<string, unknown>>;
  const network = (spec?.network ?? []) as NetworkInterface[];
  const software = (spec?.installed_software ?? []) as Array<Record<string, unknown>>;
  const security = spec?.security;

  const antivirus = (security?.antivirus ?? []) as Array<Record<string, unknown>>;
  const avLabel =
    antivirus.length > 0
      ? antivirus
          .map((a) => {
            const name = String(a.displayName ?? a.name ?? "").trim();
            const status =
              a.upToDate === true
                ? "cập nhật"
                : a.enabled === true
                  ? "bật"
                  : a.enabled === false
                    ? "tắt"
                    : typeof a.status === "string"
                      ? a.status
                      : "";
            const label = `${name}${status ? ` (${status})` : ""}`.trim();
            return label || "Antivirus (thiếu tên)";
          })
          .join(", ")
      : null;

  const weakProtocols = security?.weak_protocols
    ? ([
        ["smbv1_disabled", "SMBv1"],
        ["tls10_disabled", "TLS 1.0"],
        ["tls11_disabled", "TLS 1.1"],
        ["ssl3_disabled", "SSL 3.0"],
      ] as const)
    : [];

  const hasSecurity =
    Boolean(security) &&
    (avLabel !== null ||
      !isEmptyValue(security?.windows_update_status) ||
      !isEmptyValue(security?.bitlocker) ||
      security?.rdp_enabled !== null ||
      security?.firewall_enabled !== null ||
      security?.uac_enabled !== null ||
      security?.secure_boot_enabled !== null ||
      security?.usb_storage_blocked !== null ||
      weakProtocols.length > 0 ||
      (security?.listening_ports?.length ?? 0) > 0 ||
      (security?.startup_programs?.length ?? 0) > 0 ||
      (security?.smarts?.length ?? 0) > 0);

  return (
    <div>
      <Link href="/machines" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="size-4" /> Về danh sách máy
      </Link>

      <PageHeader
        title={machine.hostname ?? "(chưa đặt tên)"}
        description={
          <span className="font-mono text-xs">{machine.machine_uuid}</span>
        }
        actions={
          <>
            <Badge className={meta.badge}>
              <StatusDot className={meta.dot} />
              {meta.label}
            </Badge>
            <Badge className={life.badge}>{life.label}</Badge>
            <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">
              {machine.is_vm ? "Máy ảo" : "Vật lý"}
            </Badge>
            {isAdmin && (
              <Button variant="secondary" size="sm" onClick={() => setAdminOpen(true)}>
                <Wrench className="size-3.5" /> Quản trị
              </Button>
            )}
          </>
        }
      />

      {eol && (
        <div className="mb-4">
          <Badge className={EOL_STATUS_META[eol.status].badge}>
            EOL: {eol.release} — {eol.note}
          </Badge>
        </div>
      )}

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* Timeline bật/tắt — đặt lên đầu trang theo yêu cầu */}
      <div className="mb-5">
        <MachineTimelineSection machineId={machine.id} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Cấu hình phần cứng" subtitle={spec ? `Snapshot lúc ${formatDateTime(spec.collected_at)}` : "Chưa có snapshot inventory"}>
          {!spec ? (
            <p className="text-sm text-slate-500">Agent chưa gửi inventory cho máy này.</p>
          ) : (
            <div className="divide-y divide-slate-100">
              <SpecRow label="Hệ điều hành" value={kv(spec.os_name)} />
              <SpecRow
                label="Phiên bản / Build"
                value={spec.os_version ? `${spec.os_version} (build ${kv(spec.os_build)})` : kv(spec.os_build)}
              />
              <SpecRow label="Kiến trúc" value={kv(spec.os_arch)} />
              <SpecRow
                label="CPU"
                value={
                  <span className="flex items-center justify-end gap-1">
                    <Cpu className="size-3.5 text-slate-400" />
                    {kv((spec.cpu as Record<string, unknown>)?.model ?? spec.cpu)}
                  </span>
                }
              />
              {spec.ram_gb != null && <SpecRow label="RAM" value={`${spec.ram_gb} GB`} />}
              <SpecRow label="GPU" value={kv((spec.gpu as Record<string, unknown>)?.model ?? spec.gpu)} />
              {spec.mainboard && <SpecRow label="Mainboard" value={infoSummary(spec.mainboard, MAINBOARD_LABELS)} />}
              {spec.bios && <SpecRow label="BIOS" value={infoSummary(spec.bios, BIOS_LABELS)} />}
              {disks.length > 0 && (
                <div className="py-2 text-sm">
                  <span className="text-slate-500">Ổ đĩa ({disks.length})</span>
                  <ul className="mt-1.5 space-y-1">
                    {disks.map((d, i) => (
                      <li key={i} className="flex items-center justify-between rounded-md bg-slate-50 px-2.5 py-1.5">
                        <span className="flex min-w-0 items-center gap-1.5 text-slate-700">
                          <HardDrive className="size-3.5 shrink-0 text-slate-400" />
                          <span className="truncate">{kv(d.model)}</span>
                        </span>
                        <span className="shrink-0 text-xs tabular-nums text-slate-500">
                          {formatBytes(Number(d.size_bytes ?? d.size ?? 0))}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card title="Mạng & người dùng">
          {network.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có dữ liệu mạng.</p>
          ) : (
            /* Danh sách dòng phân cách — không lồng khung bo góc bên trong card */
            <ul className="divide-y divide-slate-100">
              {network.map((n, i) => (
                <li key={i} className="py-2.5 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-slate-700">
                      <Network className="size-3.5 shrink-0 text-slate-400" />
                      <span className="truncate">{kv(n.name)}</span>
                    </span>
                    {n.is_dual_homed && (
                      <Badge className="bg-rose-50 text-rose-700 ring-rose-600/20">
                        <AlertTriangle className="size-3" /> Dual-homed
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-5 gap-y-0.5 pl-5 font-mono text-xs text-slate-500">
                    <span className="min-w-0 break-all">IP: {kv(n.ip)}</span>
                    <span className="min-w-0 break-all">MAC: {kv(n.mac)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {!isEmptyValue(spec?.logged_user) && (
            <div className="mt-3 border-t border-slate-100 pt-3">
              <SpecRow label="Người dùng đang đăng nhập" value={kv(spec?.logged_user)} />
            </div>
          )}

          <div className="mt-3 border-t border-slate-100 pt-3">
            {machine.assigned_user_name && (
              <SpecRow
                label="Cá nhân sở hữu"
                value={`${machine.assigned_user_name}${machine.phone_masked ? ` (ĐT: ${machine.phone_masked})` : ""}`}
              />
            )}
            <SpecRow label="Tổ chức" value={machine.org_name} />
            <SpecRow label="Enroll lúc" value={formatDateTime(machine.enrolled_at)} />
            <SpecRow label="Lần cuối online" value={timeAgo(machine.last_seen_at)} />
          </div>
        </Card>

        {hasSecurity && (
          <Card title="Trạng thái bảo mật" subtitle="Antivirus, Windows Update, cấu hình rủi ro (Phase 2)">
            <div className="divide-y divide-slate-100">
              {avLabel && (
                <SpecRow
                  label="Antivirus"
                  value={
                    <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                      <ShieldCheck className="size-3" /> {avLabel}
                    </Badge>
                  }
                />
              )}
              <SpecRow label="Windows Update" value={kv(security?.windows_update_status)} />
              <SpecRow label="BitLocker" value={kv(security?.bitlocker)} />
              <BoolRow label="RDP mở" on={security?.rdp_enabled} warnWhenOn onLabel="Đang bật" />
              <BoolRow label="Firewall" on={security?.firewall_enabled} />
              <BoolRow label="UAC" on={security?.uac_enabled} />
              <BoolRow label="Secure Boot" on={security?.secure_boot_enabled} />
              <BoolRow label="Chặn USB storage" on={security?.usb_storage_blocked} />

              {weakProtocols.length > 0 && (
                <div className="py-2 text-sm">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-slate-500">Giao thức yếu</span>
                    <span className="text-[11px] text-slate-400">
                      {weakProtocols.filter(([k]) => security?.weak_protocols?.[k] === true).length}/{weakProtocols.length} đã tắt
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {weakProtocols.map(([key, label]) => {
                      const disabled = security?.weak_protocols?.[key] === true;
                      return (
                        <span
                          key={key}
                          className={
                            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] " +
                            (disabled
                              ? "bg-emerald-50 text-emerald-700"
                              : "bg-amber-50 text-amber-700 ring-1 ring-amber-200")
                          }
                          title={`${label}: ${disabled ? "Đã tắt (an toàn)" : "Đang bật (rủi ro)"}`}
                        >
                          {disabled ? (
                            <CheckCircle2 className="size-3" />
                          ) : (
                            <AlertTriangle className="size-3" />
                          )}
                          <span className="font-medium">{label}</span>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {(security?.listening_ports ?? []).length > 0 && (
                <CompactPortList
                  ports={(security?.listening_ports ?? []) as Array<Record<string, unknown>>}
                />
              )}
              {(security?.startup_programs ?? []).length > 0 && (
                <CompactStartupList
                  programs={(security?.startup_programs ?? []) as Array<Record<string, unknown>>}
                />
              )}
              {(security?.smarts ?? []).length > 0 && (
                <div className="py-2 text-sm">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-slate-500">Sức khỏe ổ cứng ({security?.smarts?.length})</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(security?.smarts as Array<Record<string, unknown>>).map((s, i) => {
                      const model = kv(s.model ?? s.device ?? "Ổ đĩa");
                      const statusRaw = kv(s.status ?? s.health ?? "");
                      const status = statusRaw.toLowerCase();
                      const isFail = /(fail|error|critical|bad|dead)/.test(status);
                      const isWarn = /(warn|caution|degrad|risk)/.test(status);
                      const isGood = !isFail && !isWarn && /(good|ok|healthy|pass)/.test(status);
                      const cls = isFail
                        ? "bg-rose-50 text-rose-700 ring-1 ring-rose-200"
                        : isWarn
                          ? "bg-amber-50 text-amber-700"
                          : isGood
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-slate-100 text-slate-600";
                      const Icon = isFail || isWarn ? AlertTriangle : CheckCircle2;
                      return (
                        <span
                          key={i}
                          className={"inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] " + cls}
                          title={`${model} — ${statusRaw || "không rõ"}`}
                        >
                          <Icon className="size-3" />
                          <span className="max-w-[160px] truncate font-medium">{model}</span>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </Card>
        )}

        <Card
          title="Phần mềm đã cài"
          subtitle="Software inventory (Phase 2)"
          bodyClass="flex flex-col min-h-0 flex-1"
        >
          {software.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có dữ liệu phần mềm.</p>
          ) : (
            <CompactSoftwareList software={software as Array<Record<string, unknown>>} />
          )}
        </Card>

        <Card title="Fingerprint máy" subtitle="Định danh đa nguồn, dùng fuzzy-match khi enroll">
          <pre className="max-h-80 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">
            {JSON.stringify(machine.fingerprint ?? {}, null, 2)}
          </pre>
        </Card>

        <Card title="Ghi chú" subtitle="Vòng đời tài sản & ghi chú quản trị">
          <div className="flex items-start gap-2 text-sm text-slate-700">
            <StickyNote className="mt-0.5 size-4 shrink-0 text-slate-400" />
            {machine.note ? machine.note : "Chưa có ghi chú."}
          </div>
          <div className="mt-3 flex items-start gap-2 text-sm text-slate-700">
            <Fingerprint className="mt-0.5 size-4 shrink-0 text-slate-400" />
            <span>
              Fingerprint drift (đổi mainboard / ghost Win) sẽ hiện cảnh báo ở Phase 3 — admin duyệt
              trên màn chuyên dụng.
            </span>
          </div>
        </Card>
      </div>

      {isAdmin && (
        <Modal
          open={adminOpen}
          onClose={() => setAdminOpen(false)}
          title="Thao tác quản trị"
        >
          <div className="space-y-5">
            {/* Vòng đời tài sản (#18) */}
            <div>
              <Field label="Vòng đời tài sản">
                <div className="flex gap-2">
                  <Select value={lifecycle} onChange={(e) => setLifecycle(e.target.value)}>
                    <option value="new">Mới cài</option>
                    <option value="in_use">Đang dùng</option>
                    <option value="in_repair">Sửa chữa</option>
                    <option value="decommissioned">Thanh lý</option>
                  </Select>
                  <Button
                    variant="secondary"
                    loading={actionBusy === "lifecycle"}
                    onClick={() => void saveLifecycle()}
                    disabled={!lifecycle || lifecycle === machine.lifecycle}
                  >
                    Lưu
                  </Button>
                </div>
              </Field>
              <Field label="Ghi chú kèm (tùy chọn)" className="mt-2">
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Lý do thay đổi…" />
              </Field>
            </div>

            {/* Duyệt máy (#20) */}
            <div className="border-t border-slate-100 pt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">Duyệt máy (chờ approve)</p>
              {machine.status === "pending" ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" loading={actionBusy === "approve"} onClick={() => void runAction("approve")}>
                    <CheckCircle2 className="size-3.5" /> Duyệt máy
                  </Button>
                  <Button variant="danger" size="sm" loading={actionBusy === "reject"} onClick={() => void runAction("reject", { note: "Từ chối từ portal" })}>
                    Từ chối
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-slate-500">Máy không ở trạng thái chờ duyệt.</p>
              )}
            </div>

            {/* On-demand rescan (#23) */}
            <div className="border-t border-slate-100 pt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">On-demand rescan</p>
              <Button variant="secondary" size="sm" loading={actionBusy === "rescan"} onClick={() => void runAction("rescan")}>
                <RefreshCw className="size-3.5" /> Yêu cầu agent thu thập lại
              </Button>
              <p className="mt-1.5 text-xs leading-snug text-slate-400">
                Agent sẽ nhận cờ trong heartbeat kế tiếp và quét inventory ngay (không chờ chu kỳ).
              </p>
            </div>

            {actionError && <p className="text-sm text-rose-600">{actionError}</p>}
          </div>
        </Modal>
      )}

    </div>
  );
}
