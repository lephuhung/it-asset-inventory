"""Pydantic schemas — phân tách rõ request/response."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.db.models import MachineStatus, TokenStatus

# ── Auth ──────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = Field(default=None, max_length=6)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    requires_2fa: bool = False  # True khi user đã bật 2FA nhưng chưa nhập code


class TotpSetupResponse(BaseModel):
    secret: str
    uri: str
    backup_codes: list[str]


class TotpConfirmRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Enrollment ────────────────────────────────────────────────────


class FingerprintPayload(BaseModel):
    smbios_uuid: str | None = None
    machine_guid: str | None = None
    mainboard_serial: str | None = None


class EnrollRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=64)
    fingerprint: FingerprintPayload
    csr_pem: str = Field(..., description="Client cert CSR (PEM) — ECDSA P-256")
    hostname: str | None = Field(default=None, max_length=255)


class EnrollResponse(BaseModel):
    machine_id: uuid.UUID
    client_cert_pem: str
    ca_cert_pem: str | None = None
    renew_after: datetime
    is_new_machine: bool
    status: MachineStatus
    # Cấu hình agent + URL kênh mTLS (agent liên hệ sau enroll)
    agent_server_url: str | None = None
    heartbeat_interval_seconds: int | None = None
    heartbeat_jitter_seconds: int | None = None
    inventory_interval_hours: int | None = None


# ── Heartbeat ─────────────────────────────────────────────────────


class HeartbeatRequest(BaseModel):
    logged_user: str | None = Field(default=None, max_length=255)
    uptime_sec: int | None = Field(default=None, ge=0)
    ip: str | None = None


class HeartbeatResponse(BaseModel):
    ok: bool = True
    server_time: datetime
    renew_after: datetime | None = None
    rescan_requested: bool = False  # Phase 3: on-demand rescan
    notice_version: str | None = None  # Thông báo tuân thủ hiện hành
    # Cấu hình agent — server điều chỉnh, agent đồng bộ (heartbeat interval/jitter...)
    heartbeat_interval_seconds: int | None = None
    heartbeat_jitter_seconds: int | None = None


# ── Inventory ─────────────────────────────────────────────────────
# Schema khớp đúng payload agent Windows đẩy lên (xem docs/API_CONTRACT.md).
# Mọi trường optional — agent không đọc được (WMI/Registry lỗi) → bỏ trống.


class NetworkInterface(BaseModel):
    name: str | None = None
    ip: str | None = None
    mac: str | None = None
    is_dual_homed: bool = False
    gateway: str | None = None
    dhcp_enabled: bool | None = None
    dns_servers: list[str] | None = None
    speed_mbps: int | None = Field(default=None, ge=0)


class CpuInfo(BaseModel):
    model: str | None = None
    cores: int | None = Field(default=None, ge=1)
    threads: int | None = Field(default=None, ge=1)
    clock_mhz: int | None = Field(default=None, ge=0)
    virtualization_enabled: bool | None = None


class DiskPartition(BaseModel):
    drive_letter: str | None = None
    total_bytes: int | None = Field(default=None, ge=0)
    free_bytes: int | None = Field(default=None, ge=0)
    file_system: str | None = None


class DiskInfo(BaseModel):
    model: str | None = None
    serial: str | None = None  # v1 (cũ): serial ổ cứng
    size_bytes: int | None = Field(default=None, ge=0)
    size: int | None = Field(default=None, ge=0)  # alias của size_bytes (agent mới gửi cả hai)
    size_gb: float | None = Field(default=None, ge=0)  # v1 (cũ): dung lượng GB
    type: str | None = None  # v1 (cũ): SSD | HDD | NVMe
    bus_type: str | None = None  # NVMe | SATA | SAS | ...
    media_type: str | None = None  # SSD | HDD | ...
    smart_health: str | None = None  # OK | caution | ...
    partitions: list[DiskPartition] | None = None


class GpuInfo(BaseModel):
    model: str | None = None
    driver_version: str | None = None
    memory_mb: int | None = Field(default=None, ge=0)


class MainboardInfo(BaseModel):
    model: str | None = None  # v1 (cũ): "model" = manufacturer + product
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = None
    version: str | None = None


class BiosInfo(BaseModel):
    vendor: str | None = None
    version: str | None = None
    release_date: str | None = None
    smbios_version: str | None = None


class InstalledSoftware(BaseModel):
    display_name: str | None = None
    name: str | None = None  # v1 (cũ) / alias của display_name
    version: str | None = None
    publisher: str | None = None
    install_date: str | None = None
    uninstall_string: str | None = None
    is_per_user: bool | None = None


class AntivirusInfo(BaseModel):
    displayName: str | None = None
    name: str | None = None  # v1 (cũ) / alias của displayName
    status: str | None = None  # v1 (cũ): enabled | disabled
    enabled: bool | None = None
    upToDate: bool | None = None


class LocalAccountInfo(BaseModel):
    username: str | None = None
    name: str | None = None  # v1 (cũ) / alias của username
    full_name: str | None = None
    disabled: bool | None = None
    has_password: bool | None = None
    is_admin: bool | None = None


class SmartDeviceInfo(BaseModel):
    device: str | None = None
    model: str | None = None
    health: str | None = None


class WeakProtocols(BaseModel):
    smbv1_disabled: bool | None = None
    tls10_disabled: bool | None = None
    tls11_disabled: bool | None = None
    ssl3_disabled: bool | None = None


class ListeningPort(BaseModel):
    port: int | None = Field(default=None, ge=0, le=65535)
    protocol: str | None = None  # TCP | UDP
    address: str | None = None


class StartupProgram(BaseModel):
    name: str | None = None
    command: str | None = None
    location: str | None = None  # HKLM_Run | HKCU_Run | ...


class SecurityPosture(BaseModel):
    antivirus: list[AntivirusInfo] | None = None
    windows_update_status: str | None = None
    bitlocker: str | None = None
    firewall_enabled: bool | None = None
    uac_enabled: bool | None = None
    secure_boot_enabled: bool | None = None
    usb_storage_blocked: bool | None = None
    weak_protocols: WeakProtocols | None = None
    listening_ports: list[ListeningPort] | None = None
    startup_programs: list[StartupProgram] | None = None
    rdp_enabled: bool | None = None
    local_accounts: list[LocalAccountInfo] | None = None
    smarts: list[SmartDeviceInfo] | None = None  # SMART cơ bản


class InventoryRequest(BaseModel):
    os_name: str | None = None
    os_version: str | None = None
    os_build: str | None = None
    os_arch: str | None = None
    os_installed_at: datetime | None = None
    activation_status: str | None = None
    cpu: CpuInfo | None = None
    ram_gb: float | None = None
    disks: list[DiskInfo] | None = None
    gpu: GpuInfo | None = None
    mainboard: MainboardInfo | None = None
    bios: BiosInfo | None = None
    network: list[NetworkInterface] | None = None
    logged_user: str | None = None
    installed_software: list[InstalledSoftware] | None = None
    security: SecurityPosture | None = None
    is_vm: bool | None = None
    config_hash: str | None = Field(default=None, max_length=64)


class InventoryResponse(BaseModel):
    ok: bool = True
    config_changed: bool = False


# ── Tokens ────────────────────────────────────────────────────────


class TokenCreateRequest(BaseModel):
    org_id: uuid.UUID
    full_name: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20, description="Tùy chọn, mã hóa AES-256-GCM")
    note: str | None = None
    ttl_hours: int = Field(default=72, ge=1, le=720)


class TokenCreateResponse(BaseModel):
    token: str  # chỉ hiện 1 lần
    install_command: str
    expires_at: datetime


class TokenListItem(BaseModel):
    id: uuid.UUID
    full_name: str | None
    department: str | None
    email: str | None
    phone_masked: str | None
    status: TokenStatus
    expires_at: datetime
    created_at: datetime


class TokenRevokeRequest(BaseModel):
    token_id: uuid.UUID


# ── Machines ──────────────────────────────────────────────────────


class MachineListItem(BaseModel):
    id: uuid.UUID
    hostname: str | None
    machine_uuid: str
    status: MachineStatus
    lifecycle: str
    is_vm: bool | None
    last_seen_at: datetime | None
    enrolled_at: datetime
    org_id: uuid.UUID
    assigned_user_id: uuid.UUID | None
    logged_user: str | None = None  # user Windows đang đăng nhập (từ snapshot mới nhất)


class MachineDetail(MachineListItem):
    fingerprint: dict
    note: str | None
    latest_spec: dict | None = None
    phone_masked: str | None = None
    assigned_user_name: str | None = None
    org_name: str | None = None


# ── Organizations (cây tổ chức) ─────────────────────────────────


class OrganizationCreate(BaseModel):
    """Tạo tổ chức: UBND cấp xã / Sở ban ngành / phòng / đơn vị trực thuộc."""

    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., description="ubnd_xa | so_ban_nganh | phong | don_vi")
    parent_id: uuid.UUID | None = Field(default=None, description="Cấp trên (None = cấp gốc)")


class OrganizationNode(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    type: str
    children: list[OrganizationNode] = []


# ── Stats ─────────────────────────────────────────────────────────


class StatsOverview(BaseModel):
    total_machines: int
    online: int
    offline: int
    lost: int
    pending_tokens: int
    expired_tokens: int


class StatBucket(BaseModel):
    """1 nhóm đếm: key chuẩn hóa ("true"/"false"/"unknown" cho bool) + số lượng."""

    key: str
    count: int


class TopSoftwareItem(BaseModel):
    """1 app trong bảng xếp hạng "cài nhiều nhất" — số máy cài (distinct)."""

    name: str
    machines: int


class InventoryStatsResponse(BaseModel):
    """Thống kê cấu hình 'hiện tại' — đọc từ machine_current / machine_software (GROUP BY SQL).

    Nguồn dữ liệu: snapshot mới nhất của từng máy (không phải lịch sử machine_specs).
    `unknown` = máy chưa gửi trường đó (agent cũ / trường cần admin).
    """

    total_machines: int
    by_os_family: list[StatBucket] = []
    by_os_arch: list[StatBucket] = []
    by_is_vm: list[StatBucket] = []
    by_ram_gb: list[StatBucket] = []
    by_windows_update_status: list[StatBucket] = []
    by_windows_update_enabled: list[StatBucket] = []
    by_firewall: list[StatBucket] = []
    by_antivirus: list[StatBucket] = []
    by_bitlocker: list[StatBucket] = []
    top_software: list[TopSoftwareItem] = []
    generated_at: datetime


# ── Agent config ───────────────────────────────────────────────


class AgentConfigResponse(BaseModel):
    """Cấu hình agent lấy từ GET /api/agent/config (sau khi có client cert)."""

    server_url: str
    heartbeat_interval_seconds: int
    heartbeat_jitter_seconds: int
    online_ttl_seconds: int
    inventory_interval_hours: int
    renew_before_percent: int
    server_time: datetime


# ── Alert rules (Phase 2) ────────────────────────────────────────


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    rule_type: str = Field(..., description="machine_new | machine_lost | software_new | hardware_changed")
    org_id: uuid.UUID | None = Field(default=None, description="None = toàn hệ thống")
    enabled: bool = True
    threshold_days: int | None = Field(default=None, ge=1, le=365, description="machine_lost")
    channels: list[str] = Field(default_factory=lambda: ["email"])
    notify_targets: list[str] = Field(default_factory=list)


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    threshold_days: int | None = None
    channels: list[str] | None = None
    notify_targets: list[str] | None = None


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    rule_type: str
    org_id: uuid.UUID | None
    enabled: bool
    threshold_days: int | None
    channels: list[str]
    notify_targets: list[str]
    created_at: datetime


class AlertEventOut(BaseModel):
    id: int
    rule_id: uuid.UUID
    machine_id: uuid.UUID | None
    severity: str
    message: str
    channels: list[str]
    delivered: bool
    created_at: datetime


# ── Self-service (chế độ B) ─────────────────────────────────────


class SelfServiceLinkCreate(BaseModel):
    org_id: uuid.UUID


class SelfServiceToggle(BaseModel):
    enabled: bool = True


class SelfServiceLinkOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    org_name: str | None = None
    code: str
    url: str
    enabled: bool
    created_at: datetime


class SelfServiceClaimRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    note: str | None = None


class SelfServiceInfoOut(BaseModel):
    org_id: uuid.UUID
    org_name: str
    link_id: uuid.UUID


# ── Bulk import CSV ─────────────────────────────────────────────


class BulkTokenItem(BaseModel):
    full_name: str | None = None
    department: str | None = None
    position: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    note: str | None = None


class BulkTokenRequest(BaseModel):
    org_id: uuid.UUID
    items: list[BulkTokenItem] = Field(..., min_length=1, max_length=500)
    ttl_hours: int = Field(default=72, ge=1, le=720)


class BulkTokenResponse(BaseModel):
    created: int
    tokens: list[TokenCreateResponse]


# ── Phase 3: lifecycle, approvals, drift, rescan, offline import ──


class MachineLifecycleUpdate(BaseModel):
    lifecycle: str = Field(..., description="new | in_use | in_repair | decommissioned")
    note: str | None = Field(default=None, max_length=1000)


class MachineDecision(BaseModel):
    """Duyệt / từ chối máy chờ duyệt (pending approval) hoặc drift."""

    note: str | None = Field(default=None, max_length=1000)


class FingerprintDriftOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID
    hostname: str | None = None
    old_fingerprint: dict
    new_fingerprint: dict
    reason: str
    status: str
    created_at: datetime


class OfflineImportRequest(BaseModel):
    """File máy cách ly (chế độ offline USB) — payload JSON ký ECDSA.

    `payload` là dict: {machine_uuid, hostname, fingerprint, spec{...}, exported_at}.
    `signature_b64`: chữ ký ECDSA (DER, base64) trên SHA-256 của JSON canonical payload.
    `public_key_pem`: khóa công khai tương ứng (thường là client cert public key).
    """

    payload: dict
    signature_b64: str
    public_key_pem: str


class OfflineImportResponse(BaseModel):
    machine_id: uuid.UUID
    hostname: str | None
    is_new: bool
    verified: bool


# ── Compliance ────────────────────────────────────────────────────


# ── API keys (Phase 4) ─────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scope: str = Field(default="read:machines", description="read:machines")
    org_id: uuid.UUID | None = Field(default=None, description="None = toàn hệ thống (Super Admin)")


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    scope: str
    org_id: uuid.UUID | None
    enabled: bool
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str  # chỉ hiện 1 lần


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    scope: str | None = None
    enabled: bool | None = None


class ComplianceNoticeResponse(BaseModel):
    id: uuid.UUID
    version: str
    title: str
    content_md: str
    effective_from: datetime


class AcknowledgeRequest(BaseModel):
    notice_id: uuid.UUID


# ── User management (SuperAdmin) ─────────────────────────────


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    org_id: uuid.UUID
    is_2fa_enabled: bool
    is_active: bool
    created_at: datetime
    org_name: str | None = None
    last_login_at: datetime | None = None


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., pattern="^(super_admin|org_admin|viewer|admin_global|admin_org)$")
    org_id: uuid.UUID
    password: str = Field(..., min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=20)


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, pattern="^(super_admin|org_admin|viewer|admin_global|admin_org)$")
    org_id: uuid.UUID | None = None
    is_active: bool | None = None
    phone: str | None = Field(default=None, max_length=20)


class UserResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


# ── Cấu hình agent (portal Vận hành → Cấu hình Agent) ───────────


class AgentSettingsUpdate(BaseModel):
    """Super Admin chỉnh cấu hình agent từ portal. Trường `None` = về mặc định env."""

    heartbeat_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    heartbeat_jitter_seconds: int | None = Field(default=None, ge=0, le=600)
    inventory_interval_hours: int | None = Field(default=None, ge=1, le=168)
    agent_server_url: str | None = Field(default=None, max_length=512)


class AgentSettingsOut(BaseModel):
    """Cấu hình hiệu lực + giá trị mặc định env + nguồn của từng trường."""

    # Giá trị hiệu lực (agent đang nhận)
    heartbeat_interval_seconds: int
    heartbeat_jitter_seconds: int
    online_ttl_seconds: int
    inventory_interval_hours: int
    renew_before_percent: int
    agent_server_url: str

    # Giá trị mặc định env (để so sánh / hoàn tác)
    defaults: dict[str, int | str]
    overridden: dict[str, bool]
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None


# ── Thống kê máy theo tổ chức (agent vs cách ly) ─────────────────


class OrgMachineStat(BaseModel):
    """Số máy của 1 tổ chức, tách theo có agent (có heartbeat) / cách ly."""

    org_id: uuid.UUID
    org_name: str
    org_type: str
    total: int
    with_agent: int  # đã gửi heartbeat ít nhất 1 lần → đang cài agent
    isolated: int  # không bao giờ heartbeat → import offline (máy cách ly)
    pending: int  # chờ duyệt enroll — chưa thuộc nhóm nào
