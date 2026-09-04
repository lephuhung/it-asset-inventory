"""Pydantic schemas — phân tách rõ request/response."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.db.models import MachineStatus, TokenStatus

# ── Tags ───────────────────────────────────────────────────────────


class TagOut(BaseModel):
    """Tag hiển thị — `kind='classification'` là 3 loại máy (1 tag/máy);
    `kind='purpose'` là tag mục đích (nhiều tag/máy, không ảnh hưởng thống kê)."""

    id: uuid.UUID
    key: str
    label: str
    kind: str  # classification | purpose
    color: str | None = None
    sort_order: int = 0
    is_system: bool = False


class TagCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)
    kind: str = Field(..., pattern="^(classification|purpose)$")
    key: str | None = Field(default=None, max_length=64)  # bỏ trống → tự sinh slug từ label
    color: str | None = Field(default=None, max_length=128)  # class badge tailwind


class MachineTagSetRequest(BaseModel):
    """Gán tag cho 1 máy. `classification` bắt buộc 1 trong 3 key.
    `purpose` = None → không đụng; [] → xóa hết tag mục đích; list → thay toàn bộ."""

    classification: str | None = None  # personal | official | bmnn
    purpose: list[str] | None = None


class BulkTagRequest(BaseModel):
    machine_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    classification: str | None = None
    purpose: list[str] | None = None  # None = không đụng; [] = xóa hết tag mục đích


# ── Auth ──────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)  # Hỗ trợ cả email và username
    password: str
    totp_code: str | None = Field(default=None, max_length=6)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    requires_2fa: bool = False  # True khi user đã bật 2FA nhưng chưa nhập code
    must_change_password: bool = False  # True = đang dùng MK mặc định → bắt buộc đổi ngay


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
    server_url: str | None = None
    agent_server_url: str | None = None
    inventory_interval_hours: int | None = None
    renew_before_percent: int | None = None
    # Hash cấu hình agent server đang áp dụng. Agent so sánh với hash cũ trong state:
    #   - khớp → heartbeat bình thường, không gọi lại /api/agent/config
    #   - KHÁC  → gọi GET /api/agent/config ngay để đồng bộ cấu hình mới nhất
    # Cho phép agent nhận thay đổi cấu hình từ portal trong vòng ~30s thay vì 6h.
    agent_config_hash: str | None = None



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
    model_config = ConfigDict(extra="allow")  # allow v4 envelope fields (update, remote_access, etc.)
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
    # v4 envelope fields (additive optional — server fallback khi thiếu)
    update: dict | None = None
    remote_access: dict | None = None
    disk_encryption: dict | None = None
    endpoint_protection: list[AntivirusInfo] | None = None
    privilege_control: dict | None = None


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
    # v4 envelope fields (additive — server fallback khi thiếu)
    inventory_schema_version: int | None = None
    agent: dict | None = None
    os: dict | None = None
    # IP public (WAN) — IPv4 hoặc IPv6. Agent phát hiện qua dịch vụ echo IP public
    # (vd: ipify.org, ifconfig.me) và cache 24h. Null nếu agent không phát hiện được
    # (vd: máy chỉ có IPv6 link-local, NAT không echo được, hoặc offline khi collect).
    public_ip: str | None = Field(default=None, max_length=45)
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
    # Loại máy + tag mục đích — áp cho máy khi enroll (mặc định công vụ).
    classification: str | None = Field(default=None, pattern="^(personal|official|bmnn)$")
    purpose_tags: list[str] = Field(default_factory=list)


class TokenCreateResponse(BaseModel):
    token: str  # chỉ hiện 1 lần
    install_command: str  # back-compat: Windows PowerShell MSI (default = cài CẢ 2)
    install_command_windows: str | None = None  # PowerShell -EncodedCommand — CẢ 2 (OrgInventory + Velociraptor)
    install_command_windows_org_only: str | None = None  # PowerShell -EncodedCommand — CHỈ OrgInventory (legacy)
    install_command_linux: str | None = None  # curl | bash one-liner (.deb / .rpm auto-detect)
    install_offline_url: str | None = None  # gói USB .zip cho máy cách ly (chế độ 2)
    install_url_warnings: list[str] = []  # cảnh báo khi portal/agent URL chưa public (localhost)
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
    public_ip: str | None = None  # IP public (WAN) mới nhất agent báo cáo
    platform: str | None = None  # "windows" | "linux" (từ envelope v4)
    agent_version: str | None = None  # phiên bản agent (từ envelope v4)
    tags: list[TagOut] = []  # toàn bộ tag máy (classification + purpose)
    velociraptor_client_id: str | None = None  # Velociraptor client_id (NULL = chưa enroll Velociraptor)
    velociraptor_last_seen_at: datetime | None = None  # lần cuối Velociraptor gửi data về server


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
    # Phân loại máy (theo tag classification — nguồn duy nhất của thống kê này).
    # công vụ = official + bmnn (BMNN là tập con công vụ); cá nhân = personal.
    # Tag mục đích (purpose) KHÔNG bao giờ đụng vào các số này.
    personal: int = 0
    official: int = 0
    bmnn: int = 0


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
    # v4 cross-platform buckets
    by_platform: list[StatBucket] = []
    by_update_status: list[StatBucket] = []
    by_disk_encryption: list[StatBucket] = []
    by_endpoint_protection: list[StatBucket] = []
    by_ssh_enabled: list[StatBucket] = []
    by_remote_desktop: list[StatBucket] = []
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
    # Hash SHA-256 hex của canonical JSON cấu hình trên. Agent lưu vào state để
    # so sánh với `agent_config_hash` trong heartbeat response → phát hiện đổi cấu hình.
    agent_config_hash: str | None = None


# ── Alert engine redesign (Phase 2 v2) ─────────────────────────


class AlertTemplateOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str
    default_severity: str
    title_template: str
    body_template: str | None
    opt_out_controls: list[str]
    allowed_vars: list[str]
    default_config: dict
    enabled: bool
    updated_at: datetime


class AlertTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    default_severity: str | None = Field(default=None, pattern="^(info|success|warning|error|critical)$")
    title_template: str | None = Field(default=None, min_length=1)
    body_template: str | None = None
    opt_out_controls: list[str] | None = None
    allowed_vars: list[str] | None = None
    default_config: dict | None = None
    enabled: bool | None = None


class AlertTemplatePreviewIn(BaseModel):
    """Context mẫu để render thử template (không lưu)."""

    context: dict = Field(default_factory=dict)


class AlertTemplatePreviewOut(BaseModel):
    title: str
    body: str | None
    warnings: list[str] = Field(default_factory=list)


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    template_code: str = Field(..., min_length=1, max_length=64)
    org_id: uuid.UUID | None = None
    scope_mode: str = Field(default="org_only", pattern="^(org_only|org_tree|system)$")
    recipient_mode: str = Field(default="org_admins_and_super", pattern="^(org_admins_and_super)$")
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    template_code: str | None = None
    org_id: uuid.UUID | None = None
    scope_mode: str | None = Field(default=None, pattern="^(org_only|org_tree|system)$")
    recipient_mode: str | None = Field(default=None, pattern="^(org_admins_and_super)$")
    config: dict | None = None
    enabled: bool | None = None


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    template_code: str
    template_name: str | None = None
    org_id: uuid.UUID | None
    scope_mode: str
    recipient_mode: str
    config: dict
    enabled: bool
    created_at: datetime


class AlertRuleTestOut(BaseModel):
    """Dry-run: render + resolve recipients, KHÔNG gửi."""

    template_code: str
    title: str
    body: str | None
    recipients: list[dict] = Field(default_factory=list)  # [{user_id, email, full_name, telegram_linked}]
    total_recipients: int
    warnings: list[str] = Field(default_factory=list)


class AlertEventOut(BaseModel):
    id: int
    rule_id: uuid.UUID
    template_code: str
    machine_id: uuid.UUID | None
    org_id: uuid.UUID | None
    severity: str
    title: str
    body: str | None
    recipient_user_ids: list[str]
    created_at: datetime


class UserNotificationPrefOut(BaseModel):
    """Pref của user hiện tại + metadata template (để UI render control)."""

    template_code: str
    template_name: str
    category: str
    default_severity: str
    opt_out_controls: list[str]
    muted: bool
    min_severity: str | None


class UserNotificationPrefItem(BaseModel):
    template_code: str
    muted: bool = False
    min_severity: str | None = None


class UserNotificationPrefUpdateIn(BaseModel):
    prefs: list[UserNotificationPrefItem] = Field(default_factory=list)


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
    # Loại máy + tag mục đích áp cho TOÀN BỘ dòng (bulk CSV) — mặc định công vụ.
    classification: str | None = Field(default=None, pattern="^(personal|official|bmnn)$")
    purpose_tags: list[str] = Field(default_factory=list)


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


class AssignUserRequest(BaseModel):
    """Gán người sử dụng cho máy (sau khi upload ZIP cách ly).

    Hai chế độ:
    - mode="existing": chọn user có sẵn trong tổ chức → chỉ cần `user_id`
    - mode="new": tạo user mới (role=viewer) rồi gán → cần `full_name`, `email`
      + các trường tuỳ ch ( (phone, department)

    Flow chuẩn: sau khi upload ZIP lên `/offline-import` thành công, admin nhập
    thông tin người dùng ở đây đ máy đã có assigned_user_id trước khi giao cho user.
    """

    mode: str = Field(..., pattern="^(existing|new)$", description="existing = chọn user có sẵn; new = tạo user mới")
    user_id: uuid.UUID | None = Field(default=None, description="Bắt buộc nếu mode=existing")
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    department: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1000, description="Ghi chú (vd: lý do gán)")


class AssignUserResponse(BaseModel):
    machine_id: uuid.UUID
    assigned_user_id: uuid.UUID
    assigned_user_name: str
    assigned_user_email: EmailStr
    phone_masked: str | None = None
    was_created: bool = Field(..., description="True nếu user mới được tạo ở request này")


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
    decrypted: bool = False
    apps_count: int | None = None
    collected_at: datetime | None = None
    # Người dùng hiện đang được gán cho máy (nếu có). Frontend dùng để:
    # - Hiển thị tên người dùng ngay sau khi upload
    # - Cho phép admin đổi qua user khác nếu cần
    assigned_user_id: uuid.UUID | None = None
    assigned_user_name: str | None = None
    assigned_user_email: str | None = None
    org_id: uuid.UUID | None = None  # org của máy → filter danh sách user cùng org


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
    must_change_password: bool = False


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


class ChangePasswordRequest(BaseModel):
    """Người dùng đổi mật khẩu của chính mình (không phải admin reset).
    Bắt buộc cung cấp mật khẩu hiện tại để chống chiếm đoạt phiên (VD khi
    máy bị mất/khoá nhưng vẫn có cookie hợp lệ)."""

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class SelfProfileUpdateRequest(BaseModel):
    """Thông tin cơ bản user có thể tự thay đổi."""

    full_name: str = Field(..., min_length=1, max_length=255)


class TotpDisableRequest(BaseModel):
    """Tắt 2FA phải xác thực lại mật khẩu của phiên hiện tại."""

    current_password: str = Field(..., min_length=1, max_length=128)


# ── Cấu hình agent (portal Vận hành → Cấu hình Agent) ───────────


class AgentSettingsUpdate(BaseModel):
    """Super Admin chỉnh cấu hình agent từ portal. Trường `None` = về mặc định env."""

    heartbeat_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    heartbeat_jitter_seconds: int | None = Field(default=None, ge=0, le=600)
    inventory_interval_hours: int | None = Field(default=None, ge=1, le=168)
    agent_server_url: str | None = Field(default=None, max_length=512)
    portal_url: str | None = Field(default=None, max_length=512)


class AgentSettingsOut(BaseModel):
    """Cấu hình hiệu lực + giá trị mặc định env + nguồn của từng trường."""

    # Giá trị hiệu lực (agent đang nhận)
    heartbeat_interval_seconds: int
    heartbeat_jitter_seconds: int
    online_ttl_seconds: int
    inventory_interval_hours: int
    renew_before_percent: int
    agent_server_url: str
    portal_url: str

    # Giá trị mặc định env (để so sánh / hoàn tác)
    defaults: dict[str, int | str]
    overridden: dict[str, bool]
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None


# ── Thống kê máy theo tổ chức (agent vs cách ly) ─────────────────


class OrgMachineStat(BaseModel):
    """Số máy của 1 tổ chức theo tag phân loại (cá nhân / công vụ / BMNN).

    - `official` = máy công vụ THUẦN (chưa gồm BMNN) — công vụ thực tế = official + bmnn.
    - `with_agent` giữ làm thông tin phụ "đã cài agent" (không dùng để suy loại máy).
    """

    org_id: uuid.UUID
    org_name: str
    org_type: str
    total: int
    personal: int  # máy cá nhân — KHÔNG tính vào công vụ
    official: int  # máy công vụ thuần
    bmnn: int  # máy BMNN — vẫn là công vụ
    with_agent: int  # đã gửi heartbeat ít nhất 1 lần → đang cài agent
    pending: int  # chờ duyệt enroll


class TagOrgStat(BaseModel):
    """Số máy mang 1 tag trong 1 tổ chức."""

    org_id: uuid.UUID
    org_name: str
    org_type: str
    count: int


class TagStatItem(BaseModel):
    """1 tag + số máy đang mang tag đó (toàn hệ thống + phân bố theo tổ chức)."""

    id: uuid.UUID
    key: str
    label: str
    kind: str
    color: str | None = None
    count: int
    org_stats: list[TagOrgStat] = Field(default_factory=list)


class TagStatsResponse(BaseModel):
    """Thống kê máy theo tag — đếm số máy mang mỗi tag (classification + purpose)."""

    total_machines: int
    tags: list[TagStatItem] = Field(default_factory=list)


# ── Pagination ────────────────────────────────────────────────


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Response phân trang. Dùng cho mọi list endpoint có dữ liệu lớn.

    - `items`: trang hiện tại (≤ limit)
    - `total`: tổng số record khớp filter (frontend tính tổng số trang)
    - `limit`: số record / trang (mặc định 50, max 200)
    - `offset`: vị trí bắt đầu (mặc định 0)

    Frontend dùng generic `<T>` để có type chính xác (vd `Page<MachineListItem>`).
    """

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


# ── Velociraptor (DFIR) ──────────────────────────────────────


class VelociraptorConfigOut(BaseModel):
    """Cấu hình Velociraptor Server hiệu lực.

    KHÔNG trả cert/credentials thật ra ngoài — chỉ boolean + cert metadata.
    Admin nhập mới qua update (paste YAML / username+password).
    """

    enabled: bool
    server_url: str | None = None
    # mTLS (Velociraptor-native — cần authenticator.type: Certs phía server)
    client_config_set: bool = False
    client_cert_info: dict | None = None
    # HTTP Basic (Velociraptor default authenticator — username + password)
    basic_auth_set: bool = False
    # Bearer fallback (legacy — vẫn hoạt động nếu đã set trước)
    api_token_set: bool = False
    allowlist: list[str] = Field(default_factory=list)
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    last_sync_linked: int | None = None
    last_sync_total: int | None = None
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None
    # Defaults từ env
    defaults_server_url: str | None = None
    defaults_allowlist: list[str] = Field(default_factory=list)


class VelociraptorConfigUpdate(BaseModel):
    """Cập nhật cấu hình Velociraptor (Super Admin).

    Tất cả trường đều optional. 2 cách set credentials:

      - **mTLS (khuyến nghị)**: paste `client_config` = YAML từ
        `velociraptor config client --name inventory-portal --role administrator`.
        Server parse, mã hoá AES-256-GCM, lưu vào DB.
      - **Bearer (fallback cũ)**: `api_token` = plaintext token. Server mã hoá AES-256-GCM.

    Cả 2 cách đều hợp lệ; nếu cả 2 được set, mTLS được ưu tiên.
    """

    enabled: bool | None = None
    server_url: str | None = Field(default=None, max_length=512)
    client_config: str | None = Field(
        default=None,
        description=(
            "YAML từ `velociraptor config api_client` — mTLS client cert (Velociraptor-native). "
            "Rỗng/null = KHÔNG thay đổi; \"\" để xoá."
        ),
    )
    username: str | None = Field(
        default=None,
        max_length=128,
        description="HTTP Basic username (Velociraptor default authenticator).",
    )
    password: str | None = Field(
        default=None,
        max_length=512,
        description="HTTP Basic password. Rỗng/null = KHÔNG đổi; \"\" để xoá.",
    )
    api_token: str | None = Field(
        default=None,
        max_length=512,
        description="(Legacy) Bearer API token. Rỗng/null = KHÔNG đổi; \"\" để xoá.",
    )
    allowlist: list[str] | None = None


class VelociraptorTestConnectionOut(BaseModel):
    """Kết quả test kết nối Velociraptor Server (không lưu DB)."""

    ok: bool
    error: str | None = None
    client_count_sampled: int | None = None
    server_url: str | None = None
    mcp: "DeepAgentTestOut | None" = None


class VelociraptorLinkOut(BaseModel):
    """Mapping machine ↔ Velociraptor client_id (1-1)."""

    model_config = {"from_attributes": True}  # Pydantic v2: cho phép nhận ORM object

    machine_id: uuid.UUID
    client_id: str
    hostname: str
    os_info: dict | None = None
    last_seen_at: datetime | None = None
    synced_at: datetime


class VelociraptorLinkEnriched(VelociraptorLinkOut):
    """VelociraptorLinkOut kèm thông tin máy để hiển thị trên portal."""

    machine_hostname: str | None = None
    machine_status: str | None = None
    machine_org_name: str | None = None
    machine_last_seen_at: datetime | None = None


class DfirHuntCreate(BaseModel):
    """Admin tạo hunt (trên nhiều máy đã link Velociraptor) hoặc collect artifact (trên 1/N máy)."""

    artifact: str = Field(..., min_length=1, max_length=255, description="Velociraptor artifact name (vd 'Generic.Client.Info')")
    scope: str = Field(default="all", pattern="^(all|single|multi)$")
    machine_id: uuid.UUID | None = None  # bắt buộc nếu scope=single
    machine_ids: list[uuid.UUID] | None = None  # bắt buộc nếu scope=multi
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=1024)


