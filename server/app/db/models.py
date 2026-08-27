"""Toàn bộ models — theo mục 5.1 của KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md.

Database chính: **PostgreSQL** (UUID native, JSONB). enum lưu dạng String.
"""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrgType(str, enum.Enum):
    """Loại tổ chức — theo phân cấp: UBND cấp xã / Sở ban ngành (+ cấp dưới).

    - `root`        : gốc cây tổ chức (chỉ dùng làm parent)
    - `ubnd_xa`     : UBND cấp xã
    - `so_ban_nganh`: Sở ban ngành
    - `phong`       : Phòng ban (cấp dưới của sở ban ngành)
    - `don_vi`      : Đơn vị trực thuộc (cấp dưới chung: thôn/tổ dân phố, chi cục…)
    """

    ROOT = "root"
    UBND_XA = "ubnd_xa"
    SO_BAN_NGANH = "so_ban_nganh"
    PHONG = "phong"
    DON_VI = "don_vi"


class UserRole(str, enum.Enum):
    """Vai trò người dùng.

    - `super_admin`: xem/quản lý mọi tổ chức (Super Admin)
    - `org_admin`  : admin của 1 tổ chức (UBND xã / Sở ban ngành) — xem được **cấp dưới**
                     trong cây tổ chức của mình, sinh token, quản lý máy
    - `viewer`     : người xem read-only trong phạm vi tổ chức (và cấp dưới)

    `admin_global` / `admin_org` là alias legacy (dữ liệu cũ) — vẫn được chấp nhận như
    super_admin / org_admin để không phá dữ liệu đang tồn tại.
    """

    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    VIEWER = "viewer"
    ADMIN_GLOBAL = "admin_global"  # legacy → super_admin
    ADMIN_ORG = "admin_org"        # legacy → org_admin


class MachineStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    LOST = "lost"
    DECOMMISSIONED = "decommissioned"
    PENDING = "pending"  # pending approval


class TokenStatus(str, enum.Enum):
    PENDING = "pending"
    USED = "used"
    REVOKED = "revoked"
    EXPIRED = "expired"


class NoticeStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class AssetLifecycle(str, enum.Enum):
    NEW = "new"                  # Mới cài
    IN_USE = "in_use"            # Đang dùng
    IN_REPAIR = "in_repair"      # Sửa chữa
    DECOMMISSIONED = "decommissioned"  # Thanh lý


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default=OrgType.DON_VI.value)

    parent: Mapped[Organization | None] = relationship(remote_side=[id])
    children: Mapped[list[Organization]] = relationship(back_populates="parent")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # AES-256-GCM
    role: Mapped[str] = mapped_column(String(32), default=UserRole.VIEWER.value)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    backup_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # hash bcrypt, dùng 1 lần
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))

    org: Mapped[Organization] = relationship()


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    machine_uuid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fingerprint: Mapped[dict] = mapped_column(JSONB, default=dict)  # fingerprint có trọng số
    status: Mapped[str] = mapped_column(String(32), default=MachineStatus.PENDING.value)
    lifecycle: Mapped[str] = mapped_column(String(32), default=AssetLifecycle.NEW.value)
    is_vm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # IP public (WAN) mới nhất mà agent phát hiện — dùng để hiển thị trên portal,
    # phát hiện IP WAN động, NAT/proxy. Cache ở bảng máy để hiển thị kể cả khi máy offline.
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    org: Mapped[Organization] = relationship()
    assigned_user: Mapped[User | None] = relationship()
    specs: Mapped[list[MachineSpec]] = relationship(
        back_populates="machine", cascade="all, delete-orphan", order_by="MachineSpec.collected_at.desc()"
    )
    current: Mapped[MachineCurrent | None] = relationship(
        back_populates="machine", cascade="all, delete-orphan", uselist=False
    )
    software: Mapped[list[MachineSoftware]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )


