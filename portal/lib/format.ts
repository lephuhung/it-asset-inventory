import type {
  AssetLifecycle,
  MachineStatus,
  Organization,
  OrgType,
  TokenStatus,
  UserRole,
} from "@/lib/types";

/** Nhãn tiếng Việt + màu badge cho từng loại trạng thái. */

export const MACHINE_STATUS_META: Record<
  MachineStatus,
  { label: string; badge: string; dot: string; icon: "ok" | "warn" | "bad" | "wait" }
> = {
  online: {
    label: "Online",
    badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    dot: "bg-emerald-500",
    icon: "ok",
  },
  offline: {
    label: "Offline",
    badge: "bg-slate-100 text-slate-600 ring-slate-500/20",
    dot: "bg-slate-400",
    icon: "warn",
  },
  lost: {
    label: "Máy mất kết nối",
    badge: "bg-rose-50 text-rose-700 ring-rose-600/20",
    dot: "bg-rose-500",
    icon: "bad",
  },
  decommissioned: {
    label: "Đã thanh lý",
    badge: "bg-zinc-100 text-zinc-500 ring-zinc-500/20",
    dot: "bg-zinc-400",
    icon: "wait",
  },
  pending: {
    label: "Chờ duyệt",
    badge: "bg-amber-50 text-amber-700 ring-amber-600/20",
    dot: "bg-amber-500",
    icon: "wait",
  },
};

export const TOKEN_STATUS_META: Record<TokenStatus, { label: string; badge: string; dot: string }> = {
  pending: {
    label: "Đã gửi, chờ cài",
    badge: "bg-amber-50 text-amber-700 ring-amber-600/20",
    dot: "bg-amber-500",
  },
  used: {
    label: "Đã dùng",
    badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    dot: "bg-emerald-500",
  },
  revoked: {
    label: "Đã thu hồi",
    badge: "bg-rose-50 text-rose-700 ring-rose-600/20",
    dot: "bg-rose-500",
  },
  expired: {
    label: "Hết hạn",
    badge: "bg-zinc-100 text-zinc-500 ring-zinc-500/20",
    dot: "bg-zinc-400",
  },
};