class DfirHuntOut(BaseModel):
    """Kết quả tạo hunt/collect — trả hunt_id + deep-link Velociraptor GUI."""

    id: uuid.UUID
    hunt_id: str | None = None
    artifact: str
    scope: str
    machine_id: uuid.UUID | None = None
    requested_by: uuid.UUID
    status: str
    velociraptor_url: str | None = None
    notes: str | None = None
    error: str | None = None
    created_at: datetime
    # Số client tham gia (lấy từ Velociraptor nếu là hunt, =1 nếu là single)
    client_count: int | None = None




class DfirInvestigationRequestCreate(BaseModel):
    """Form Admin gửi yêu cầu điều tra DFIR."""
    machine_id: uuid.UUID
    artifact: str = Field(..., min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=2000)
    urgency: str = Field(default="normal", pattern="^(low|normal|high|critical)$")


class DfirInvestigationRequestReview(BaseModel):
    """Super Admin duyệt/reject request."""
    action: str = Field(..., pattern="^(approve|reject|complete|fail)$")
    notes: str | None = Field(default=None, max_length=2000)
    velociraptor_flow_id: str | None = None  # khi complete: flow_id từ Velociraptor


class DfirInvestigationRequestOut(BaseModel):
    """Out cho Admin (ẩn chi tiết Velociraptor)."""
    id: uuid.UUID
    machine_id: uuid.UUID
    machine_hostname: str | None = None
    artifact: str
    reason: str | None
    urgency: str
    status: str
    requested_by: str | None = None  # user name
    requested_at: datetime
    review_notes: str | None = None
    completed_at: datetime | None = None
    # CHỈ super_admin mới thấy các field Velociraptor:
    velociraptor_flow_id: str | None = None
    velociraptor_url: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class DfirInvestigationRequestDetail(DfirInvestigationRequestOut):
    """Detail cho Super Admin (có thêm thông tin nội bộ)."""
    pass

