"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  AlertTriangle,
  Brain,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Fingerprint,
  HardDrive,
  Loader2,
  Monitor,
  Network,
  Package,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  StickyNote,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type { DfirHunt, DfirInvestigation, MachineClassification, MachineDetail, NetworkInterface, Tag, VelociraptorClientMetadata, VelociraptorConfig, VelociraptorLink, VelociraptorLookup } from "@/lib/types";
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
  Textarea,
} from "@/components/ui";
import {
  LIFECYCLE_META,
  MACHINE_STATUS_META,
  classificationTag,
  formatBytes,
  formatDateTime,
  purposeTags,
  tagBadgeClass,
  timeAgo,
} from "@/lib/format";
import { EOL_STATUS_META, getWindowsEol } from "@/lib/eol";
import { MachineTimelineSection } from "@/components/machine-timeline";
import { VeloLogDrawer, VelociraptorLiveCard } from "@/components/velociraptor-live";
import { MachineInvestigationPanel } from "@/components/machine-investigation-panel";

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

/** Phần mềm đã cài — LUÔN hiện toàn bộ danh sách, list cuộn trong khung card.
 *  - Không còn nút "Xem tất cả / Thu gọn" — hiển thị hết mọi phần mềm.
 *  - Card được cha khóa chiều cao bằng chiều cao card "Trạng thái bảo mật"
 *    cùng hàng (xem `measureSoftwareCard`); list `flex-1 min-h-0 overflow-y-auto`
 *    lấp đầy body Card → nội dung dài hơn khung thì scroll trong list,
 *    card không kéo dài trang. */
