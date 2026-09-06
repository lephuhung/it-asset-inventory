"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Plus, Trash2, Building2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  DeviceType,
  MachineListItem,
  Organization,
  SystemProfileDetail,
  SystemProfileDevicePayload,
  SystemProfileDevice,
  SystemProfileReviewPayload,
  ProfileRequirement,
  SystemProfileApplication,
  SystemProfileIpRange,
  SystemProfileParty,
  PartyRole,
  ItContact,
} from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
  Textarea,
  EmptyState,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import { MermaidDiagram } from "@/components/mermaid-diagram";
import { generateDevicesMermaid, labelFor, validateDevicesMermaid } from "@/lib/system-profile-diagram";
import { LevelBadge, StatusBadge } from "@/components/system-profile-badges";

type Tab = "info" | "history" | "devices" | "machines" | "contacts" | "requirements" | "applications" | "ip-ranges" | "diagram";

/** Icon + màu hiển thị từng loại sự kiện trên timeline lịch sử. */
const EVENT_META: Record<string, { icon: string; cls: string }> = {
  created: { icon: "📝", cls: "bg-brand-50 ring-brand-600/20" },
  updated: { icon: "✏️", cls: "bg-slate-100 ring-slate-500/20" },
  level_changed: { icon: "🎚️", cls: "bg-indigo-50 ring-indigo-600/20" },
  document_updated: { icon: "📄", cls: "bg-slate-100 ring-slate-500/20" },
  submitted: { icon: "📤", cls: "bg-amber-50 ring-amber-600/20" },
  approved: { icon: "✅", cls: "bg-emerald-50 ring-emerald-600/20" },
  rejected: { icon: "❌", cls: "bg-rose-50 ring-rose-600/20" },
  implementation_reported: { icon: "🚀", cls: "bg-blue-50 ring-blue-600/20" },
  fulfilled: { icon: "🏁", cls: "bg-teal-50 ring-teal-600/20" },
  device_added: { icon: "➕", cls: "bg-slate-100 ring-slate-500/20" },
  device_updated: { icon: "🔧", cls: "bg-slate-100 ring-slate-500/20" },
  device_removed: { icon: "➖", cls: "bg-slate-100 ring-slate-500/20" },
  machine_attached: { icon: "💻", cls: "bg-slate-100 ring-slate-500/20" },
  machine_detached: { icon: "🔌", cls: "bg-slate-100 ring-slate-500/20" },
  requirement_requested: { icon: "🛡️", cls: "bg-amber-50 ring-amber-600/20" },
  requirement_verified: { icon: "🛡️", cls: "bg-emerald-50 ring-emerald-600/20" },
  requirement_rejected: { icon: "🛡️", cls: "bg-rose-50 ring-rose-600/20" },
  contact_attached: { icon: "🧑‍💼", cls: "bg-slate-100 ring-slate-500/20" },
  contact_detached: { icon: "🧑‍💼", cls: "bg-slate-100 ring-slate-500/20" },
  party_added: { icon: "🏢", cls: "bg-slate-100 ring-slate-500/20" },
  party_updated: { icon: "🏢", cls: "bg-slate-100 ring-slate-500/20" },
  party_removed: { icon: "🏢", cls: "bg-slate-100 ring-slate-500/20" },
  application_added: { icon: "🧩", cls: "bg-slate-100 ring-slate-500/20" },
  application_updated: { icon: "🧩", cls: "bg-slate-100 ring-slate-500/20" },
  application_removed: { icon: "🧩", cls: "bg-slate-100 ring-slate-500/20" },
  ip_range_added: { icon: "🌐", cls: "bg-slate-100 ring-slate-500/20" },
  ip_range_updated: { icon: "🌐", cls: "bg-slate-100 ring-slate-500/20" },
  ip_range_removed: { icon: "🌐", cls: "bg-slate-100 ring-slate-500/20" },
};

const AUDIENCE_LABELS: Record<string, string> = {
  internal: "Nội bộ",
  citizens: "Người dân",
  businesses: "Doanh nghiệp",
  mixed: "Kết hợp (nội bộ + người dân/doanh nghiệp)",
};