class VelociraptorClientFlowOut(BaseModel):
    """Flow (hunt/collection/interrogation) của 1 Velociraptor client."""
    State: str | None = None
    FlowId: str | None = None
    Artifacts: list[str] = []
    Created: int | None = None  # Unix timestamp (ns)
    LastActive: int | None = None
    Creator: str | None = None
    Mb: int | None = None
    Rows: int | None = None


class VelociraptorClientMetadataOut(BaseModel):
    """Metadata chi tiết của Velociraptor client (từ GetClient API)."""
    client_id: str
    agent_information: dict | None = None
    os_info: dict | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    last_ip: str | None = None
    last_interrogate_flow_id: str | None = None
    last_interrogate_artifact_name: str | None = None
    client_count: int | None = None


class VelociraptorTop10ArtifactOut(BaseModel):
    """1 artifact trong bảng "Top 10 sự kiện DFIR" của 1 client.

    source: reused (tái sử dụng flow FINISHED cũ) | running (flow đang chạy)
            | collected (vừa collect đồng bộ) | missing (chưa có dữ liệu)
            | error (Velociraptor trả lỗi khi đọc/collect).
    """

    artifact: str
    label: str
    flow_id: str | None = None
    source: str = "missing"
    error: str | None = None
    rows: list[dict] = Field(default_factory=list)
    total_rows: int = 0