export const LIFECYCLE_META: Record<AssetLifecycle, { label: string; badge: string }> = {
  new: { label: "Mới cài", badge: "bg-sky-50 text-sky-700 ring-sky-600/20" },
  in_use: { label: "Đang dùng", badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  in_repair: { label: "Sửa chữa", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  decommissioned: { label: "Thanh lý", badge: "bg-zinc-100 text-zinc-500 ring-zinc-500/20" },
};

export const ROLE_META: Record<UserRole, { label: string; badge: string }> = {
  super_admin: { label: "Super Admin", badge: "bg-violet-50 text-violet-700 ring-violet-600/20" },
  org_admin: { label: "Admin tổ chức", badge: "bg-blue-50 text-blue-700 ring-blue-600/20" },
  viewer: { label: "Người xem", badge: "bg-slate-100 text-slate-600 ring-slate-500/20" },
  admin_global: { label: "Super Admin (cũ)", badge: "bg-violet-50 text-violet-700 ring-violet-600/20" },
  admin_org: { label: "Admin tổ chức (cũ)", badge: "bg-blue-50 text-blue-700 ring-blue-600/20" },
};

/** Nhãn loại tổ chức — UBND cấp xã / Sở ban ngành / cấp dưới. */
export const ORG_TYPE_META: Record<OrgType, { label: string; badge: string }> = {
  root: { label: "Tổ chức gốc", badge: "bg-zinc-100 text-zinc-600 ring-zinc-500/20" },
  ubnd_xa: { label: "UBND cấp xã", badge: "bg-sky-50 text-sky-700 ring-sky-600/20" },
  so_ban_nganh: { label: "Sở ban ngành", badge: "bg-indigo-50 text-indigo-700 ring-indigo-600/20" },
  phong: { label: "Phòng ban", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  don_vi: { label: "Đơn vị trực thuộc", badge: "bg-slate-100 text-slate-600 ring-slate-500/20" },
};

export function orgTypeLabel(type: string): string {
  return ORG_TYPE_META[type as OrgType]?.label ?? type;
}

/** Nhãn loại alert rule (Phase 2). */
export const ALERT_RULE_TYPE_META: Record<string, { label: string; badge: string }> = {
  machine_new: { label: "Máy mới", badge: "bg-sky-50 text-sky-700 ring-sky-600/20" },
  machine_lost: { label: "Mất liên lạc", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
  software_new: { label: "Phần mềm lạ", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  hardware_changed: { label: "Phần cứng đổi", badge: "bg-violet-50 text-violet-700 ring-violet-600/20" },
};

export const ALERT_CHANNEL_META: Record<string, string> = {
  email: "Email",
  telegram: "Telegram",
  zalo: "Zalo OA",
};

export const ALERT_SEVERITY_META: Record<string, { label: string; badge: string }> = {
  info: { label: "Thông tin", badge: "bg-sky-50 text-sky-700 ring-sky-600/20" },
  success: { label: "Thành công", badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  warning: { label: "Cảnh báo", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  error: { label: "Lỗi", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
  critical: { label: "Nghiêm trọng", badge: "bg-rose-100 text-rose-700 ring-rose-600/20" },
};

/* ── Tags máy (phân loại + mục đích) ──────────────────────────── */

/** Nhãn + màu mặc định cho 3 loại máy (tag classification hệ thống). */
export const CLASSIFICATION_META: Record<string, { label: string; badge: string }> = {
  personal: { label: "Máy cá nhân", badge: "bg-sky-50 text-sky-700 ring-sky-600/20" },
  official: { label: "Máy công vụ", badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  bmnn: { label: "Máy BMNN", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
};

export interface TagLike {
  key: string;
  label: string;
  kind: "classification" | "purpose" | string;
  color?: string | null;
}

/** Class badge cho 1 tag — ưu tiên màu đặt ở server, fallback theo key/kind.
 *  Classification → màu theo loại máy (sky/emerald/amber); purpose → violet nổi bật. */
export function tagBadgeClass(tag: TagLike): string {
  if (tag.color) return tag.color;
  if (tag.kind === "classification") {
    return CLASSIFICATION_META[tag.key]?.badge ?? "bg-emerald-50 text-emerald-700 ring-emerald-600/20";
  }
  return "bg-violet-50 text-violet-700 ring-violet-600/20";
}

/** Tag classification của máy (mỗi máy đúng 1) — trả về tag hoặc null. */
export function classificationTag(tags: TagLike[] | undefined | null): TagLike | null {
  return (tags ?? []).find((t) => t.kind === "classification") ?? null;
}

/** Tag mục đích của máy (nhiều). */
export function purposeTags(tags: TagLike[] | undefined | null): TagLike[] {
  return (tags ?? []).filter((t) => t.kind === "purpose");
}

/** Làm phẳng cây tổ chức thành danh sách select (kèm độ sâu). */
export function flattenOrgTree(
  roots: Organization[],
  depth = 0,
): Array<{ org: Organization; depth: number }> {
  const out: Array<{ org: Organization; depth: number }> = [];
  for (const node of roots) {
    out.push({ org: node, depth });
    if (node.children?.length) {
      out.push(...flattenOrgTree(node.children, depth + 1));
    }
  }
  return out;
}

/** Định dạng số liệu người dùng máy (mask mặc định theo mục 7.3). */
export function maskPhone(phone: string | null | undefined): string {
  if (!phone) return "—";
  if (phone.length >= 7) return `${phone.slice(0, 4)}•••${phone.slice(-3)}`;
  return "•••";
}

/** Thời gian tương đối tiếng Việt. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 0) return "vừa xong";
  if (diffSec < 60) return `${diffSec}s trước`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} phút trước`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH} giờ trước`;
  const diffD = Math.round(diffH / 24);
  if (diffD < 30) return `${diffD} ngày trước`;
  return new Date(iso).toLocaleDateString("vi-VN");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes) || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function shortUuid(uuid: string | null | undefined, len = 8): string {
  if (!uuid) return "—";
  return uuid.length > len ? `${uuid.slice(0, len)}…` : uuid;
}

/** Số ngày còn lại tới 1 mốc thời gian (âm = đã qua). */
export function daysLeft(iso: string | undefined | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return Math.ceil((t - Date.now()) / 86_400_000);
}

/**
 * Trạng thái hết hạn chính xác (không dùng làm tròn ngày — tránh nhầm token
 * quá hạn dưới 1 ngày thành "còn 0 ngày" do `Math.ceil` trả `-0`).
 */
export interface TokenExpiry {
  /** Đã hết hạn (mốc thời gian < hiện tại). */
  expired: boolean;
  /** Nhãn ngắn: "Đã quá hạn" / "Còn X ngày" / "Còn X giờ". */
  label: string;
  /** Số giờ còn lại (âm = đã quá hạn). */
  hoursLeft: number;
}

export function tokenExpiry(iso: string | undefined | null): TokenExpiry | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const hoursLeft = (t - Date.now()) / 3_600_000;
  if (hoursLeft <= 0) {
    return { expired: true, label: "Đã quá hạn", hoursLeft };
  }
  if (hoursLeft < 24) {
    return { expired: false, label: `Còn ${Math.max(1, Math.round(hoursLeft))} giờ`, hoursLeft };
  }
  return { expired: false, label: `Còn ${Math.ceil(hoursLeft / 24)} ngày`, hoursLeft };
}
// ── Alert engine (templates) ───────────────────────────────────

export const ALERT_CATEGORY_META: Record<string, { label: string; badge: string }> = {
  machine: { label: "Máy", badge: "bg-blue-50 text-blue-700 ring-blue-600/20" },
  investigation: { label: "Điều tra", badge: "bg-violet-50 text-violet-700 ring-violet-600/20" },
  security: { label: "Bảo mật", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
  system: { label: "Hệ thống", badge: "bg-slate-100 text-slate-600 ring-slate-500/20" },
};

export const OPT_OUT_LABELS: Record<string, string> = {
  template: "Tắt nhận template này",
  severity: "Chọn mức severity tối thiểu",
};