function CompactSoftwareList({ software }: { software: Array<Record<string, unknown>> }) {
  const sorted = useMemo(
    () =>
      [...software].sort((a, b) =>
        String(a.display_name ?? a.name ?? "").localeCompare(
          String(b.display_name ?? b.name ?? ""),
        ),
      ),
    [software],
  );

  return (
    <>
      <p className="mb-2 text-xs text-slate-400">
        {sorted.length} phần mềm — phát hiện phần mềm không phép / không bản quyền.
      </p>
      <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-slate-50">
        {sorted.map((s, i) => (
          <div key={i} className="flex items-center justify-between gap-3 py-1.5 text-sm">
            <span className="flex min-w-0 items-center gap-1.5 text-slate-700">
              <Package className="size-3.5 shrink-0 text-slate-400" />
              <span className="truncate">{kv(s.display_name ?? s.name ?? "(không có tên)")}</span>
            </span>
            <span className="shrink-0 text-xs text-slate-400">{kv(s.version)}</span>
          </div>
        ))}
      </div>
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

  // ── Tag máy (phân loại + mục đích) ──
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [editClass, setEditClass] = useState<MachineClassification>("official");
  const [editPurpose, setEditPurpose] = useState<string[]>([]);
  const [tagBusy, setTagBusy] = useState(false);
  const [tagError, setTagError] = useState<string | null>(null);

  const classificationOptions = allTags.filter((t) => t.kind === "classification");
  const purposeOptions = allTags.filter((t) => t.kind === "purpose");

  // ── DFIR ──
  const [veloConfig, setVeloConfig] = useState<VelociraptorConfig | null>(null);
  const [veloLink, setVeloLink] = useState<VelociraptorLink | null>(null);
  const [veloBusy, setVeloBusy] = useState(false);
  const [veloError, setVeloError] = useState<string | null>(null);
  const [veloResult, setVeloResult] = useState<{ ok: boolean; message: string; url: string | null } | null>(null);
  // Live Velociraptor data (realtime từ Velociraptor Server API, không qua DB)
  const [veloMetadata, setVeloMetadata] = useState<VelociraptorClientMetadata | null>(null);
  const [veloLiveLoading, setVeloLiveLoading] = useState(false);
  const [veloLiveError, setVeloLiveError] = useState<string | null>(null);
  const [showCollectModal, setShowCollectModal] = useState(false);
  // LLM-DFIR investigation
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [llmInvestigationId, setLlmInvestigationId] = useState<string | null>(null);
  const [showInvestigationModal, setShowInvestigationModal] = useState(false);
  const [investigationInstructions, setInvestigationInstructions] = useState("");
  const [collectArtifact, setCollectArtifact] = useState("");
  // ── Panel log Velociraptor (trượt vào từ bên phải, đẩy nội dung sang trái) ──
  const [showVeloLog, setShowVeloLog] = useState(false);
  const [showInvestigationPanel, setShowInvestigationPanel] = useState(false);

  // ── Luôn khóa chiều cao card "Phần mềm đã cài" theo card "Trạng thái bảo mật" cùng hàng ──
  const securityCardRef = useRef<HTMLElement | null>(null);
  const softwareCardRef = useRef<HTMLElement | null>(null);
  const [softwareCardStyle, setSoftwareCardStyle] = useState<React.CSSProperties | undefined>(
    undefined,
  );

  /** Đo card "Trạng thái bảo mật" và khóa card phần mềm theo đúng chiều cao đó.
   *  List phần mềm luôn hiện đầy đủ nên NẾU đo trực tiếp, row height của grid
   *  sẽ bị list dài kéo giãn (card bảo mật cũng bị kéo theo) → đo sai. Vì vậy
   *  tạm đưa card phần mềm ra khỏi luồng grid (position:absolute) trong lúc đo
   *  để row height chỉ còn do card bảo mật quyết định → đo được chiều cao TỰ
   *  NHIÊN của nó, rồi khóa card phần mềm đúng chiều cao đó.
   *  Chỉ áp dụng khi 2 card nằm cùng hàng trong grid 2 cột (lg+); khi xếp chồng
   *  (màn hình nhỏ / không có card bảo mật) chỉ chặn chiều cao tối đa hợp lý. */
  const measureSoftwareCard = useCallback(() => {
    const sec = securityCardRef.current;
    const soft = softwareCardRef.current;
    if (!sec || !soft) {
      setSoftwareCardStyle({ maxHeight: "min(70vh, 640px)" });
      return;
    }
    const softTop = soft.getBoundingClientRect().top;
    const secTop = sec.getBoundingClientRect().top;
    if (Math.abs(secTop - softTop) > 4) {
      // Không cùng hàng (mobile xếp chồng) — chỉ chặn chiều cao tối đa
      setSoftwareCardStyle({ maxHeight: "min(70vh, 640px)" });
      return;
    }
    // Cùng hàng → đo chiều cao tự nhiên của card bảo mật (card phần mềm ngoài luồng)
    const prevPosition = soft.style.position;
    soft.style.position = "absolute";
    const secHeight = sec.getBoundingClientRect().height;
    soft.style.position = prevPosition;
    setSoftwareCardStyle({ height: secHeight });
  }, []);

  // Đo/khóa sau khi dữ liệu máy có (và mỗi lần tải lại) — chạy TRƯỚC khi paint
  // để không nháy layout phình to do list dài.
  const useIsomorphicLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;
  useIsomorphicLayoutEffect(() => {
    if ((machine?.latest_spec?.installed_software ?? []).length === 0) {
      setSoftwareCardStyle(undefined);
      return;
    }
    measureSoftwareCard();
  }, [measureSoftwareCard, machine]);

  // Re-đo khi cửa sổ đổi kích thước (debounce nhẹ — tránh reflow liên tục)
  useEffect(() => {
    if ((machine?.latest_spec?.installed_software ?? []).length === 0) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(() => measureSoftwareCard(), 120);
    };
    window.addEventListener("resize", onResize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [measureSoftwareCard, machine]);

  const load = useCallback(async () => {
    try {
      const m = await api.get<MachineDetail>(`/machines/${id}`);
      setMachine(m);
      setLifecycle(m.lifecycle);
      // Đồng bộ bộ chỉnh tag với tag hiện tại của máy
      const cls = classificationTag(m.tags);
      if (cls) setEditClass(cls.key as MachineClassification);
      setEditPurpose(purposeTags(m.tags).map((t) => t.key));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được chi tiết máy");
    } finally {
      setLoading(false);
    }
  }, [id]);

  // Toàn bộ tag (classification + purpose) — cho bộ chỉnh trong modal Quản trị
  useEffect(() => {
    api
      .get<Tag[]>("/tags")
      .then((list) => {
        setAllTags(Array.isArray(list) ? list : []);
        if (Array.isArray(list)) {
          const def = list.find((t) => t.kind === "classification" && t.key === "official");
          if (def) setEditClass((cur) => cur ?? "official");
        }
      })
      .catch(() => setAllTags([]));
  }, []);

  /** Lưu loại máy + tag mục đích (PUT /machines/{id}/tags — ghi audit). */
  const saveTags = async () => {
    if (!machine) return;
    setTagBusy(true);
    setTagError(null);
    try {
      const res = await api.put<{ tags: Tag[] }>(`/machines/${machine.id}/tags`, {
        classification: editClass,
        purpose: editPurpose,
      });
      setMachine((prev) => (prev ? { ...prev, tags: res.tags } : prev));
      setAdminOpen(false);
    } catch (e) {
      setTagError(e instanceof Error ? e.message : "Không lưu được tag");
    } finally {
      setTagBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  // On-demand lookup Velociraptor (NO background sync):
  // 1. Config từ DB (allowlist, server_url) — sync_state không còn
  // 2. Client_id lookup trực tiếp từ Velociraptor Server bằng hostname (không cache DB)
  const loadVelo = useCallback(async () => {
    setVeloConfig(null);
    setVeloLink(null);
    try {
      const cfg = await api.get<VelociraptorConfig>("/admin/velociraptor/config");
      setVeloConfig(cfg);
      if (cfg.allowlist.length > 0) setCollectArtifact((cur) => cur || cfg.allowlist[0]);
      // Lookup hostname → client_id qua Velociraptor API trực tiếp
      if (machine?.hostname && cfg.enabled) {
        const lookup = await api.get<VelociraptorLookup>(
          `/admin/velociraptor/lookup?hostname=${encodeURIComponent(machine.hostname)}`,
        );
        if (lookup.matched && lookup.client_id) {
          // Synthesize VelociraptorLink-like object từ lookup (không qua DB)
          setVeloLink({
            machine_id: id,
            client_id: lookup.client_id,
            hostname: lookup.hostname ?? machine.hostname,
            os_info: lookup.os_info,
            last_seen_at: null,
            synced_at: new Date().toISOString(),
          });
        }
      }
    } catch {
      // DFIR chưa cấu hình / unreachable — section hiện "chưa cấu hình"
    }
  }, [id, machine?.hostname]);

  // Load live Velociraptor data (metadata realtime) cho máy đã link
  const loadVeloLive = useCallback(async () => {
    if (!veloLink) {
      setVeloMetadata(null);
      return;
    }
    setVeloLiveLoading(true);
    setVeloLiveError(null);
    try {
      const meta = await api.get<VelociraptorClientMetadata>(
        `/admin/velociraptor/clients/${veloLink.client_id}/metadata`,
      );
      setVeloMetadata(meta);
    } catch (e) {
      setVeloLiveError(e instanceof Error ? e.message : "Không tải được dữ liệu Velociraptor");
      setVeloMetadata(null);
    } finally {
      setVeloLiveLoading(false);
    }
  }, [veloLink]);

  useEffect(() => {
    void loadVelo();
  }, [loadVelo]);

  // Load live data sau khi veloLink sẵn sàng (từ lần loadVelo đầu tiên)
  useEffect(() => {
    void loadVeloLive();
  }, [loadVeloLive]);

  // ESC đóng panel log Velociraptor
  useEffect(() => {
    if (!showVeloLog) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowVeloLog(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showVeloLog]);

  const isAdmin = user?.role === "super_admin" || user?.role === "org_admin" || user?.role === "admin_global" || user?.role === "admin_org";
  const isSuperAdmin = user?.role === "super_admin";

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

  /** Collect artifact qua Velociraptor trên máy này (1 client cụ thể). */
  const collectArtifactOnMachine = async () => {
    if (!machine || !veloLink || !collectArtifact) return;
    setVeloBusy(true);
    setVeloError(null);
    setVeloResult(null);
    try {
      const res = await api.post<DfirHunt>("/admin/velociraptor/hunt", {
        artifact: collectArtifact,
        scope: "single",
        machine_id: machine.id,
        notes: `Thu thập từ trang máy ${machine.hostname ?? machine.id}`,
      });
      setVeloResult({
        ok: true,
        message: `Đã gửi yêu cầu điều tra — flow_id ${res.hunt_id ?? res.id}. Xem kết quả ở GUI.`,
        url: res.velociraptor_url,
      });
      setShowCollectModal(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Collect thất bại";
      setVeloError(msg);
      setVeloResult({ ok: false, message: msg, url: null });
    } finally {
      setVeloBusy(false);
    }
  };

  /** Trigger LLM-DFIR investigation cho máy này.
   *  Tự động thu thập 10 artifact Velociraptor mặc định + gọi LLM phân tích.
   *  Background worker xử lý; chuyển trang sang chi tiết investigation.
   */
  const investigateWithAI = async () => {
    if (!machine) return;
    setLlmBusy(true);
    setLlmError(null);
    try {
      const inv = await api.post<DfirInvestigation>("/admin/llm-dfir/investigations", {
        machine_id: machine.id,
        artifacts: null, // dùng default
        custom_instructions: investigationInstructions.trim() || null,
      });
      setLlmInvestigationId(inv.id);
      // Chuyển trang sau khi tạo xong
      window.location.href = `/admin/llm-dfir/investigations/${inv.id}`;
    } catch (e) {
      setLlmError(e instanceof Error ? e.message : "Tạo investigation thất bại");
    } finally {
      setLlmBusy(false);
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
            {(() => {
              const cls = classificationTag(machine.tags);
              return cls ? (
                <Badge className={tagBadgeClass(cls)}>{cls.label}</Badge>
              ) : (
                <Badge className="bg-slate-100 text-slate-500 ring-slate-500/20">Chưa phân loại</Badge>
              );
            })()}
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

      {/* Ghi chú quản trị — hiện ngay dưới tên thiết bị như nội dung EOL */}
      {machine.note && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700">
          <StickyNote className="mt-0.5 size-4 shrink-0 text-slate-400" />
          <span className="min-w-0">{machine.note}</span>
        </div>
      )}

      {/* Tag mục đích — chip nhỏ dưới tên máy, không ảnh hưởng thống kê */}
      {purposeTags(machine.tags).length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          {purposeTags(machine.tags).map((t) => (
            <Badge key={t.key} className={tagBadgeClass(t)}>{t.label}</Badge>
          ))}
        </div>
      )}

      {eol && (
        <div className="mb-4">
          <Badge className={EOL_STATUS_META[eol.status].badge}>
            EOL: {eol.release} — {eol.note}
          </Badge>
        </div>
      )}

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* Heatmap 3/5 trái + Phân tích sự cố (DFIR) — Live data 2/5 phải (nếu máy đã link) */}
      {veloLink ? (
        <div className="mb-5 grid items-stretch gap-5 lg:grid-cols-5">
          <MachineTimelineSection machineId={machine.id} className="h-full lg:col-span-3" />
          <VelociraptorLiveCard
            className="h-full lg:col-span-2"
            metadata={veloMetadata}
            loading={veloLiveLoading}
            error={veloLiveError}
            active={Boolean(
              veloConfig?.enabled &&
                (veloConfig.basic_auth_set || veloConfig.client_config_set || veloConfig.api_token_set),
            )}
            result={veloResult}
            busy={veloBusy}
            canCollect={Boolean(
              isAdmin &&
                veloConfig?.enabled &&
                (veloConfig.basic_auth_set || veloConfig.client_config_set || veloConfig.api_token_set),
            )}
            guiUrl={
              veloConfig?.server_url
                ? `${veloConfig.server_url.replace(/\/$/, "")}/#/host/${veloLink.client_id}`
                : null
            }
            onRefresh={() => void loadVeloLive()}
            onOpenLogs={() => setShowVeloLog(true)}
            onShowHistory={() => setShowInvestigationPanel(true)}
            onInvestigateAI={() => setShowInvestigationModal(true)}
            llmBusy={llmBusy}
          />
        </div>
      ) : (
        <div className="mb-5">
          <MachineTimelineSection machineId={machine.id} />
        </div>
      )}

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

          {/* Fingerprint máy — định danh tĩnh (không đổi theo snapshot), gộp gọn tại đây */}
          <details className="group mt-1 text-sm">
            <summary className="flex cursor-pointer select-none items-center justify-between gap-2 text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <Fingerprint className="size-3.5 shrink-0 text-slate-400" />
                <span className="font-medium">Fingerprint máy</span>
              </span>
              <ChevronRight className="size-3.5 shrink-0 text-slate-400 transition-transform group-open:rotate-90" />
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2.5 font-mono text-[11px] leading-relaxed text-slate-600">
              {JSON.stringify(machine.fingerprint ?? {}, null, 2)}
            </pre>
            <p className="mt-1.5 text-[11px] leading-snug text-slate-400">
              Fingerprint drift (đổi mainboard / ghost Win) sẽ hiện cảnh báo ở Phase 3 — admin duyệt
              trên màn chuyên dụng.
            </p>
          </details>
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
          <Card
            title="Trạng thái bảo mật"
            subtitle="Antivirus, Windows Update, cấu hình rủi ro (Phase 2)"
            sectionRef={securityCardRef}
          >
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
          sectionRef={softwareCardRef}
          style={softwareCardStyle}
        >
          {software.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có dữ liệu phần mềm.</p>
          ) : (
            <CompactSoftwareList software={software as Array<Record<string, unknown>>} />
          )}
        </Card>

        {/* Velociraptor Live Data — card đã tách sang cột 2/5 cạnh heatmap (VelociraptorLiveCard) */}
      </div>

      {/* Modal: Collect Artifact qua hệ thống phân tích sự cố */}
      <Modal
        open={showCollectModal}
        onClose={() => setShowCollectModal(false)}
        title={`Thu thập bằng chứng từ xa — ${machine?.hostname ?? machine?.id ?? ""}`}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setShowCollectModal(false)} disabled={veloBusy}>
              Hủy
            </Button>
            <Button onClick={collectArtifactOnMachine} disabled={veloBusy || !collectArtifact}>
              {veloBusy ? <Loader2 className="size-3.5 animate-spin" /> : <PlayCircle className="size-3.5" />}
              Gửi yêu cầu điều tra
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {veloError && <ErrorBanner message={veloError} />}
          {llmError && (
            <div className="mb-2">
              <ErrorBanner message={`LLM-DFIR: ${llmError}`} onRetry={() => setLlmError(null)} />
            </div>
          )}

          <Field
            label="Artifact"
            hint="Chỉ chạy được artifact có trong allowlist (cấu hình ở /dfir/settings)."
          >
            <Select value={collectArtifact} onChange={(e) => setCollectArtifact(e.target.value)}>
              {(veloConfig?.allowlist ?? []).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>

          <div className="rounded-md bg-slate-50 p-3 text-xs leading-relaxed text-slate-600 ring-1 ring-inset ring-slate-200">
            <Search className="mr-1 inline size-3.5 align-text-top text-violet-600" />
            Hệ thống sẽ thu thập bằng chứng trên client_id{" "}
            <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">
              {veloLink?.client_id?.slice(0, 16)}…
            </code>
            . Kết quả lưu kết quả trên server — click <em>Mở GUI</em> sau khi gửi để xem notebook.
          </div>
        </div>
      </Modal>

      {isAdmin && (
        <Modal
          open={adminOpen}
          onClose={() => setAdminOpen(false)}
          title="Thao tác quản trị"
        >
          <div className="space-y-5">
            {/* Phân loại máy + tag mục đích (#tag) */}
            <div>
              <Field
                label="Loại máy"
                required
                hint="Máy cá nhân không tính vào máy công vụ; máy BMNN là máy công vụ — quyết định số liệu thống kê"
              >
                <div className="flex flex-wrap gap-2">
                  {classificationOptions.map((t) => (
                    <label
                      key={t.key}
                      className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
                        editClass === t.key
                          ? "border-brand-600 bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-600"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <input
                        type="radio"
                        name="edit-classification"
                        value={t.key}
                        checked={editClass === t.key}
                        onChange={() => setEditClass(t.key as MachineClassification)}
                        className="size-3.5 accent-brand-600"
                      />
                      {t.label}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="Mục đích sử dụng (tag linh hoạt — kind)" className="mt-3">
                {purposeOptions.length === 0 ? (
                  <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-500 ring-1 ring-inset ring-slate-200">
                    Chưa có tag mục đích nào. Super Admin tạo tag (kind) tại{" "}
                    <Link href="/tags" className="font-medium text-brand-600 hover:underline">
                      Quản lý tag
                    </Link>{" "}
                    — sau đó quay lại đây gán cho máy.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {purposeOptions.map((t) => {
                      const on = editPurpose.includes(t.key);
                      return (
                        <label
                          key={t.key}
                          className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
                            on
                              ? "border-brand-600 bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-600"
                              : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() =>
                              setEditPurpose((prev) =>
                                prev.includes(t.key) ? prev.filter((k) => k !== t.key) : [...prev, t.key],
                              )
                            }
                            className="size-3.5 rounded accent-brand-600"
                          />
                          {t.label}
                        </label>
                      );
                    })}
                  </div>
                )}
              </Field>
              {tagError && <p className="mt-2 text-sm text-rose-600">{tagError}</p>}
              <div className="mt-3 flex justify-end">
                <Button size="sm" loading={tagBusy} onClick={() => void saveTags()} disabled={classificationOptions.length === 0}>
                  Lưu phân loại & tag
                </Button>
              </div>
            </div>

            {/* Vòng đời tài sản (#18) */}
            <div className="border-t border-slate-100 pt-4">
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

      {/* Panel log Velociraptor — overlay trượt từ phải sang trái.
          Trong panel hiển thị: thông tin realtime + Top 10 sự kiện DFIR
          (Prefetch/Netstat/Pslist) — để Admin đánh giá an toàn thiết bị. */}
      <VeloLogDrawer
        open={showVeloLog}
        onClose={() => setShowVeloLog(false)}
        metadata={veloMetadata}
        loading={veloLiveLoading}
        error={veloLiveError}
        onRefresh={() => void loadVeloLive()}
        guiUrl={
          veloConfig?.server_url && veloLink
            ? `${veloConfig.server_url.replace(/\/$/, "")}/#/host/${veloLink.client_id}`
            : null
        }
        clientId={veloLink?.client_id ?? null}
        allowlist={veloConfig?.allowlist ?? []}
      />

      {/* Panel lịch sử investigations — mở từ nút "Lịch sử điều tra" trên card Velociraptor */}
      <MachineInvestigationPanel
        machineId={machine.id}
        machineHostname={machine.hostname}
        open={showInvestigationPanel}
        onClose={() => setShowInvestigationPanel(false)}
      />

      {showInvestigationModal && (
        <Modal
          open={showInvestigationModal}
          title="Khởi tạo điều tra AI"
          onClose={() => setShowInvestigationModal(false)}
        >
          <div className="space-y-4">
            <p className="text-sm text-slate-600">Điều tra máy <strong>{machine.hostname}</strong> qua LangGraph và Velociraptor. Agent dùng policy cố định; chỉ thời gian hiện tại và dấu hiệu dưới đây được đưa vào cuộc điều tra.</p>
            <Field label="Dấu hiệu nghi ngờ / yêu cầu điều tra">
              <Textarea value={investigationInstructions} onChange={(e) => setInvestigationInstructions(e.target.value)} placeholder="Ví dụ: nghi ngờ PowerShell thực thi bất thường trong 24 giờ gần đây" rows={5} />
            </Field>
            {llmError && <p className="text-sm text-rose-600">{llmError}</p>}
            <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setShowInvestigationModal(false)}>Hủy</Button><Button loading={llmBusy} onClick={() => void investigateWithAI()}>Bắt đầu điều tra</Button></div>
          </div>
        </Modal>
      )}

    </div>
  );
}
