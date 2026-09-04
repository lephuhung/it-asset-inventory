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
  /** True = đang dùng mật khẩu mặc định/được cấp → bắt buộc đổi trước khi dùng portal. */
  must_change_password: boolean;
  last_login_at?: string | null;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  requires_2fa: boolean;
  must_change_password: boolean;
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
  /** Phân loại máy (tag classification). Công vụ thực tế = official + bmnn. */
  personal: number;
  official: number;
  bmnn: number;
}

/** Tag linh hoạt — `classification` (1 tag/máy, nguồn thống kê) | `purpose` (nhiều tag/máy). */
export interface Tag {
  id: string;
  key: string;
  label: string;
  kind: "classification" | "purpose";
  color: string | null;
  sort_order: number;
  is_system: boolean;
}

/** 3 loại máy (tag classification hệ thống). */
export type MachineClassification = "personal" | "official" | "bmnn";

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
  tags?: Tag[];
  platform?: string | null;
  agent_version?: string | null;
  public_ip?: string | null;
  velociraptor_client_id?: string | null;
  velociraptor_last_seen_at?: string | null;
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
  install_command: string; // back-compat: Windows PowerShell MSI command
  install_command_windows?: string; // PowerShell -EncodedCommand — cài CẢ 2 (OrgInventory + Velociraptor)
  install_command_windows_org_only?: string; // PowerShell -EncodedCommand — cài CH� OrgInventory (không Velociraptor)
  install_command_linux?: string; // curl | bash one-liner — auto-detect .deb / .rpm
  install_offline_url?: string; // gói USB .zip cho máy cách ly (chế độ 2)
  install_url_warnings?: string[]; // cảnh báo khi portal/agent URL chưa public (localhost)
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
  template_code: string;
  template_name: string | null;
  org_id: string | null;
  scope_mode: "org_only" | "org_tree" | "system";
  recipient_mode: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
}