class VelociraptorTop10Out(BaseModel):
    """Kết quả trích xuất Top 10 sự kiện / log gần nhất cho 1 client."""

    client_id: str
    generated_at: datetime
    artifacts: list[VelociraptorTop10ArtifactOut] = Field(default_factory=list)
    flows: list[VelociraptorClientFlowOut] = Field(default_factory=list)


class VelociraptorTop10CollectArtifactOut(BaseModel):
    """1 artifact trong response POST collect — trạng thái kick-off."""

    artifact: str
    label: str
    status: str = "missing"  # reused | collecting | not_allowed | missing | error
    flow_id: str | None = None
    error: str | None = None


class VelociraptorTop10CollectOut(BaseModel):
    """Kết quả POST /top10/collect — các artifact đã kick-off collect."""

    client_id: str
    started_at: datetime
    artifacts: list[VelociraptorTop10CollectArtifactOut] = Field(default_factory=list)



class DfirScheduleCreate(BaseModel):
    """Tạo scheduled hunt/collect định kỳ."""
    name: str = Field(..., min_length=1, max_length=255)
    artifact: str = Field(..., min_length=1, max_length=255)
    scope: str = Field(default="all", pattern="^(all|multi)$")
    machine_ids: list[uuid.UUID] | None = None
    interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400 * 7,
        description="60 (1 phút) → 604800 (1 tuần). Phổ biến: 300 (5p), 3600 (1h), 86400 (1 ngày).",
    )


