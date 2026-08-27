/** Kiểu dữ liệu phản chiếu schema backend (FastAPI — app/schemas/__init__.py). */

/** Vai trò theo phân cấp: super_admin xem tất cả; org_admin xem org mình + cấp dưới. */
export type UserRole =
  | "super_admin"
  | "org_admin"
  | "viewer"
  | "admin_global" // legacy → super_admin
  | "admin_org"; // legacy → org_admin

export type OrgType = "root" | "ubnd_xa" | "so_ban_nganh" | "phong" | "don_vi";

export type MachineStatus = "online" | "offline" | "lost" | "decommissioned" | "pending";

export type TokenStatus = "pending" | "used" | "revoked" | "expired";

export type AssetLifecycle = "new" | "in_use" | "in_repair" | "decommissioned";

export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  org_id: string;
  is_2fa_enabled: boolean;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  requires_2fa: boolean;
}

export interface TotpSetupResponse {
  secret: string;
  uri: string;
  backup_codes: string[];
}

export interface StatsOverview {
  total_machines: number;
  online: number;
  offline: number;
  lost: number;
  pending_tokens: number;
  expired_tokens: number;
}

export interface Organization {
  id: string;
  parent_id: string | null;
  name: string;
  type: OrgType;
  /** Cây tổ chức: các đơn vị cấp dưới. */
  children: Organization[];
}

export interface OrganizationCreate {
  name: string;
  type: "ubnd_xa" | "so_ban_nganh" | "phong" | "don_vi";
  parent_id?: string | null;
}

export interface MachineListItem {
  id: string;
  hostname: string | null;
  machine_uuid: string;
  status: MachineStatus;
  lifecycle: AssetLifecycle;
  is_vm: boolean | null;
  last_seen_at: string | null;
  enrolled_at: string;
  org_id: string;
  assigned_user_id: string | null;
  logged_user?: string | null;
}

export interface NetworkInterface {
  name?: string | null;
  ip?: string | null;
  mac?: string | null;
  is_dual_homed?: boolean;
}

export interface SecurityPosture {
  antivirus?: Array<Record<string, unknown>> | null;
  windows_update_status?: string | null;
  bitlocker?: string | null;
  firewall_enabled?: boolean | null;
  uac_enabled?: boolean | null;
  secure_boot_enabled?: boolean | null;
  usb_storage_blocked?: boolean | null;
  weak_protocols?: Record<string, boolean> | null;
  listening_ports?: Array<Record<string, unknown>> | null;
  startup_programs?: Array<Record<string, unknown>> | null;
  rdp_enabled?: boolean | null;
  local_accounts?: Array<Record<string, unknown>> | null;
  smarts?: Array<Record<string, unknown>> | null;
}

export interface MachineSpecSnapshot {
  os_name?: string | null;
  os_version?: string | null;
  os_build?: string | null;
  os_arch?: string | null;
  os_installed_at?: string | null;
  activation_status?: string | null;
  cpu?: Record<string, unknown> | null;
  ram_gb?: number | null;
  disks?: Array<Record<string, unknown>> | null;
  gpu?: Record<string, unknown> | null;
  mainboard?: Record<string, unknown> | null;
  bios?: Record<string, unknown> | null;
  network?: NetworkInterface[] | null;
  logged_user?: string | null;
  installed_software?: Array<Record<string, unknown>> | null;
  security?: SecurityPosture | null;
  collected_at?: string | null;
}

export interface MachineDetail extends MachineListItem {
  fingerprint: Record<string, unknown>;
  note: string | null;
  latest_spec: MachineSpecSnapshot | null;
  phone_masked?: string | null;
  assigned_user_name?: string | null;
  org_name?: string | null;
}

export interface TokenListItem {
  id: string;
  full_name: string | null;
  department: string | null;
  email: string | null;
  phone_masked: string | null;
  status: TokenStatus;
  expires_at: string;
  created_at: string;
}

export interface TokenCreateResponse {
  token: string;
  install_command: string;
  expires_at: string;
}

export interface ComplianceNotice {
  id: string;
  version: string;
  title: string;
  content_md: string;
  effective_from: string;
}

export interface AuditLogEntry {
  id: number;
  actor: string | null;
  action: string;
  target: string | null;
  ts: string;
  ip: string | null;
  prev_hash: string;
  content_hash: string;
  request_id?: string | null;
  machine_id?: string | null;
}

/* ── Phase 2 ───────────────────────────────────────────────── */

export interface TimelineDaily {
  date: string;
  boots: number;
  online_sec: number;
}

export interface TimelineSession {
  start: string;
  end: string;
  duration_sec: number;
}

export interface MachineTimeline {
  machine_id: string;
  hostname: string | null;
  days: number;
  total_online_sec: number;
  sessions_count: number;
  daily: TimelineDaily[];
  sessions: TimelineSession[];
}