export interface AlertEvent {
  id: number;
  rule_id: string;
  template_code: string;
  machine_id: string | null;
  org_id: string | null;
  severity: string;
  title: string;
  body: string | null;
  recipient_user_ids: string[];
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

/** Payload tạo token — kèm loại máy (classification) + tag mục đích (purpose). */
export interface TokenCreatePayload {
  org_id: string;
  full_name?: string | null;
  department?: string | null;
  position?: string | null;
  email?: string | null;
  phone?: string | null;
  note?: string | null;
  ttl_hours?: number;
  classification?: MachineClassification;
  purpose_tags?: string[];
}

export interface BulkTokenPayload {
  org_id: string;
  items: BulkTokenItem[];
  ttl_hours?: number;
  classification?: MachineClassification;
  purpose_tags?: string[];
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
  /** Lần đăng nhập gần nhất — null = chưa kích hoạt. */
  last_login_at: string | null;
  must_change_password: boolean;
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

/* ── Velociraptor (DFIR — tích hợp từ backend FastAPI) ────────── */

export interface VelociraptorConfig {
  enabled: boolean;
  server_url: string | null;
  /** mTLS — cần authenticator.type: Certs phía Velociraptor Server. */
  client_config_set: boolean;
  client_cert_info: Record<string, unknown> | null;
  /** HTTP Basic — Velociraptor default authenticator. */
  basic_auth_set: boolean;
  /** Legacy Bearer token (đã deprecated). */
  api_token_set: boolean;
  allowlist: string[];
  last_sync_at: string | null;
  last_sync_error: string | null;
  last_sync_linked: number | null;
  last_sync_total: number | null;
  updated_at: string | null;
  updated_by: string | null;
  defaults_server_url: string | null;
  defaults_allowlist: string[];
}

export interface VelociraptorConfigUpdate {
  enabled?: boolean | null;
  server_url?: string | null;
  /** YAML từ `velociraptor config api_client` — cho mTLS. */
  client_config?: string | null;
  /** HTTP Basic username (Velociraptor default authenticator). */
  username?: string | null;
  /** HTTP Basic password. Để trống để KHÔNG đ�i; "" để xoá. */
  password?: string | null;
  /** Legacy Bearer token (đã deprecated). */
  api_token?: string | null;
  allowlist?: string[] | null;
}

export interface VelociraptorTestResult {
  ok: boolean;
  error: string | null;
  client_count_sampled: number | null;
  server_url: string | null;
  mcp?: DeepAgentTestResult | null;
}

/** Artifact Custom.* do Super Admin nạp lên Velociraptor (GET /api/admin/velociraptor/artifacts). */
export interface VelociraptorArtifact {
  id: string;
  name: string;
  sha256: string;
  artifact_type: string;
  enabled: boolean;
  supported_platforms: Array<"windows" | "linux" | "macos">;
  selection_priority: number;
  /** Artifact đã hiện diện trên Velociraptor server (verify qua artifact_definitions). */
  on_server: boolean;
  last_push_status: string | null;
  last_push_error: string | null;
  updated_at: string;
}

export interface VelociraptorLink {
  machine_id: string;
  client_id: string;
  hostname: string;
  os_info: Record<string, unknown> | null;
  last_seen_at: string | null;
  synced_at: string;
  machine_hostname?: string | null;
  machine_status?: MachineStatus | null;
  machine_org_name?: string | null;
  machine_last_seen_at?: string | null;
}

/** Kết quả on-demand lookup hostname → Velociraptor client_id (không qua DB cache). */
export interface VelociraptorLookup {
  matched: boolean;
  client_id: string | null;
  hostname: string | null;
  os_info: Record<string, unknown> | null;
  raw_count: number;
}

/** Trạng thái Velociraptor Server (ping trực tiếp, không cache). */
export interface VelociraptorStatus {
  reachable: boolean;
  reason?: string | null;
  server_url?: string | null;
  client_count_sampled?: number;
  checked_at?: string;
}

export interface DfirHuntCreate {
  artifact: string;
  scope: "all" | "single";
  machine_id?: string | null;
  name?: string | null;
  description?: string | null;
  notes?: string | null;
}

export interface DfirHunt {
  id: string;
  hunt_id: string | null;
  artifact: string;
  scope: "all" | "single";
  machine_id: string | null;
  requested_by: string;
  status: string;
  velociraptor_url: string | null;
  notes: string | null;
  error: string | null;
  created_at: string;
  client_count: number | null;
}

/** Kết quả live từ Velociraptor Server (GET /api/admin/velociraptor/hunt/{id}). */
export interface VelociraptorHuntLive {
  hunt_id: string;
  velociraptor_status: Record<string, unknown>;
  db_record: {
    id: string;
    artifact: string;
    scope: "all" | "single";
    machine_id: string | null;
    requested_by: string;
    status: string;
    created_at: string;
    notes: string | null;
    error: string | null;
  } | null;
  velociraptor_url: string | null;
}

/** 1 Velociraptor flow (hunt/collection/interrogation) — live từ Velociraptor API. */
export interface VelociraptorClientFlow {
  State: string | null;
  FlowId: string | null;
  Artifacts: string[];
  Created: number | null;
  LastActive: number | null;
  Creator: string | null;
  Mb: number | null;
  Rows: number | null;
}

/** Velociraptor client metadata (live t� GetClient API). */
export interface VelociraptorClientMetadata {
  client_id: string;
  agent_information: Record<string, unknown> | null;
  os_info: {
    system?: string;
    hostname?: string;
    fqdn?: string;
    release?: string;
    machine?: string;
    mac_addresses?: string[];
  } | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  last_ip: string | null;
  last_interrogate_flow_id: string | null;
  last_interrogate_artifact_name: string | null;
}

/**
 * 1 artifact trong bảng "Top 10 sự kiện DFIR" (trang máy).
 * source: reused (tái sử dụng flow FINISHED cũ) | running | collected
 *         | missing (chưa có dữ liệu) | error
 */
export interface VelociraptorTop10Artifact {
  artifact: string;
  label: string;
  flow_id: string | null;
  source: "reused" | "running" | "collected" | "missing" | "error";
  error: string | null;
  rows: Array<Record<string, unknown>>;
  total_rows: number;
}

/** GET /api/admin/velociraptor/clients/{client_id}/top10 */
export interface VelociraptorTop10Response {
  client_id: string;
  generated_at: string;
  artifacts: VelociraptorTop10Artifact[];
  flows: VelociraptorClientFlow[];
}

/** 1 artifact trong response POST /top10/collect. */
export interface VelociraptorTop10CollectArtifact {
  artifact: string;
  label: string;
  status: "reused" | "collecting" | "not_allowed" | "missing" | "error";
  flow_id: string | null;
  error: string | null;
}

/** POST /api/admin/velociraptor/clients/{client_id}/top10/collect */
export interface VelociraptorTop10CollectResponse {
  client_id: string;
  started_at: string;
  artifacts: VelociraptorTop10CollectArtifact[];
}

/** Scheduled DFIR hunt (chạy artifact định k�). */
export interface VelociraptorSchedule {
  id: string;
  name: string;
  artifact: string;
  scope: "all" | "multi";
  machine_ids: string[] | null;
  interval_seconds: number;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string;
  last_status: string | null;
  last_error: string | null;
  requested_by: string;
  created_at: string;
}

export interface VelociraptorScheduleCreate {
  name: string;
  artifact: string;
  scope?: "all" | "multi";
  machine_ids?: string[] | null;
  interval_seconds: number;
}

export interface VelociraptorScheduleUpdate {
  name?: string;
  interval_seconds?: number;
  enabled?: boolean;
}

/** DFIR alert khi có flow sensitive xuất hiện. */
export interface VelociraptorAlert {
  id: string;
  artifact_pattern: string;
  severity: "info" | "warning" | "critical";
  flow_id: string;
  client_id: string | null;
  machine_id: string | null;
  message: string;
  resolved: boolean;
  created_at: string;
}

/* ── Thống kê máy theo tag (org-machine-stats) ───────────────── */

/** Số máy mang 1 tag trong 1 tổ chức. */
export interface TagOrgStat {
  org_id: string;
  org_name: string;
  org_type: string;
  count: number;
}

/** 1 tag + số máy đang mang (toàn hệ thống + phân bố theo tổ chức). */
export interface TagStatItem {
  id: string;
  key: string;
  label: string;
  kind: string;
  color: string | null;
  count: number;
  org_stats: TagOrgStat[];
}

export interface TagStatsResponse {
  total_machines: number;
  tags: TagStatItem[];
}


// ── LLM-DFIR (AI Assistant) ──────────────────────────────────────

export interface LlmConfig {
  enabled: boolean;
  provider: string;
  base_url: string;
  api_key_masked: string;
  model: string;
  fallback_model: string | null;
  system_prompt: string | null;
  max_tokens: number;
  temperature: number;
  request_timeout: number;
  max_context_chars: number;
  allow_cloud: boolean;
  external_orchestrator: string;
  deepagent_enabled: boolean;
  deepagent_url: string | null;
  deepagent_service_token_set: boolean;
  daily_token_budget: number | null;
  tokens_used_today: number;
  test_status: string | null;
  test_error: string | null;
  test_at: string | null;
  updated_at: string;
  available_models: string[];
}

export interface LlmConfigUpdate {
  enabled?: boolean | null;
  provider?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  model?: string | null;
  fallback_model?: string | null;
  system_prompt?: string | null;
  max_tokens?: number | null;
  temperature?: number | null;
  request_timeout?: number | null;
  max_context_chars?: number | null;
  allow_cloud?: boolean | null;
  external_orchestrator?: string | null;
  deepagent_enabled?: boolean | null;
  deepagent_url?: string | null;
  deepagent_service_token?: string | null;
  daily_token_budget?: number | null;
}

export interface LlmTestResult {
  ok: boolean;
  latency_ms: number;
  models: string[];
  error: string | null;
}

export interface LlmModelsResult {
  models: string[];
}

export interface DeepAgentTestResult {
  ok: boolean;
  service_ok: boolean;
  mcp_ok: boolean;
  tools: string[];
  client_count_sampled: number | null;
  error: string | null;
}

export type InvestigationStatus =
  | "pending"
  | "running"
  | "collecting"
  | "analyzing"
  | "completed"
  | "failed";

export type InvestigationSeverity = "critical" | "high" | "medium" | "low" | "info";

export interface DfirInvestigation {
  id: string;
  machine_id: string;
  machine_hostname: string | null;
  status: InvestigationStatus;
  artifacts: string[];
  llm_provider: string | null;
  llm_model: string | null;
  severity: InvestigationSeverity | null;
  findings: any[] | null;
  iocs: any[] | null;
  findings_count: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_usd: number | null;
  error: string | null;
  report_markdown: string | null;
  external_orchestrator: string | null;
  hermes_status: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  requested_by: string;
}

export interface DfirInvestigationCreate {
  machine_id: string;
  artifacts?: string[] | null;
  custom_instructions?: string | null;
}

export interface DfirInvestigationMessage {
  id: string;
  role: "system" | "user" | "assistant";
  content: string;
  tokens: number | null;
  created_at: string;
}

// ── Notifications ─────────────────────────────────────────────

export type NotificationSeverity = "info" | "success" | "warning" | "error" | "critical";
export type NotificationCategory =
  | "investigation" | "alert" | "system" | "machine" | "security" | "message";
export type NotificationSource = "user" | "system" | "hermes" | "velociraptor" | "agent";

export interface NotificationOut {
  id: string;
  source: NotificationSource | string;
  category: NotificationCategory | string;
  severity: NotificationSeverity | string;
  title: string;
  body: string | null;
  link: string | null;
  entity_type: string | null;
  entity_id: string | null;
  read_at: string | null;
  created_at: string;
  sender_name: string | null;
}

export interface TelegramLinkStartOut {
  bot_url: string;
  linking_token: string;
  expires_at: string;
}

export interface TelegramLinkStatusOut {
  linked: boolean;
  telegram_chat_id: string | null;
  linked_at: string | null;
}

/** Cấu hình bot Telegram (Super Admin) — token + secret đều được mask ở backend. */
export interface TelegramBotConfigOut {
  configured: boolean;
  bot_username: string | null;
  bot_token_set: boolean;
  bot_token_masked: string | null;
  webhook_secret_set: boolean;
  webhook_secret_masked: string | null;
  enabled: boolean;
  /** `db` | `env` | `none` */
  source: string;
  updated_at: string | null;
  updated_by: string | null;
  /** URL callback đầy đủ để submit cho @BotFather. */
  callback_url: string;
  /** Snippet curl để set webhook (kèm secret_token nếu có). null nếu chưa có token. */
  webhook_set_command: string | null;
  /** Snippet curl để xem trạng thái webhook hiện tại. */
  webhook_check_command: string | null;
}

export interface TelegramBotConfigUpdateIn {
  bot_token?: string | null;
  bot_username?: string | null;
  webhook_secret?: string | null;
  enabled?: boolean | null;
}

export interface TelegramBotConfigTestOut {
  ok: boolean;
  bot_id: number | null;
  bot_username: string | null;
  error: string | null;
}

/** 1 user đã liên kết Telegram — hiển thị cho Super Admin. */
export interface TelegramLinkedUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  org_id: string;
  org_name: string | null;
  telegram_chat_id: string;
  telegram_linked_at: string | null;
  is_active: boolean;
}

// ── LLM-DFIR Statistics & Pagination ───────────────────────────

export interface DfirInvestigationListOut {
  items: DfirInvestigation[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface DfirStatsByMachine {
  machine_id: string;
  hostname: string | null;
  count: number;
  critical: number;
}

export interface DfirStatsDaily {
  date: string;
  total: number;
  critical: number;
}

export interface DfirStatsTopFinding {
  mitre_id: string;
  title: string;
  count: number;
}

export interface DfirInvestigationStats {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  by_machine: DfirStatsByMachine[];
  recent_24h: number;
  recent_7d: number;
  avg_duration_seconds: number | null;
  daily_counts: DfirStatsDaily[];
  top_findings: DfirStatsTopFinding[];
}

// ── Alert engine redesign (templates / scope / recipients) ─────

export interface AlertTemplate {
  id: string;
  code: string;
  name: string;
  description: string | null;
  category: string; // machine | investigation | security | system
  default_severity: string;
  title_template: string;
  body_template: string | null;
  opt_out_controls: string[]; // ["template"] | ["severity"] | [...]
  allowed_vars: string[];
  default_config: Record<string, unknown>;
  enabled: boolean;
  updated_at: string;
}

export interface AlertTemplatePreview {
  title: string;
  body: string | null;
  warnings: string[];
}

export interface AlertRuleTestResult {
  template_code: string;
  title: string;
  body: string | null;
  recipients: Array<{
    user_id: string;
    email: string;
    full_name: string;
    telegram_linked: boolean;
  }>;
  total_recipients: number;
  warnings: string[];
}

export interface UserNotificationPref {
  template_code: string;
  template_name: string;
  category: string;
  default_severity: string;
  opt_out_controls: string[];
  muted: boolean;
  min_severity: string | null;
}