class DfirScheduleUpdate(BaseModel):
    """Update scheduled hunt."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    interval_seconds: int | None = Field(default=None, ge=60, le=86400 * 7)
    enabled: bool | None = None


class DfirScheduleOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    artifact: str
    scope: str
    machine_ids: list | None = None
    interval_seconds: int
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime
    last_status: str | None = None
    last_error: str | None = None
    requested_by: uuid.UUID
    created_at: datetime


class DfirAlertOut(BaseModel):
    """Alert khi có flow sensitive xuất hiện."""
    model_config = {"from_attributes": True}
    id: uuid.UUID
    artifact_pattern: str
    severity: str
    flow_id: str
    client_id: str | None = None
    machine_id: uuid.UUID | None = None
    message: str
    resolved: bool
    created_at: datetime


# ── LLM-DFIR ──────────────────────────────────────────────────────


class LlmConfigOut(BaseModel):
    enabled: bool
    provider: str
    base_url: str
    api_key_masked: str
    model: str
    fallback_model: str | None
    system_prompt: str | None
    max_tokens: int
    temperature: float
    request_timeout: int
    max_context_chars: int
    allow_cloud: bool
    external_orchestrator: str = ""  # "" = local LLM | "hermes" = đợi Hermes push kết quả
    deepagent_enabled: bool = False
    deepagent_url: str | None = None
    deepagent_service_token_set: bool = False
    daily_token_budget: int | None
    tokens_used_today: int
    test_status: str | None
    test_error: str | None
    test_at: datetime | None
    updated_at: datetime
    available_models: list[str] = []


class LlmConfigUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    fallback_model: str | None = None
    system_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    request_timeout: int | None = None
    max_context_chars: int | None = None
    allow_cloud: bool | None = None
    external_orchestrator: str | None = None
    deepagent_enabled: bool | None = None
    deepagent_url: str | None = None
    deepagent_service_token: str | None = None
    daily_token_budget: int | None = None


class LlmTestConnectionOut(BaseModel):
    ok: bool
    latency_ms: int
    models: list[str]
    error: str | None = None


class DeepAgentTestOut(BaseModel):
    ok: bool
    service_ok: bool = False
    mcp_ok: bool = False
    tools: list[str] = Field(default_factory=list)
    client_count_sampled: int | None = None
    error: str | None = None


class LlmModelsOut(BaseModel):
    models: list[str] = Field(default_factory=list)


class DfirInvestigationCreate(BaseModel):
    machine_id: uuid.UUID
    artifacts: list[str] | None = None
    custom_instructions: str | None = None
    # True nếu muốn orchestrator chỉ thu thập data rồi đợi external (Hermes) push kết quả
    # (override config LlmConfig.external_orchestrator nếu cần)
    use_external_orchestrator: bool | None = None


class DfirInvestigationOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID
    machine_hostname: str | None = None
    status: str
    artifacts: list[str]
    llm_provider: str | None
    llm_model: str | None
    severity: str | None
    findings_count: int | None
    findings: list | None = None
    iocs: list | None = None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    error: str | None
    report_markdown: str | None
    custom_instructions: str | None = None
    external_orchestrator: str | None = None
    external_job_id: str | None = None
    external_polled_at: datetime | None = None
    hermes_status: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    callback_received_at: datetime | None = None
    requested_by: uuid.UUID
    requested_by_name: str | None = None


class ExternalInvestigationResultIn(BaseModel):
    """Body Hermes gửi về khi xong investigation.

    Idempotent qua X-Idempotency-Key header.
    """
    report_markdown: str | None = None
    severity: str | None = "info"  # critical|high|medium|low|info
    findings_count: int | None = None
    findings: list | None = None  # [{id, title, mitre_id, severity, evidence, recommendation}]
    iocs: list | None = None  # [{type, value, source}]
    llm_provider: str | None = None  # vd "hermes-agent"
    llm_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None  # nếu set → status=failed
    external_job_id: str | None = None  # correl với job_id phía Hermes
    raw_response: dict | None = None  # full response để audit

    @model_validator(mode="after")
    def validate_report_for_success(self):
        if not self.error and not self.report_markdown:
            raise ValueError("report_markdown bắt buộc khi callback thành công")
        return self


class ExternalInvestigationStatusIn(BaseModel):
    """Cập nhật tiến độ từ external orchestrator; không hoàn tất investigation."""
    external_job_id: str
    phase: str = Field(min_length=1, max_length=64)
    progress_percent: int = Field(ge=0, le=100)
    current_step: int | None = Field(default=None, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=1000)


class ExternalInvestigationPendingOut(BaseModel):
    """Item trong list pending — Hermes consume."""
    id: uuid.UUID
    machine_id: uuid.UUID
    velociraptor_client_id: str | None
    machine_hostname: str | None
    machine_fqdn: str | None
    machine_os: str | None
    artifacts: list[str]
    custom_instructions: str | None
    created_at: datetime
    callback_url: str  # URL Hermes gọi POST result về


class ExternalInvestigationAckOut(BaseModel):
    id: uuid.UUID
    status: str
    message: str
    notification_id: str | None = None  # notification đã gửi cho admin


class DfirInvestigationMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tokens: int | None
    created_at: datetime


class DfirInvestigationChatIn(BaseModel):
    message: str


# ── Notifications ───────────────────────────────────────────────


class NotificationOut(BaseModel):
    id: uuid.UUID
    source: str
    category: str
    severity: str
    title: str
    body: str | None
    link: str | None
    entity_type: str | None
    entity_id: str | None
    read_at: datetime | None
    created_at: datetime
    sender_name: str | None = None


class NotificationUnreadCountOut(BaseModel):
    total: int
    by_severity: dict[str, int] = {}


class NotificationMarkAllReadOut(BaseModel):
    marked: int


class AdminSendNotificationIn(BaseModel):
    recipient_ids: list[uuid.UUID] | None = None
    recipient_filter: dict | None = None  # {role, org_id, broadcast, exclude_user_id}
    category: str = "message"
    severity: str = "info"
    title: str
    body: str | None = None
    link: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    data: dict | None = None


class AdminSendNotificationOut(BaseModel):
    delivered_to: int
    recipient_ids: list[str]
    notification_ids: list[str]


class ExternalNotificationIn(BaseModel):
    recipients: dict  # {type: "role"|"user"|"broadcast", role?, user_ids?, broadcast?}
    category: str = "investigation"
    severity: str = "info"
    title: str
    body: str | None = None
    link: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    data: dict | None = None


class TelegramLinkStartOut(BaseModel):
    """Trả về deep-link để user mở Telegram bot."""
    bot_url: str
    linking_token: str
    expires_at: datetime


class TelegramLinkStatusOut(BaseModel):
    linked: bool
    telegram_chat_id: str | None = None
    linked_at: datetime | None = None


# ── Telegram bot config (Super Admin) ────────────────────────────


class TelegramBotConfigOut(BaseModel):
    """Trả về cấu hình bot hiện tại.

    Token KHÔNG được trả về plaintext (chỉ mask) — chỉ Super Admin biết đã
    cấu hình hay chưa. Webhook secret cũng mask tương tự.
    """

    configured: bool
    """True nếu đã có token + username (kể cả từ env)."""

    bot_username: str | None = None
    """Username bot (vd `MyInventoryBot`) — hiển thị cho admin."""

    bot_token_set: bool
    """True nếu có token (DB hoặc env)."""

    bot_token_masked: str | None = None
    """Mask token: `1234567890:AA***xyz` — chỉ khi DB có token. None nếu
    token đến từ env (không tiết lộ độ dài/mask theo cách lộ thông tin)."""

    webhook_secret_set: bool
    """True nếu đã set secret (để verify webhook Telegram)."""

    webhook_secret_masked: str | None = None
    """Mask webhook secret."""

    enabled: bool
    """Bot đang bật (chỉ áp dụng cho row DB; nếu source=env thì mặc định True)."""

    source: str
    """`db` (Super Admin đã cấu hình trên portal) | `env` (đang dùng
    fallback từ .env) | `none` (chưa cấu hình)."""

    updated_at: datetime | None = None
    """Thời điểm update gần nhất (chỉ khi source=db)."""

    updated_by: str | None = None
    """User id đã update lần cuối (chỉ khi source=db)."""

    callback_url: str
    """URL callback đầy đủ mà Super Admin cần submit cho @BotFather khi set
    webhook. Dựa trên `agent_server_url` (cùng URL backend public dùng cho
    agent), trỏ về `/api/external/telegram/callback`."""

    webhook_set_command: str | None = None
    """Snippet `curl` để set webhook qua Telegram API (kèm secret_token).
    `None` nếu chưa có token + secret. Super Admin có thể copy & chạy trên
    server có HTTPS reach được bởi Telegram."""

    webhook_check_command: str | None = None
    """Snippet `curl` để verify webhook hiện tại (dùng `getWebhookInfo`)."""


class TelegramBotConfigUpdateIn(BaseModel):
    """PUT body từ Super Admin — set / update bot config trên portal.

    Tất cả trường optional; chỉ update trường được set (kể cả set None để xoá).
    Token được mã hoá AES-256-GCM trước khi lưu DB.
    """

    bot_token: str | None = None
    """Plaintext token từ BotFather. Set chuỗi rỗng = KHÔNG đổi; để None = xoá."""

    bot_username: str | None = None
    """Username bot (không có '@'). Để None để KHÔNG đổi."""

    webhook_secret: str | None = None
    """Secret Telegram dùng để ký webhook. Để None để KHÔNG đổi; chuỗi rỗng = xoá."""

    enabled: bool | None = None
    """Bật/tắt delivery. None = KHÔNG đổi."""


class TelegramBotConfigTestOut(BaseModel):
    """Kết quả `POST /api/admin/telegram-bot/test` — gọi `getMe` API để verify."""

    ok: bool
    bot_id: int | None = None
    bot_username: str | None = None
    error: str | None = None
    """Mô tả lỗi kết nối / HTTP / parsing (KHÔNG log token ra đây)."""


class TelegramLinkedUserOut(BaseModel):
    """1 user đã liên kết Telegram — dùng cho Super Admin xem trên portal.

    Hiển thị đủ thông tin để admin biết ai đang nhận notification qua bot.
    `chat_id` không che — Super Admin cần xem để debug (vd ai đó liên kết nhầm
    account Telegram cá nhân).
    """

    id: str
    email: str
    full_name: str
    role: str
    org_id: str
    org_name: str | None = None
    telegram_chat_id: str
    telegram_linked_at: datetime | None = None
    is_active: bool = True


# ── LLM-DFIR Statistics ──────────────────────────────────────────


class DfirInvestigationListOut(BaseModel):
    """Paginated list investigations."""
    items: list  # list[DfirInvestigationOut]
    total: int
    page: int
    limit: int
    has_more: bool


class DfirInvestigationStatsOut(BaseModel):
    """Thống kê investigations — cho dashboard báo cáo."""
    total: int
    by_status: dict[str, int]  # {"pending": 5, "completed": 30, "failed": 3, ...}
    by_severity: dict[str, int]  # {"critical": 2, "high": 5, "info": 30, ...}
    by_machine: list[dict]  # [{"machine_id": "...", "hostname": "...", "count": 5, "critical": 1}, ...]
    recent_24h: int  # số investigation tạo trong 24h qua
    recent_7d: int
    avg_duration_seconds: float | None  # thời gian xử lý trung bình
    # Series theo ngày (30 ngày gần nhất) — cho chart
    daily_counts: list[dict]  # [{"date": "2026-08-30", "total": 5, "critical": 1}, ...]
    # Top findings
    top_findings: list[dict]  # [{"mitre_id": "T1059.001", "title": "...", "count": 3}, ...]