export type AlertRuleType = "machine_new" | "machine_lost" | "software_new" | "hardware_changed";

export interface AlertRule {
  id: string;
  name: string;
  rule_type: AlertRuleType;
  org_id: string | null;
  enabled: boolean;
  threshold_days: number | null;
  channels: string[];
  notify_targets: string[];
  created_at: string;
}

export interface AlertEvent {
  id: number;
  rule_id: string;
  machine_id: string | null;
  severity: "info" | "warning" | "critical";
  message: string;
  channels: string[];
  delivered: boolean;
  created_at: string;
}

export interface SelfServiceLink {
  id: string;
  org_id: string;
  org_name: string | null;
  code: string;
  url: string;
  enabled: boolean;
  created_at: string;
}

export interface SelfServiceInfo {
  org_id: string;
  org_name: string;
  link_id: string;
}

export interface BulkTokenItem {
  full_name?: string | null;
  department?: string | null;
  position?: string | null;
  email?: string | null;
  phone?: string | null;
  note?: string | null;
}

export interface BulkTokenResponse {
  created: number;
  tokens: TokenCreateResponse[];
}

/* ── Phase 3 ───────────────────────────────────────────────── */

export type AssetLifecycleValue = "new" | "in_use" | "in_repair" | "decommissioned";

export interface FingerprintDrift {
  id: string;
  machine_id: string;
  hostname: string | null;
  old_fingerprint: Record<string, unknown>;
  new_fingerprint: Record<string, unknown>;
  reason: "mainboard_changed" | "os_reinstall" | "other";
  status: "pending" | "approved" | "rejected";
  created_at: string;
}

export interface OfflineImportResponse {
  machine_id: string;
  hostname: string | null;
  is_new: boolean;
  verified: boolean;
  decrypted?: boolean;
  apps_count?: number | null;
  collected_at?: string | null;
  /** Người dùng hiện đang gán cho máy (nếu có). */
  assigned_user_id?: string | null;
  assigned_user_name?: string | null;
  assigned_user_email?: string | null;
  /** Org của máy — dùng để lọc danh sách user khi gán. */
  org_id?: string | null;
}

/** Request body cho `POST /api/machines/{id}/assign-user`. */
export type AssignUserMode = "existing" | "new";

export interface AssignUserRequest {
  mode: AssignUserMode;
  /** Bắt buộc nếu mode="existing". */
  user_id?: string;
  /** Bắt buộc nếu mode="new". */
  full_name?: string;
  email?: string;
  phone?: string;
  department?: string;
  note?: string;
}

export interface AssignUserResponse {
  machine_id: string;
  assigned_user_id: string;
  assigned_user_name: string;
  assigned_user_email: string;
  phone_masked: string | null;
  /** True nếu user mới được tạo ở request này. */
  was_created: boolean;
}

/** Sự kiện realtime từ WebSocket (machine:events). */
export interface MachineEvent {
  type: "machine_event";
  machine_id: string;
  status: MachineStatus;
  hostname: string | null;
  ts: string;
}

export interface RealtimeMessage {
  type: "hello" | "machine_event";
  user_id?: string;
  machine_id?: string;
  status?: MachineStatus;
  hostname?: string | null;
  ts?: string;
}

/* ── Phase 4 ───────────────────────────────────────────────── */

export interface ApiKey {
  id: string;
  name: string;
  scope: string;
  org_id: string | null;
  enabled: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  key: string; // chỉ hiện 1 lần
}

/* ── Inventory stats (`GET /api/stats/inventory`) ───────────── */

export interface StatBucket {
  /** Key nhóm đếm — chuẩn hóa: "true"/"false"/"unknown" cho bool, raw cho chuỗi. */
  key: string;
  count: number;
}

export interface TopSoftwareItem {
  name: string;
  machines: number;
}

export interface InventoryStatsResponse {
  total_machines: number;
  by_os_family: StatBucket[];
  by_os_arch: StatBucket[];
  by_is_vm: StatBucket[];
  by_ram_gb: StatBucket[];
  by_windows_update_status: StatBucket[];
  by_windows_update_enabled: StatBucket[];
  by_firewall: StatBucket[];
  by_antivirus: StatBucket[];
  by_bitlocker: StatBucket[];
  top_software: TopSoftwareItem[];
  generated_at: string;
}
/* ── User management (Super Admin) ─────────────────────────── */

export interface ManagedUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  org_id: string;
  is_2fa_enabled: boolean;
  is_active: boolean;
  created_at: string;
  org_name: string | null;
}

export interface UserCreatePayload {
  email: string;
  full_name: string;
  role: UserRole;
  org_id: string;
  password: string;
  phone?: string;
}

export interface UserUpdatePayload {
  full_name?: string;
  role?: UserRole;
  org_id?: string;
  is_active?: boolean;
  phone?: string;
}