class MachineSpec(Base):
    __tablename__ = "machine_specs"
    __table_args__ = (Index("ix_machine_specs_machine_collected", "machine_id", "collected_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    os_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    os_product: Mapped[str | None] = mapped_column(String(128), nullable=True)  # ProductName thuần ("Windows 11 Pro")
    os_release: Mapped[str | None] = mapped_column(String(32), nullable=True)   # DisplayVersion ("25H2")
    os_family: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # windows_10|windows_11|...
    os_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_build: Mapped[str | None] = mapped_column(String(32), nullable=True)
    os_arch: Mapped[str | None] = mapped_column(String(16), nullable=True)
    os_installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cpu: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ram_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    disks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    gpu: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mainboard: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    bios: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    network: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    logged_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    installed_software: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    security: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # IP public (WAN) mà agent phát hiện được khi gửi snapshot này (lưu lịch sử).
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))

    machine: Mapped[Machine] = relationship(back_populates="specs")


class MachineCurrent(Base):
    """Snapshot CẤU HÌNH MỚI NHẤT của mỗi máy — 1:1 với machines (denormalized).

    Upsert mỗi lần nhận inventory mới (cùng transaction với insert `machine_specs`).
    Nguồn duy nhất cho thống kê "hiện tại" — mọi câu đếm là GROUP BY trên cột có index,
    không phải scan lịch sử JSONB trong `machine_specs`.

    Các trường OS/security được CHUẨN HÓA PHÍA SERVER từ payload agent (v1/v2/v3) —
    agent không cần đổi (xem `app/services/inventory_normalize.py`).
    """

    __tablename__ = "machine_current"

    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), primary_key=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── OS — chuẩn hóa để đếm (không parse chuỗi) ──
    os_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    os_product: Mapped[str | None] = mapped_column(String(128), nullable=True)
    os_release: Mapped[str | None] = mapped_column(String(32), nullable=True)
    os_family: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    os_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_build: Mapped[str | None] = mapped_column(String(32), nullable=True)
    os_arch: Mapped[str | None] = mapped_column(String(16), nullable=True)
    os_installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── Phần cứng — ít thống kê, giữ JSONB gọn ──
    cpu: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ram_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    disks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    gpu: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mainboard: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    bios: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    network: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_vm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    logged_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # IP public (WAN) — để thống kê / lọc nhanh theo subnet WAN.
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True, index=True)

    # ── Bảo mật — CỘT có kiểu rõ ràng (đếm được, index được) ──
    antivirus: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # chi tiết, hiển thị
    antivirus_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    antivirus_up_to_date: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    windows_update_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    windows_update_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    bitlocker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    firewall_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    uac_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    secure_boot_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rdp_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    usb_storage_blocked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    machine: Mapped[Machine] = relationship(back_populates="current")