const REQ_STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: "Chưa đáp ứng", cls: "bg-slate-100 text-slate-600 ring-slate-500/20" },
  requested: { label: "Chờ thẩm định", cls: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  verified: { label: "Đã thẩm định đạt", cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  rejected: { label: "Thẩm định không đạt", cls: "bg-rose-50 text-rose-700 ring-rose-600/20" },
};

function ReqStatusBadge({ status }: { status: string }) {
  const meta = REQ_STATUS_META[status] ?? REQ_STATUS_META.pending;
  return <Badge className={meta.cls}>{meta.label}</Badge>;
}

export default function SystemProfileDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";
  const isAdmin = isSuperAdmin || user?.role === "org_admin" || user?.role === "admin_org";

  const [profile, setProfile] = useState<SystemProfileDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("info");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [reviewModal, setReviewModal] = useState<"approve" | "reject" | null>(null);
  const [decisionNumber, setDecisionNumber] = useState("");
  const [decisionAgency, setDecisionAgency] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  // Sửa tên & mô tả — modal thay window.prompt (native prompt là anti-pattern)
  const [renameModal, setRenameModal] = useState(false);
  const [rName, setRName] = useState("");
  const [rDesc, setRDesc] = useState("");

  // Số văn bản đề nghị + ngày văn bản + tên chủ quản (bổ sung sau được)
  const [docModal, setDocModal] = useState(false);
  const [dcNumber, setDcNumber] = useState("");
  const [dcDate, setDcDate] = useState("");
  const [dcManaged, setDcManaged] = useState("");

  // Thiết bị — form modal
  const [deviceModal, setDeviceModal] = useState<"new" | SystemProfileDevice | null>(null);
  const [dName, setDName] = useState("");
  const [dCode, setDCode] = useState("");
  const [dTag, setDTag] = useState("");
  const [dType, setDType] = useState<string>("firewall");
  const [dIp, setDIp] = useState("");
  const [dModel, setDModel] = useState("");
  const [dLocation, setDLocation] = useState("");
  const [dPurpose, setDPurpose] = useState("");
  const [dSort, setDSort] = useState(0);

  // Catalog loại thiết bị động (Super Admin quản trị ở trang cấu hình)
  const [devTypes, setDevTypes] = useState<DeviceType[]>([]);

  // Gắn máy
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [machinePick, setMachinePick] = useState("");

  // Gắn chuyên trách CNTT / tổ chức vận hành (từ danh bạ đơn vị)
  const [contactsDir, setContactsDir] = useState<ItContact[]>([]);
  const [contactPick, setContactPick] = useState("");
  const [contactNote, setContactNote] = useState("");

  // Dossier: chủ quản/vận hành, phạm vi & quy mô, ứng dụng, vùng mạng
  const [partyModal, setPartyModal] = useState<SystemProfileParty | "new-owner" | "new-operator" | null>(null);
  const [pRole, setPRole] = useState<PartyRole>("owner");
  const [pName, setPName] = useState("");
  const [pDoc, setPDoc] = useState("");
  const [pRep, setPRep] = useState("");
  const [pTitle, setPTitle] = useState("");
  const [pAddress, setPAddress] = useState("");
  const [pPhone, setPPhone] = useState("");
  const [pEmail, setPEmail] = useState("");
  const [scopeModal, setScopeModal] = useState(false);
  const [scLocation, setScLocation] = useState("");
  const [scAccounts, setScAccounts] = useState("");
  const [scData, setScData] = useState("");
  const [scAudience, setScAudience] = useState("internal");
  const [appModal, setAppModal] = useState<SystemProfileApplication | "new" | null>(null);
  const [aName, setAName] = useState("");
  const [aMachine, setAMachine] = useState("");
  const [aServer, setAServer] = useState("");
  const [aOs, setAOs] = useState("");
  const [aRole, setARole] = useState("");
  const [aUrl, setAUrl] = useState("");
  const [ipModal, setIpModal] = useState<SystemProfileIpRange | "new" | null>(null);
  const [ipZone, setIpZone] = useState("");
  const [ipZoneDesc, setIpZoneDesc] = useState("");
  const [ipCidr, setIpCidr] = useState("");
  const [ipKind, setIpKind] = useState<"private" | "public">("private");
  const [ipGateway, setIpGateway] = useState("");

  // Yêu cầu an toàn: trình thẩm định / thẩm định
  const [reqModal, setReqModal] = useState<ProfileRequirement | null>(null);
  const [reqEvidence, setReqEvidence] = useState("");
  const [reviewReqModal, setReviewReqModal] = useState<{ row: ProfileRequirement; action: "verify" | "reject" } | null>(null);
  const [reqReviewNote, setReqReviewNote] = useState("");

  const load = useCallback(async () => {
    try {
      const p = await api.get<SystemProfileDetail>(`/system-profiles/${id}`);
      setProfile(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được hồ sơ");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Catalog loại thiết bị — super admin lấy cả loại đã tắt (để quản lý)
  useEffect(() => {
    void api
      .get<DeviceType[]>("/device-types", { active_only: isSuperAdmin ? false : true })
      .then(setDevTypes)
      .catch(() => setDevTypes([]));
  }, [isSuperAdmin]);

  const activeDevTypes = devTypes.filter((t) => t.is_active);
  const typeMeta = {
    icons: Object.fromEntries(devTypes.map((t) => [t.code, t.icon ?? "📦"])),
    labels: Object.fromEntries(devTypes.map((t) => [t.code, t.label])),
  };

  const loadMachines = useCallback(async () => {
    if (!profile) return;
    try {
      const page = await api.get<{ items: MachineListItem[] }>("/machines", {
        org_id: profile.org_id,
        limit: 200,
      });
      setMachines(page.items);
    } catch {
      setMachines([]);
    }
  }, [profile]);

  useEffect(() => {
    if (tab === "machines" || tab === "applications") void loadMachines();
    if (tab === "contacts") {
      void api
        .get<ItContact[]>("/it-contacts", { org_id: profile?.org_id })
        .then(setContactsDir)
        .catch(() => setContactsDir([]));
    }
  }, [tab, loadMachines, profile?.org_id]);

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Thao tác thất bại");
    } finally {
      setBusy(false);
    }
  };

  const saveDevice = async () => {
    if (!profile || !dName.trim()) return;
    const payload: SystemProfileDevicePayload = {
      name: dName.trim(),
      device_code: dCode.trim() || null,
      tag: dTag.trim() || null,
      device_type: dType,
      ip: dIp.trim() || null,
      model: dModel.trim() || null,
      location: dLocation.trim() || null,
      purpose: dPurpose.trim() || null,
      sort_order: dSort,
    };
    await act(() =>
      deviceModal === "new"
        ? api.post(`/system-profiles/${profile.id}/devices`, payload)
        : api.put(`/system-profiles/${profile.id}/devices/${(deviceModal as SystemProfileDevice).id}`, payload),
    );
    setDeviceModal(null);
  };

  const openEditDevice = (d: SystemProfileDevice) => {
    setDName(d.name);
    setDCode(d.device_code ?? "");
    setDTag(d.tag ?? "");
    setDType(d.device_type);
    setDIp(d.ip ?? "");
    setDModel(d.model ?? "");
    setDLocation(d.location ?? "");
    setDPurpose(d.purpose ?? "");
    setDSort(d.sort_order);
    setDeviceModal(d);
  };

  const openNewDevice = () => {
    setDName("");
    setDCode("");
    setDTag("");
    setDType(activeDevTypes[0]?.code ?? "other");
    setDIp("");
    setDModel("");
    setDLocation("");
    setDPurpose("");
    setDSort(0);
    setDeviceModal("new");
  };

  // ── Dossier helpers ──
  const resetPartyForm = (role: PartyRole) => {
    setPRole(role); setPName(""); setPDoc(""); setPRep(""); setPTitle(""); setPAddress(""); setPPhone(""); setPEmail("");
  };
  const openPartyEdit = (x: SystemProfileParty) => {
    setPRole(x.role); setPName(x.name); setPDoc(x.mandate_document ?? ""); setPRep(x.legal_representative ?? "");
    setPTitle(x.representative_title ?? ""); setPAddress(x.address ?? ""); setPPhone(x.phone ?? ""); setPEmail(x.email ?? "");
  };
  const partyPayload = () => ({
    role: pRole,
    name: pName.trim(),
    mandate_document: pDoc.trim() || null,
    legal_representative: pRep.trim() || null,
    representative_title: pTitle.trim() || null,
    address: pAddress.trim() || null,
    phone: pPhone.trim() || null,
    email: pEmail.trim() || null,
  });
  const resetAppForm = () => { setAName(""); setAMachine(""); setAServer(""); setAOs(""); setARole(""); setAUrl(""); };
  const openAppEdit = (a: SystemProfileApplication) => {
    setAName(a.name); setAMachine(a.machine_id ?? ""); setAServer(a.server_name ?? ""); setAOs(a.os_name ?? ""); setARole(a.role ?? ""); setAUrl(a.url ?? "");
  };
  const appPayload = () => ({
    name: aName.trim(),
    machine_id: aMachine || null,
    server_name: aServer.trim() || null,
    os_name: aOs.trim() || null,
    role: aRole.trim() || null,
    url: aUrl.trim() || null,
  });
  const resetIpForm = () => { setIpZone(""); setIpZoneDesc(""); setIpCidr(""); setIpKind("private"); setIpGateway(""); };
  const openIpEdit = (x: SystemProfileIpRange) => {
    setIpZone(x.zone); setIpZoneDesc(x.zone_description ?? ""); setIpCidr(x.cidr); setIpKind(x.ip_kind); setIpGateway(x.gateway ?? "");
  };
  const ipPayload = () => ({
    zone: ipZone.trim(),
    zone_description: ipZoneDesc.trim() || null,
    cidr: ipCidr.trim(),
    ip_kind: ipKind,
    gateway: ipGateway.trim() || null,
  });

  if (loading) return <Spinner label="Đang tải hồ sơ…" />;
  if (error || !profile) return <ErrorBanner message={error ?? "Không tìm thấy hồ sơ"} onRetry={() => void load()} />;

  const canEdit = isAdmin && (profile.status !== "approved" || isSuperAdmin);
  const canSubmit = isAdmin && (profile.status === "drafted" || profile.status === "rejected");
  const canReview = isSuperAdmin && profile.status === "pending_review";
  const canDelete = isSuperAdmin || (isAdmin && (profile.status === "drafted" || profile.status === "rejected"));
  // Khai báo đã triển khai: đơn vị của hồ sơ (Super Admin cũng được) khi đã approved
  // và đã đáp ứng 100% yêu cầu ATTT của cấp độ (backend cũng chặn lần nữa)
  const canReportImplementation =
    isAdmin &&
    profile.status === "approved" &&
    profile.level_compliant &&
    (isSuperAdmin || profile.org_id === user?.org_id);
  // Super Admin xác nhận đáp ứng hồ sơ
  const canConfirmImplementation = isSuperAdmin && profile.status === "implemented";

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: "info", label: "Thông tin" },
    { key: "history", label: "Lịch sử" },
    { key: "devices", label: `Thiết bị (${profile.device_count})` },
    { key: "machines", label: `Máy tính (${profile.machine_count})` },
    { key: "contacts", label: `Chuyên trách & vận hành (${profile.contacts.length})` },
    { key: "requirements", label: `Yêu cầu ATTT (${profile.requirements_verified}/${profile.requirements_total})` },
    { key: "applications", label: `Ứng dụng (${profile.applications.length})` },
    { key: "ip-ranges", label: `Vùng mạng & IP (${profile.ip_ranges.length})` },
    { key: "diagram", label: "Sơ đồ" },
  ];

  return (
    <div>
      <PageHeader
        title={profile.name}
        description={`${profile.code} · ${profile.org_name ?? profile.org_id}`}
        actions={
          isAdmin && (
            <div className="flex flex-wrap gap-2">
              {canSubmit && (
                <Button variant="secondary" loading={busy} onClick={() => void act(() => api.post(`/system-profiles/${profile.id}/submit`))}>
                  Trình duyệt
                </Button>
              )}
              {canReview && (
                <Button onClick={() => setReviewModal("approve")}>Phê duyệt</Button>
              )}
              {canReview && (
                <Button variant="secondary" onClick={() => setReviewModal("reject")}>Từ chối</Button>
              )}
              {canReportImplementation && (
                <Button
                  loading={busy}
                  onClick={() => void act(() => api.post(`/system-profiles/${profile.id}/report-implementation`, {}))}
                >
                  Khai báo đã triển khai
                </Button>
              )}
              {canConfirmImplementation && (
                <Button
                  loading={busy}
                  onClick={() => void act(() => api.post(`/system-profiles/${profile.id}/confirm-implementation`, {}))}
                >
                  Xác nhận đáp ứng hồ sơ
                </Button>
              )}
              {canDelete && (
                <Button variant="danger" onClick={() => setConfirmDelete(true)}>
                  <Trash2 className="size-4" /> Xóa
                </Button>
              )}
            </div>
          )
        }
      />

      {actionError && <ErrorBanner message={actionError} />}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <LevelBadge level={profile.level} />
        <StatusBadge status={profile.status} />
        {profile.decision_number && (
          <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
            QĐ: {profile.decision_number}
            {profile.decision_agency ? ` — ${profile.decision_agency}` : ""}
          </Badge>
        )}
        {profile.status !== "approved" && (
          <span className="text-xs text-slate-500">Chưa đáp ứng cấp độ — chưa có quyết định phê duyệt</span>
        )}
        <Badge className={profile.level_compliant ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/20"}>
          {profile.level_compliant
            ? `Đáp ứng cấp độ ${profile.level}`
            : `Chưa đủ yêu cầu cấp độ ${profile.level} (${profile.requirements_verified}/${profile.requirements_total})`}
        </Badge>
      </div>

      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
              tab === t.key
                ? "border-brand-600 text-slate-900"
                : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
            }`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "info" && (
        <Card bodyClass="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div><span className="text-xs text-slate-500">Mã hồ sơ</span><div className="font-medium">{profile.code}</div></div>
            <div><span className="text-xs text-slate-500">Cấp độ</span><div><LevelBadge level={profile.level} /></div></div>
            <div><span className="text-xs text-slate-500">Tên chủ quản</span><div className="font-medium">{profile.managed_by ?? "—"}</div></div>
            <div><span className="text-xs text-slate-500">Đơn vị</span><div>{profile.org_name ?? profile.org_id}</div></div>
            <div>
              <span className="text-xs text-slate-500">Số văn bản đề nghị</span>
              <div className="font-medium">
                {profile.document_number ?? "—"}
                {profile.document_date && (
                  <span className="ml-1 text-xs font-normal text-slate-500">
                    (ngày {new Date(profile.document_date).toLocaleDateString("vi-VN")})
                  </span>
                )}
              </div>
            </div>
            <div><span className="text-xs text-slate-500">Số quyết định</span><div className="font-medium">{profile.decision_number ?? "—"}</div></div>
            <div><span className="text-xs text-slate-500">Ngày quyết định</span><div>{profile.decision_date ? new Date(profile.decision_date).toLocaleDateString("vi-VN") : "—"}</div></div>
            <div><span className="text-xs text-slate-500">Cơ quan ban hành</span><div>{profile.decision_agency ?? "—"}</div></div>
            <div><span className="text-xs text-slate-500">Cập nhật</span><div>{new Date(profile.updated_at).toLocaleString("vi-VN")}</div></div>
          </div>
          {profile.description && (
            <div>
              <span className="text-xs text-slate-500">Mô tả</span>
              <p className="whitespace-pre-wrap text-sm text-slate-700">{profile.description}</p>
            </div>
          )}
          {profile.review_note && (
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
              <strong>Ghi chú duyệt:</strong> {profile.review_note}
            </div>
          )}
          {/* Phạm vi & quy mô */}
          <div className="border-t border-slate-100 pt-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">Phạm vi & quy mô hệ thống</span>
              {canEdit && (
                <Button size="sm" variant="secondary" onClick={() => {
                  setScLocation(profile.physical_location ?? "");
                  setScAccounts(profile.user_accounts?.toString() ?? "");
                  setScData(profile.data_volume ?? "");
                  setScAudience(profile.service_audience ?? "internal");
                  setScopeModal(true);
                }}>Sửa phạm vi & quy mô</Button>
              )}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><span className="text-xs text-slate-500">Địa điểm lắp đặt thiết bị</span><div className="text-sm">{profile.physical_location ?? "—"}</div></div>
              <div><span className="text-xs text-slate-500">Số lượng tài khoản</span><div className="text-sm">{profile.user_accounts ?? "—"}</div></div>
              <div><span className="text-xs text-slate-500">Lượng dữ liệu xử lý</span><div className="text-sm">{profile.data_volume ?? "—"}</div></div>
              <div><span className="text-xs text-slate-500">Đối tượng sử dụng</span><div className="text-sm">{AUDIENCE_LABELS[profile.service_audience ?? "internal"] ?? profile.service_audience ?? "—"}</div></div>
            </div>
          </div>

          {/* Chủ quản & đơn vị vận hành */}
          <div className="border-t border-slate-100 pt-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">Chủ quản & đơn vị vận hành</span>
              {canEdit && (
                <div className="flex gap-1">
                  {!profile.parties.some((x) => x.role === "owner") && (
                    <Button size="sm" variant="secondary" onClick={() => { resetPartyForm("owner"); setPartyModal("new-owner"); }}>Thêm chủ quản</Button>
                  )}
                  {!profile.parties.some((x) => x.role === "operator") && (
                    <Button size="sm" variant="secondary" onClick={() => { resetPartyForm("operator"); setPartyModal("new-operator"); }}>Thêm đơn vị vận hành</Button>
                  )}
                </div>
              )}
            </div>
            {profile.parties.length === 0 ? (
              <p className="text-sm text-slate-400">Chưa khai báo chủ quản / đơn vị vận hành.</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {profile.parties.map((x) => (
                  <Card key={x.id} className="p-4">
                    <div className="mb-2 flex items-center justify-between">
                      <Badge className={x.role === "owner" ? "bg-indigo-50 text-indigo-700 ring-indigo-600/20" : "bg-sky-50 text-sky-700 ring-sky-600/20"}>
                        {x.role === "owner" ? "Chủ quản" : "Đơn vị vận hành"}
                      </Badge>
                      {canEdit && (
                        <Button size="sm" variant="secondary" onClick={() => { openPartyEdit(x); setPartyModal(x); }}>Sửa</Button>
                      )}
                    </div>
                    <div className="text-sm font-medium">{x.name}</div>
                    <dl className="mt-2 space-y-1 text-xs text-slate-600">
                      {x.mandate_document && <div><span className="text-slate-400">Văn bản: </span>{x.mandate_document}</div>}
                      {x.legal_representative && <div><span className="text-slate-400">Đại diện: </span>{x.legal_representative}{x.representative_title ? ` — ${x.representative_title}` : ""}</div>}
                      {x.address && <div><span className="text-slate-400">Địa chỉ: </span>{x.address}</div>}
                      {(x.phone || x.email) && <div><span className="text-slate-400">Liên hệ: </span>{[x.phone, x.email].filter(Boolean).join(" · ")}</div>}
                    </dl>
                  </Card>
                ))}
              </div>
            )}
          </div>
          {(canEdit || isAdmin) && (
            <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
              {canEdit && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setRName(profile.name);
                    setRDesc(profile.description ?? "");
                    setRenameModal(true);
                  }}
                >
                  Sửa tên & mô tả
                </Button>
              )}
              {/* Số văn bản + tên chủ quản bổ sung sau được, kể cả khi đã duyệt */}
              {isAdmin && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setDcNumber(profile.document_number ?? "");
                    setDcDate(profile.document_date ?? "");
                    setDcManaged(profile.managed_by ?? "");
                    setDocModal(true);
                  }}
                >
                  Sửa số văn bản & tên chủ quản
                </Button>
              )}
            </div>
          )}
        </Card>
      )}

      {tab === "history" && (
        <Card title="Timeline hồ sơ">
          {profile.events.length === 0 ? (
            <p className="text-sm text-slate-400">Chưa có sự kiện nào được ghi nhận.</p>
          ) : (
            <ol className="relative space-y-0 border-l-2 border-slate-100 pl-5 ml-2">
              {profile.events.map((ev) => {
                const meta = EVENT_META[ev.event] ?? { icon: "•", cls: "bg-slate-100 ring-slate-500/20" };
                return (
                  <li key={ev.id} className="relative pb-5 last:pb-0">
                    <span
                      className={`absolute -left-[31px] flex size-6 items-center justify-center rounded-full text-[11px] ring-2 ring-white ${meta.cls}`}
                      aria-hidden
                    >
                      {meta.icon}
                    </span>
                    <p className="text-sm font-medium text-slate-800">{ev.message}</p>
                    <p className="mt-0.5 text-xs text-slate-400">
                      {ev.actor_name ?? "Hệ thống"} · {new Date(ev.created_at).toLocaleString("vi-VN")}
                    </p>
                  </li>
                );
              })}
            </ol>
          )}
        </Card>
      )}

      {tab === "devices" && (
        <div className="space-y-3">
          {canEdit && (
            <div className="flex justify-end gap-2">
              {isSuperAdmin && (
                <Link href="/system-profiles/config">
                  <Button variant="secondary">Cấu hình loại thiết bị</Button>
                </Link>
              )}
              <Button onClick={openNewDevice}><Plus className="size-4" /> Thêm thiết bị</Button>
            </div>
          )}
          {profile.devices.length === 0 ? (
            <EmptyState title="Chưa có thiết bị nào" description="Khai báo firewall, switch, máy chủ… của hệ thống." />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr><th className={TH}>Tên thiết bị</th><th className={TH}>Loại</th><th className={TH}>Mã thiết bị</th><th className={TH}>IP</th><th className={TH}>Chủng loại</th><th className={TH}>Vị trí</th>{canEdit && <th className={TH}></th>}</tr>
                </thead>
                <tbody>
                  {profile.devices.map((d) => (
                    <tr key={d.id} className={TR_HOVER}>
                      <td className={`${TD} font-medium`}>{d.name}</td>
                      <td className={TD}><Badge>{typeMeta.icons[d.device_type] ?? "📦"} {labelFor(d.device_type, typeMeta)}</Badge></td>
                      <td className={`${TD} text-sm`}>{d.device_code ?? "—"}</td>
                      <td className={`${TD} text-sm`}>{d.ip ?? "—"}</td>
                      <td className={`${TD} text-sm`}>{d.model ?? "—"}</td>
                      <td className={`${TD} text-sm`}>{d.location ?? "—"}</td>
                      {canEdit && (
                        <td className={TD}>
                          <div className="flex gap-1">
                            <Button size="sm" variant="secondary" onClick={() => openEditDevice(d)}>Sửa</Button>
                            <Button size="sm" variant="danger" loading={busy} onClick={() => void act(() => api.delete(`/system-profiles/${profile.id}/devices/${d.id}`))}>Xóa</Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "machines" && (
        <div className="space-y-3">
          {canEdit && (
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Field label="Gắn máy tính đã enroll">
                  <Select value={machinePick} onChange={(e) => setMachinePick(e.target.value)}>
                    <option value="">— chọn máy thuộc đơn vị —</option>
                    {machines
                      // Chỉ máy thuộc đúng đơn vị của hồ sơ (chặn máy đơn vị khác)
                      .filter((m) => m.org_id === profile.org_id && !profile.machines.some((pm) => pm.machine_id === m.id))
                      .map((m) => (
                        <option key={m.id} value={m.id}>{m.hostname ?? m.machine_uuid}</option>
                      ))}
                  </Select>
                </Field>
              </div>
              <Button
                disabled={!machinePick || busy}
                loading={busy}
                onClick={() => {
                  const mid = machinePick;
                  setMachinePick("");
                  void act(() => api.post(`/system-profiles/${profile.id}/machines?machine_id=${mid}`));
                }}
              >
                Gắn máy
              </Button>
            </div>
          )}
          {profile.machines.length === 0 ? (
            <EmptyState title="Chưa gắn máy nào" description="Gắn các máy tính agent đã enroll thuộc hệ thống này." />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr><th className={TH}>Hostname</th><th className={TH}>Machine UUID</th><th className={TH}>Trạng thái</th>{canEdit && <th className={TH}></th>}</tr>
                </thead>
                <tbody>
                  {profile.machines.map((m) => (
                    <tr key={m.machine_id} className={TR_HOVER}>
                      <td className={TD}>
                        <Link href={`/machines/${m.machine_id}`} className="font-medium text-brand-600 hover:underline">
                          {m.hostname ?? "—"}
                        </Link>
                      </td>
                      <td className={`${TD} font-mono text-xs`}>{m.machine_uuid}</td>
                      <td className={`${TD} text-sm`}>{m.status}</td>
                      {canEdit && (
                        <td className={TD}>
                          <Button size="sm" variant="danger" loading={busy} onClick={() => void act(() => api.delete(`/system-profiles/${profile.id}/machines/${m.machine_id}`))}>Gỡ</Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "contacts" && (
        <div className="space-y-3">
          {canEdit && (
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Field label="Gắn chuyên trách CNTT / tổ chức vận hành" hint="Danh bạ của đơn vị — quản lý thêm ở trang Chuyên trách CNTT.">
                  <Select value={contactPick} onChange={(e) => setContactPick(e.target.value)}>
                    <option value="">— chọn từ danh bạ đơn vị —</option>
                    {contactsDir
                      .filter((c) => !profile.contacts.some((pc) => pc.contact_id === c.id))
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {`${c.kind === "org" ? "🏢" : "👤"} ${c.name}${c.position ? ` — ${c.position}` : ""}`}
                        </option>
                      ))}
                  </Select>
                </Field>
              </div>
              <div className="w-56">
                <Field label="Vai trò trong hồ sơ (tùy chọn)">
                  <Input value={contactNote} onChange={(e) => setContactNote(e.target.value)} placeholder="Phụ trách vận hành…" />
                </Field>
              </div>
              <Button
                disabled={!contactPick || busy}
                loading={busy}
                onClick={() => {
                  const cid = contactPick;
                  const note = contactNote.trim();
                  setContactPick("");
                  setContactNote("");
                  void act(() => api.post(`/system-profiles/${profile.id}/contacts/${cid}${note ? `?note=${encodeURIComponent(note)}` : ""}`));
                }}
              >
                Gắn
              </Button>
            </div>
          )}
          {profile.contacts.length === 0 ? (
            <EmptyState
              icon={<Building2 className="size-8 text-slate-400" />}
              title="Chưa gắn chuyên trách/tổ chức nào"
              description="Gắn người chuyên trách CNTT hoặc tổ chức vận hành liên quan đến hệ thống này từ danh bạ đơn vị."
            />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr><th className={TH}>Tên</th><th className={TH}>Loại</th><th className={TH}>Chức vụ / Đầu mối</th><th className={TH}>Điện thoại</th><th className={TH}>Email</th><th className={TH}>Vai trò trong hồ sơ</th>{canEdit && <th className={TH}></th>}</tr>
                </thead>
                <tbody>
                  {profile.contacts.map((pc) => (
                    <tr key={pc.contact_id} className={TR_HOVER}>
                      <td className={`${TD} font-medium`}>{pc.name}</td>
                      <td className={TD}>
                        <Badge className={pc.kind === "org" ? "bg-sky-50 text-sky-700 ring-sky-600/20" : "bg-indigo-50 text-indigo-700 ring-indigo-600/20"}>
                          {pc.kind === "org" ? "Tổ chức vận hành" : "Chuyên trách CNTT"}
                        </Badge>
                      </td>
                      <td className={`${TD} text-sm`}>
                        {pc.kind === "org"
                          ? [pc.position, pc.contact_person ? `Đầu mối: ${pc.contact_person}` : null].filter(Boolean).join(" · ") || "—"
                          : pc.position || "—"}
                      </td>
                      <td className={`${TD} text-sm`}>{pc.phone ?? "—"}</td>
                      <td className={`${TD} text-sm`}>{pc.email ?? "—"}</td>
                      <td className={`${TD} text-sm`}>{pc.note ?? "—"}</td>
                      {canEdit && (
                        <td className={TD}>
                          <Button size="sm" variant="danger" loading={busy} onClick={() => void act(() => api.delete(`/system-profiles/${profile.id}/contacts/${pc.contact_id}`))}>Gỡ</Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {isAdmin && (
            <p className="text-xs text-slate-400">
              Quản lý danh bạ đơn vị ở trang{" "}
              <Link href="/contacts" className="text-brand-600 hover:underline">Chuyên trách CNTT</Link>.
            </p>
          )}
        </div>
      )}

      {tab === "requirements" && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">
            Đơn vị phải đáp ứng đủ <strong>{profile.requirements_total}</strong> yêu cầu của cấp độ {profile.level} và được Super Admin thẩm định đạt mới coi là đảm bảo an toàn theo cấp độ.
          </p>
          {profile.requirements.length === 0 ? (
            <EmptyState title="Chưa có yêu cầu nào" description="Chưa có yêu cầu an toàn nào được định nghĩa cho cấp độ này." />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr><th className={TH}>Yêu cầu</th><th className={TH}>Trạng thái</th><th className={TH}>Cách đáp ứng</th><th className={TH}>Ghi chú thẩm định</th><th className={TH}></th></tr>
                </thead>
                <tbody>
                  {profile.requirements.map((r) => (
                    <tr key={r.id} className={TR_HOVER}>
                      <td className={`${TD} max-w-xs`}>
                        <div className="font-medium">{r.title}</div>
                        {r.description && <div className="text-xs text-slate-500">{r.description}</div>}
                      </td>
                      <td>
                        <div className="flex flex-col gap-1">
                          <ReqStatusBadge status={r.status} />
                          {r.review_note && <span className="text-xs text-rose-600">{r.review_note}</span>}
                        </div>
                      </td>
                      <td className={`${TD} max-w-xs text-sm`}>{r.evidence ?? <span className="text-slate-400">—</span>}</td>
                      <td className={`${TD} max-w-xs text-sm`}>{r.review_note && r.status === "verified" ? r.review_note : "—"}</td>
                      <td>
                        <div className="flex gap-1">
                          {isAdmin && (r.status === "pending" || r.status === "rejected") && (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => { setReqEvidence(r.evidence ?? ""); setReqModal(r); }}
                            >
                              Trình thẩm định
                            </Button>
                          )}
                          {isSuperAdmin && r.status === "requested" && (
                            <>
                              <Button size="sm" onClick={() => { setReqReviewNote(""); setReviewReqModal({ row: r, action: "verify" }); }}>
                                Đạt
                              </Button>
                              <Button size="sm" variant="danger" onClick={() => { setReqReviewNote(""); setReviewReqModal({ row: r, action: "reject" }); }}>
                                Không đạt
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "applications" && (
        <div className="space-y-3">
          {canEdit && (
            <div className="flex justify-end">
              <Button onClick={() => { resetAppForm(); setAppModal("new"); }}><Plus className="size-4" /> Thêm ứng dụng</Button>
            </div>
          )}
          {profile.applications.length === 0 ? (
            <EmptyState title="Chưa có ứng dụng nào" description="Khai báo các ứng dụng/dịch vụ do hệ thống cung cấp." />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr><th className={TH}>Ứng dụng</th><th className={TH}>Máy chủ</th><th className={TH}>Hệ điều hành</th><th className={TH}>Vai trò</th><th className={TH}>URL</th>{canEdit && <th className={TH}></th>}</tr>
                </thead>
                <tbody>
                  {profile.applications.map((a) => (
                    <tr key={a.id} className={TR_HOVER}>
                      <td className={`${TD} font-medium`}>{a.name}</td>
                      <td className={`${TD} text-sm`}>{a.machine_id ? (profile.machines.find((m) => m.machine_id === a.machine_id)?.hostname ?? "Máy đã gắn") : (a.server_name ?? "—")}</td>
                      <td className={`${TD} text-sm`}>{a.os_name ?? "—"}</td>
                      <td className={`${TD} max-w-xs text-sm`}>{a.role ?? "—"}</td>
                      <td className={`${TD} text-sm`}>{a.url ?? "—"}</td>
                      {canEdit && (
                        <td className={TD}>
                          <div className="flex gap-1">
                            <Button size="sm" variant="secondary" onClick={() => { openAppEdit(a); setAppModal(a); }}>Sửa</Button>
                            <Button size="sm" variant="danger" loading={busy} onClick={() => void act(() => api.delete(`/system-profiles/${profile.id}/applications/${a.id}`))}>Xóa</Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "ip-ranges" && (
        <div className="space-y-3">
          {canEdit && (
            <div className="flex justify-end">
              <Button onClick={() => { resetIpForm(); setIpModal("new"); }}><Plus className="size-4" /> Thêm dải IP</Button>
            </div>
          )}
          {profile.ip_ranges.length === 0 ? (
            <EmptyState title="Chưa có quy hoạch IP" description="Khai báo các vùng mạng (nội bộ, biên, DMZ…) và dải IP tương ứng." />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr><th className={TH}>Vùng mạng</th><th className={TH}>Dải IP</th><th className={TH}>Loại</th><th className={TH}>Gateway</th><th className={TH}>Mô tả</th>{canEdit && <th className={TH}></th>}</tr>
                </thead>
                <tbody>
                  {profile.ip_ranges.map((ip) => (
                    <tr key={ip.id} className={TR_HOVER}>
                      <td className={`${TD} font-medium`}>{ip.zone}</td>
                      <td className={`${TD} font-mono text-sm`}>{ip.cidr}</td>
                      <td className={TD}>
                        <Badge className={ip.ip_kind === "public" ? "bg-amber-50 text-amber-700 ring-amber-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/20"}>
                          {ip.ip_kind === "public" ? "Public" : "Private"}
                        </Badge>
                      </td>
                      <td className={`${TD} text-sm`}>{ip.gateway ?? "—"}</td>
                      <td className={`${TD} max-w-xs text-sm`}>{ip.zone_description ?? "—"}</td>
                      {canEdit && (
                        <td className={TD}>
                          <div className="flex gap-1">
                            <Button size="sm" variant="secondary" onClick={() => { openIpEdit(ip); setIpModal(ip); }}>Sửa</Button>
                            <Button size="sm" variant="danger" loading={busy} onClick={() => void act(() => api.delete(`/system-profiles/${profile.id}/ip-ranges/${ip.id}`))}>Xóa</Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "diagram" && (
        <div className="space-y-4">
          <Card title="Sơ đồ mô hình lô-gic">
            <MermaidDiagram
              code={profile.diagram_mermaid}
              fallbackCode={generateDevicesMermaid(profile.devices, typeMeta)}
              autoLabel="Sơ đồ tự sinh từ danh mục thiết bị đã khai — bấm Chỉnh sửa để tự vẽ."
              editable={canEdit}
              saving={busy}
              onSave={(code) => act(() => api.patch(`/system-profiles/${profile.id}`, { diagram_mermaid: code }))}
              validate={(c) => validateDevicesMermaid(c, profile.devices)}
            />
          </Card>
          <Card title="Sơ đồ mô hình vật lý">
            <MermaidDiagram
              code={profile.physical_diagram_mermaid}
              fallbackCode={generateDevicesMermaid(profile.devices, typeMeta)}
              autoLabel="Sơ đồ tự sinh từ danh mục thiết bị đã khai — bấm Chỉnh sửa để tự vẽ."
              editable={canEdit}
              saving={busy}
              onSave={(code) => act(() => api.patch(`/system-profiles/${profile.id}`, { physical_diagram_mermaid: code }))}
              validate={(c) => validateDevicesMermaid(c, profile.devices)}
            />
          </Card>
        </div>
      )}

      {/* Modal thêm/sửa thiết bị */}
      <Modal
        open={deviceModal !== null}
        onClose={() => setDeviceModal(null)}
        title={deviceModal === "new" ? "Thêm thiết bị" : "Sửa thiết bị"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeviceModal(null)}>Hủy</Button>
            <Button onClick={() => void saveDevice()} loading={busy}>Lưu</Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Tên thiết bị" required>
            <Input value={dName} onChange={(e) => setDName(e.target.value)} placeholder="Firewall biên giới" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Loại thiết bị">
              <Select value={dType} onChange={(e) => setDType(e.target.value)}>
                {activeDevTypes.map((t) => (
                  <option key={t.code} value={t.code}>{`${t.icon ?? "📦"} ${t.label}`}</option>
                ))}
              </Select>
            </Field>
            <Field label="Mã thiết bị">
              <Input value={dCode} onChange={(e) => setDCode(e.target.value)} placeholder="FW-01" />
            </Field>
            <Field label="Tag">
              <Input value={dTag} onChange={(e) => setDTag(e.target.value)} placeholder="FW" />
            </Field>
            <Field label="IP">
              <Input value={dIp} onChange={(e) => setDIp(e.target.value)} placeholder="10.0.0.1" />
            </Field>
            <Field label="Hãng sản xuất / chủng loại">
              <Input value={dModel} onChange={(e) => setDModel(e.target.value)} />
            </Field>
            <Field label="Vị trí triển khai">
              <Input value={dLocation} onChange={(e) => setDLocation(e.target.value)} placeholder="Tầng 2 — tủ rack A" />
            </Field>
            <Field label="Thứ tự hiển thị">
              <Input type="number" value={dSort} onChange={(e) => setDSort(Number(e.target.value))} />
            </Field>
          </div>
          <Field label="Mục đích sử dụng trong hệ thống"><Textarea value={dPurpose} onChange={(e) => setDPurpose(e.target.value)} rows={2} /></Field>
        </div>
      </Modal>

      {/* Modal duyệt / từ chối */}
      <Modal
        open={reviewModal !== null}
        onClose={() => setReviewModal(null)}
        title={reviewModal === "approve" ? "Phê duyệt hồ sơ" : "Từ chối hồ sơ"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReviewModal(null)}>Hủy</Button>
            <Button
              variant={reviewModal === "approve" ? "primary" : "danger"}
              loading={busy}
              onClick={() => {
                const payload: SystemProfileReviewPayload =
                  reviewModal === "approve"
                    ? { action: "approve", decision_number: decisionNumber.trim() || null, decision_agency: decisionAgency.trim() || null }
                    : { action: "reject", review_note: reviewNote.trim() || null };
                if (reviewModal === "approve" && !payload.decision_number) {
                  setActionError("Phải nhập số quyết định phê duyệt");
                  return;
                }
                if (reviewModal === "reject" && !payload.review_note) {
                  setActionError("Phải nhập lý do từ chối để đơn vị biết và sửa hồ sơ");
                  return;
                }
                setDecisionNumber("");
                setDecisionAgency("");
                setReviewNote("");
                const p = payload;
                void act(async () => { await api.post(`/system-profiles/${profile.id}/review`, p); setTab("info"); });
                setReviewModal(null);
              }}
            >
              Xác nhận
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {reviewModal === "approve" ? (
            <>
              <Field label="Số quyết định" required>
                <Input value={decisionNumber} onChange={(e) => setDecisionNumber(e.target.value)} placeholder="15/QĐ-ATTT" />
              </Field>
              <Field label="Cơ quan ban hành">
                <Input value={decisionAgency} onChange={(e) => setDecisionAgency(e.target.value)} placeholder="Công an tỉnh" />
              </Field>
            </>
          ) : (
            <Field label="Lý do từ chối" required hint="Lý do hiển thị cho đơn vị để sửa hồ sơ và trình lại.">
              <Textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={3} />
            </Field>
          )}
        </div>
      </Modal>

      {/* Modal trình thẩm định yêu cầu */}
      <Modal
        open={reqModal !== null}
        onClose={() => setReqModal(null)}
        title={reqModal ? `Trình thẩm định: ${reqModal.title}` : ""}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReqModal(null)}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                if (!reqModal) return;
                if (!reqEvidence.trim()) {
                  setActionError("Nhập cách đáp ứng yêu cầu (bằng chứng)");
                  return;
                }
                const row = reqModal;
                setReqModal(null);
                void act(() => api.post(`/system-profiles/${profile.id}/requirements/${row.id}/request`, { evidence: reqEvidence.trim() }));
              }}
            >
              Trình thẩm định
            </Button>
          </>
        }
      >
        {reqModal && (
          <div className="space-y-3">
            {reqModal.description && <p className="text-sm text-slate-600">{reqModal.description}</p>}
            <Field label="Cách đáp ứng / bằng chứng" required>
              <Textarea value={reqEvidence} onChange={(e) => setReqEvidence(e.target.value)} rows={4} placeholder="Mô tả cách đơn vị đáp ứng yêu cầu, kèm tài liệu minh chứng…" />
            </Field>
          </div>
        )}
      </Modal>

      {/* Modal thẩm định yêu cầu */}
      <Modal
        open={reviewReqModal !== null}
        onClose={() => setReviewReqModal(null)}
        title={reviewReqModal?.action === "verify" ? "Xác nhận thẩm định đạt" : "Thẩm định không đạt"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReviewReqModal(null)}>Hủy</Button>
            <Button
              variant={reviewReqModal?.action === "verify" ? "primary" : "danger"}
              loading={busy}
              onClick={() => {
                if (!reviewReqModal) return;
                const { row, action } = reviewReqModal;
                setReviewReqModal(null);
                void act(() => api.post(`/system-profiles/${profile.id}/requirements/${row.id}/review`, { action, review_note: reqReviewNote.trim() || null }));
              }}
            >
              Xác nhận
            </Button>
          </>
        }
      >
        {reviewReqModal && (
          <div className="space-y-3">
            {reviewReqModal.row.evidence && (
              <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
                <strong>Bằng chứng của đơn vị:</strong> {reviewReqModal.row.evidence}
              </div>
            )}
            <Field label="Ghi chú thẩm định">
              <Textarea value={reqReviewNote} onChange={(e) => setReqReviewNote(e.target.value)} rows={3} />
            </Field>
          </div>
        )}
      </Modal>

      {/* Modal chủ quản / vận hành */}
      <Modal
        open={partyModal !== null}
        onClose={() => setPartyModal(null)}
        title={partyModal === "new-owner" ? "Thêm chủ quản" : partyModal === "new-operator" ? "Thêm đơn vị vận hành" : "Sửa thông tin"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPartyModal(null)}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                if (!pName.trim()) { setActionError("Nhập tên đơn vị"); return; }
                const payload = partyPayload();
                setPartyModal(null);
                void act(() =>
                  partyModal === "new-owner" || partyModal === "new-operator"
                    ? api.post(`/system-profiles/${profile.id}/parties`, payload)
                    : api.put(`/system-profiles/${profile.id}/parties/${(partyModal as SystemProfileParty).id}`, payload),
                );
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Tên đơn vị" required><Input value={pName} onChange={(e) => setPName(e.target.value)} /></Field>
          <Field label="Văn bản quy định chức năng, nhiệm vụ, quyền hạn"><Textarea value={pDoc} onChange={(e) => setPDoc(e.target.value)} rows={2} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Người đại diện pháp luật"><Input value={pRep} onChange={(e) => setPRep(e.target.value)} /></Field>
            <Field label="Chức vụ"><Input value={pTitle} onChange={(e) => setPTitle(e.target.value)} /></Field>
            <Field label="Địa chỉ" required={false}><Input value={pAddress} onChange={(e) => setPAddress(e.target.value)} /></Field>
            <Field label="Số điện thoại"><Input value={pPhone} onChange={(e) => setPPhone(e.target.value)} /></Field>
            <Field label="Email"><Input value={pEmail} onChange={(e) => setPEmail(e.target.value)} /></Field>
          </div>
        </div>
      </Modal>

      {/* Modal phạm vi & quy mô */}
      <Modal
        open={scopeModal}
        onClose={() => setScopeModal(false)}
        title="Phạm vi & quy mô hệ thống"
        footer={
          <>
            <Button variant="secondary" onClick={() => setScopeModal(false)}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                setScopeModal(false);
                void act(() => api.patch(`/system-profiles/${profile.id}`, {
                  physical_location: scLocation.trim() || null,
                  user_accounts: scAccounts === "" ? null : Number(scAccounts),
                  data_volume: scData.trim() || null,
                  service_audience: scAudience,
                }));
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Phạm vi vật lý — địa điểm lắp đặt thiết bị"><Textarea value={scLocation} onChange={(e) => setScLocation(e.target.value)} rows={2} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Số lượng tài khoản"><Input type="number" value={scAccounts} onChange={(e) => setScAccounts(e.target.value)} /></Field>
            <Field label="Đối tượng sử dụng">
              <Select value={scAudience} onChange={(e) => setScAudience(e.target.value)}>
                {Object.entries(AUDIENCE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Lượng dữ liệu xử lý"><Textarea value={scData} onChange={(e) => setScData(e.target.value)} rows={2} /></Field>
        </div>
      </Modal>

      {/* Modal ứng dụng */}
      <Modal
        open={appModal !== null}
        onClose={() => setAppModal(null)}
        title={appModal === "new" ? "Thêm ứng dụng / dịch vụ" : "Sửa ứng dụng"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setAppModal(null)}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                if (!aName.trim()) { setActionError("Nhập tên ứng dụng"); return; }
                const payload = appPayload();
                const isNew = appModal === "new";
                setAppModal(null);
                void act(() =>
                  isNew
                    ? api.post(`/system-profiles/${profile.id}/applications`, payload)
                    : api.put(`/system-profiles/${profile.id}/applications/${(appModal as SystemProfileApplication).id}`, payload),
                );
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Tên ứng dụng / dịch vụ" required><Input value={aName} onChange={(e) => setAName(e.target.value)} /></Field>
          <Field label="Máy chủ cài đặt" hint="Chọn máy đã enroll (tự lấy hostname), hoặc nhập tay bên dưới nếu máy chưa được quản lý">
            <Select value={aMachine} onChange={(e) => setAMachine(e.target.value)}>
              <option value="">— nhập tay —</option>
              {machines.filter((m) => m.org_id === profile.org_id).map((m) => <option key={m.id} value={m.id}>{m.hostname ?? m.machine_uuid}</option>)}
            </Select>
          </Field>
          {!aMachine && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Tên máy chủ"><Input value={aServer} onChange={(e) => setAServer(e.target.value)} /></Field>
              <Field label="Hệ điều hành"><Input value={aOs} onChange={(e) => setAOs(e.target.value)} /></Field>
            </div>
          )}
          <Field label="Vai trò / nhiệm vụ của dịch vụ"><Textarea value={aRole} onChange={(e) => setARole(e.target.value)} rows={2} /></Field>
          <Field label="URL / cổng truy cập"><Input value={aUrl} onChange={(e) => setAUrl(e.target.value)} /></Field>
        </div>
      </Modal>

      {/* Modal dải IP */}
      <Modal
        open={ipModal !== null}
        onClose={() => setIpModal(null)}
        title={ipModal === "new" ? "Thêm dải IP" : "Sửa dải IP"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setIpModal(null)}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                if (!ipZone.trim() || !ipCidr.trim()) { setActionError("Nhập tên vùng và dải IP"); return; }
                const payload = ipPayload();
                const isNew = ipModal === "new";
                setIpModal(null);
                void act(() =>
                  isNew
                    ? api.post(`/system-profiles/${profile.id}/ip-ranges`, payload)
                    : api.put(`/system-profiles/${profile.id}/ip-ranges/${(ipModal as SystemProfileIpRange).id}`, payload),
                );
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Tên vùng mạng" required><Input value={ipZone} onChange={(e) => setIpZone(e.target.value)} placeholder="DMZ / Nội bộ / Biên mạng" /></Field>
            <Field label="Loại IP">
              <Select value={ipKind} onChange={(e) => setIpKind(e.target.value as "private" | "public")}>
                <option value="private">Private (nội bộ)</option>
                <option value="public">Public (công khai)</option>
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Dải IP / CIDR" required><Input value={ipCidr} onChange={(e) => setIpCidr(e.target.value)} placeholder="10.10.1.0/24" /></Field>
            <Field label="Gateway"><Input value={ipGateway} onChange={(e) => setIpGateway(e.target.value)} /></Field>
          </div>
          <Field label="Mô tả vùng"><Textarea value={ipZoneDesc} onChange={(e) => setIpZoneDesc(e.target.value)} rows={2} /></Field>
        </div>
      </Modal>

      {/* Modal sửa số văn bản đề nghị & tên chủ quản — bổ sung sau được */}
      <Modal
        open={docModal}
        onClose={() => setDocModal(false)}
        title="Số văn bản đề nghị & tên chủ quản"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDocModal(false)} disabled={busy}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                setDocModal(false);
                void act(() => api.patch(`/system-profiles/${profile.id}`, {
                  document_number: dcNumber.trim() || null,
                  document_date: dcDate || null,
                  managed_by: dcManaged.trim() || null,
                }));
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Số văn bản đề nghị" hint="Văn bản đơn vị gửi kèm hồ sơ thẩm định — có thể bổ sung sau.">
            <Input value={dcNumber} onChange={(e) => setDcNumber(e.target.value)} placeholder="VD: 125/BC-XX" />
          </Field>
          <Field label="Ngày văn bản">
            <Input type="date" value={dcDate} onChange={(e) => setDcDate(e.target.value)} />
          </Field>
          <Field label="Tên chủ quản hệ thống thông tin">
            <Input value={dcManaged} onChange={(e) => setDcManaged(e.target.value)} />
          </Field>
        </div>
      </Modal>

      {/* Modal sửa tên & mô tả */}
      <Modal
        open={renameModal}
        onClose={() => setRenameModal(false)}
        title="Sửa tên & mô tả"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRenameModal(false)} disabled={busy}>Hủy</Button>
            <Button
              loading={busy}
              onClick={() => {
                if (!rName.trim()) { setActionError("Nhập tên hệ thống thông tin"); return; }
                setRenameModal(false);
                void act(() => api.patch(`/system-profiles/${profile.id}`, { name: rName.trim(), description: rDesc.trim() || null }));
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Tên hệ thống thông tin" required>
            <Input value={rName} onChange={(e) => setRName(e.target.value)} />
          </Field>
          <Field label="Mô tả phạm vi, chức năng">
            <Textarea value={rDesc} onChange={(e) => setRDesc(e.target.value)} rows={4} />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Xóa hồ sơ?"
        message={`Xóa vĩnh viễn hồ sơ "${profile.name}" cùng danh sách thiết bị. Thao tác không thể hoàn tác.`}
        danger
        loading={busy}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => {
          void act(async () => {
            await api.delete(`/system-profiles/${profile.id}`);
            router.push("/system-profiles");
          });
          setConfirmDelete(false);
        }}
      />
    </div>
  );
}