class MachineSoftware(Base):
    """Phần mềm đã cài của mỗi máy — 1 dòng/app/máy (bảng "hiện tại" chuẩn hóa).

    Upsert dạng replace (xóa hết app cũ của máy + insert danh sách mới) mỗi lần
    inventory đổi — tần suất thấp (24h / khi cấu hình đổi), kích thước nhỏ (~50–200/máy).

    - "App cài nhiều nhất": GROUP BY name → COUNT(DISTINCT machine_id) (index lower(name)).
    - "Máy nào thiếu app X": LEFT JOIN machines.
    - Alert `software_new` (diff vs allowlist) trở nên tầm thường.
    """

    __tablename__ = "machine_software"
    __table_args__ = (
        # Unique theo tên KHÔNG phân biệt hoa thường — agent cùng code luôn gửi cùng casing,
        # nhưng offline import / agent khác có thể lệch. Dùng text("lower(name)") để trỏ ĐÚNG
        # vào cột (func.lower("name") sẽ thành literal 'name' — sai).
        Index(
            "uq_machine_software_machine_name",
            "machine_id",
            text("lower(name)"),
            unique=True,
        ),
        Index("ix_machine_software_name", text("lower(name)")),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    install_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))

    machine: Mapped[Machine] = relationship(back_populates="software")


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    __table_args__ = (Index("ix_heartbeats_machine_ts", "machine_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), index=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    logged_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uptime_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EnrollToken(Base):
    __tablename__ = "enroll_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=TokenStatus.PENDING.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_ts", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)  # user id | "agent:<machine_id>" | "system"
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # hash chuỗi phía trước
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # hash nội dung dòng này
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"), nullable=True)


class ComplianceNotice(Base):
    __tablename__ = "compliance_notices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=NoticeStatus.DRAFT.value)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class UserAcknowledgment(Base):
    __tablename__ = "user_acknowledgments"
    __table_args__ = (UniqueConstraint("user_id", "notice_id", name="uq_user_notice_ack"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    notice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("compliance_notices.id"), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)  # portal | installer


class AlertRule(Base):
    """Alert rule (tính năng #14) — máy mới, mất liên lạc, phần mềm lạ, phần cứng đổi."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)  # machine_new | machine_lost | software_new | hardware_changed
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)  # None = toàn hệ thống
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # machine_lost
    channels: Mapped[list | None] = mapped_column(JSONB, default=list)  # ["email","telegram","zalo"]
    notify_targets: Mapped[list | None] = mapped_column(JSONB, default=list)  # email / chat id / phone
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AlertEvent(Base):
    """Bản ghi 1 lần alert được kích hoạt (không lặp lại cùng rule + máy)."""

    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("rule_id", "machine_id", "fingerprint", name="uq_alert_event"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)  # chống trùng: hash(rule+machine+ngày)
    severity: Mapped[str] = mapped_column(String(16), default="warning")  # info | warning | critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[list | None] = mapped_column(JSONB, default=list)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class SelfServiceLink(Base):
    """Token chế độ B — link tự khai báo của 1 tổ chức (mục 4.4)."""

    __tablename__ = "self_service_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))





class FingerprintDrift(Base):
    """Cảnh báo fingerprint thay đổi (tính năng #4) — admin duyệt trước khi chấp nhận.

    Khi enroll một máy ĐÃ CÓ mà fingerprint lệch đáng kể (đổi mainboard / ghost Win):
    lưu bản ghi drift (status=pending) thay vì ghi đè ngay; admin approve → cập nhật
    fingerprint máy; reject → giữ nguyên.
    """

    __tablename__ = "fingerprint_drifts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    old_fingerprint: Mapped[dict] = mapped_column(JSONB, default=dict)
    new_fingerprint: Mapped[dict] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)  # mainboard_changed | os_reinstall | other
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class ApiKey(Base):
    """API mở cho hệ thống khác (#22, Phase 4) — key theo scope, chỉ lưu hash.

    Plaintext key chỉ trả 1 lần lúc tạo (dạng `ai_<base62>`); scope hiện hỗ trợ
    `read:machines`. org_id=None → toàn hệ thống (chỉ Super Admin tạo).
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(64), default="read:machines")
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AgentConfigOverride(Base):
    """Cấu hình agent do Super Admin đặt từ portal (bảng 1 dòng, id cố định = 1).

    Agent sau khi cài đặt gọi `GET /api/agent/config` (hoặc nhận qua heartbeat)
    để đồng bộ: tần suất heartbeat, chu kỳ inventory, IP/Domain server đẩy dữ liệu.
    Trường `None` = dùng giá trị mặc định từ env (`app.core.config.Settings`).
    """

    __tablename__ = "agent_config_override"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    heartbeat_interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    heartbeat_jitter_seconds: Mapped[int | None] = mapped_column(nullable=True)
    inventory_interval_hours: Mapped[int | None] = mapped_column(nullable=True)
    agent_server_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # IP/Domain agent đẩy dữ liệu về
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), onupdate=datetime.now(UTC))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
