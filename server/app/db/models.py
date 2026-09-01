"""Toàn bộ models — theo mục 5.1 của KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md.

Database chính: **PostgreSQL** (UUID native, JSONB). enum lưu dạng String.
"""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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


class TagKind(str, enum.Enum):
    """Vai trò của tag.

    - `classification` — PHÂN LOẠI máy: mỗi máy có ĐÚNG 1 tag loại này
      (`personal` / `official` / `bmnn`). Đây là nguồn DUY NHẤT cho thống kê
      "cá nhân / công vụ / BMNN" — tag mục đích KHÔNG bao giờ đụng vào số liệu này.
    - `purpose`        — MỤC ĐÍCH sử dụng: nhiều tag / máy, linh hoạt bổ sung
      (VD `dich_vu_cong`, `soan_thao_van_ban`…) — chỉ để lọc/hiển thị.
    """

    CLASSIFICATION = "classification"
    PURPOSE = "purpose"


# 3 tag phân loại hệ thống — key cố định, seed trong migration.
CLASSIFICATION_TAGS: tuple[tuple[str, str], ...] = (
    ("personal", "Máy cá nhân"),
    ("official", "Máy công vụ"),
    ("bmnn", "Máy BMNN"),
)
DEFAULT_CLASSIFICATION = "official"  # máy enroll thường / máy cũ chưa gán


class Tag(Base):
    """Tag linh hoạt — 3 tag phân loại (is_system) + tag mục đích mở rộng sau."""

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default=TagKind.PURPOSE.value)
    color: Mapped[str | None] = mapped_column(String(128), nullable=True)  # class badge tailwind
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # 3 tag gốc — không xóa
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class MachineTag(Base):
    """Nhiều–nhiều machines ↔ tags.

    - `kind` denormalized từ `tags.kind` (app set khi insert) để chặn ràng buộc
      "1 máy tối đa 1 tag classification" ngay tại DB (partial unique index).
    - `set_by` = ai gán tag (audit).
    """

    __tablename__ = "machine_tags"
    __table_args__ = (
        Index(
            "uq_machine_tags_classification",
            "machine_id",
            unique=True,
            postgresql_where=text("kind = 'classification'"),
        ),
        Index("ix_machine_tags_tag", "tag_id"),
    )

    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    set_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))

    tag: Mapped[Tag] = relationship()


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
    # Telegram bot linking (mỗi user link 1 chat_id với account)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    tags: Mapped[list[MachineTag]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
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
    # v4 envelope fields (agent metadata + os metadata + schema version)
    agent: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    os_metadata: Mapped[dict | None] = mapped_column("os_metadata", JSONB, nullable=True)
    inventory_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    # ── v4 cross-platform columns (added in commit 784b6c4 migration) ──
    platform: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    update_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    update_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updates_pending: Mapped[int | None] = mapped_column(Integer, nullable=True)
    endpoint_protection_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    disk_encryption_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    disk_encryption_technology: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ssh_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    remote_desktop_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

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
    # Loại máy + tag mục đích chọn LÚC SINH TOKEN — áp cho máy khi enroll (mục 4.4/4.5).
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)  # tag key: personal|official|bmnn
    purpose_tags: Mapped[list | None] = mapped_column(JSONB, default=list)  # list tag key mục đích


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
    """Subscription alert — bind template + scope + recipient_mode (redesign)."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )  # NULL khi scope_mode='system'
    scope_mode: Mapped[str] = mapped_column(String(32), default="org_only")
    # org_only | org_tree | system
    recipient_mode: Mapped[str] = mapped_column(String(32), default="org_admins_and_super")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # VD {"threshold_days": 3}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AlertEvent(Base):
    """Bản ghi 1 lần alert được kích hoạt (snapshot title/body đã render)."""

    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("rule_id", "machine_id", "fingerprint", name="uq_alert_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recipient_user_ids: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AlertTemplate(Base):
    """Template nội dung alert — Super Admin quản lý title/body + opt_out_controls."""

    __tablename__ = "alert_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # machine | investigation | security | system
    default_severity: Mapped[str] = mapped_column(String(16), default="info")
    title_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    opt_out_controls: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_vars: Mapped[list] = mapped_column(JSONB, default=list)
    default_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class UserNotificationPref(Base):
    """Opt-out per (user, template) — muted / min_severity."""

    __tablename__ = "user_notification_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "template_code", name="uq_user_notification_prefs_user_template"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    min_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


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
    portal_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # IP/Domain Portal công khai — dùng cho install_command + enroll_url
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), onupdate=datetime.now(UTC))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class VelociraptorConfig(Base):
    """Cấu hình Velociraptor Server — singleton (id=1), Super Admin cấu hình trên portal.

    Tích hợp Velociraptor (https://github.com/velocidex/velociraptor) cho DFIR.
    Backend sync hostname ↔ client_id mỗi 5 phút qua REST API; portal deep-link
    sang Velociraptor GUI để admin chạy hunt/collect artifact.

    - **`client_config_encrypted`** (mTLS — khuyến nghị): YAML từ
      `velociraptor config client --name inventory-portal --role administrator`.
      Mã hoá AES-256-GCM. Khi kết nối Velociraptor REST API, server dựng
      `ssl.SSLContext` chứa ca_cert + client_cert + client_private_key →
      giao tiếp mTLS (Velociraptor chỉ trust client cert được CA của nó ký).
    - `api_token_encrypted` (Bearer — fallback cũ): chỉ dùng nếu
      `client_config_encrypted` chưa set. Sẽ bị drop sau khi mọi deploy
      nâng cấp lên mTLS.
    - `client_cert_info` (JSONB): metadata cert (subject, issuer, expiry,
      sha256_fingerprint) hiển thị portal — KHÔNG chứa private key.
    - `allowlist`: artifact Velociraptor được phép chạy (chống lạm quyền).
    """

    __tablename__ = "velociraptor_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    server_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # legacy Bearer fallback
    basic_auth_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # HTTP Basic (JSON {"username","password"})
    client_config_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # mTLS YAML
    client_cert_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # metadata cert
    allowlist: Mapped[list | None] = mapped_column(JSONB, default=list)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_linked: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), onupdate=datetime.now(UTC))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class VelociraptorLink(Base):
    """Mapping `machine_id ↔ Velociraptor client_id` — được sync mỗi 5 phút từ Velociraptor.

    Cách match: Velociraptor client có `os_info.hostname` (lower-case insensitive)
    ↔ `machines.hostname` (cũng chuẩn hoá về lower-case khi so sánh). Một client chỉ
    link với 1 máy; nếu Velociraptor trả nhiều client cùng hostname (VD máy clone),
    hệ thống chọn client mới thấy gần nhất.

    `client_id` UNIQUE — Velociraptor cũng dùng nó làm primary key phía GUI/API nên
    không thể trùng giữa 2 máy trong inventory.
    """

    __tablename__ = "velociraptor_links"

    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)  # hostname Velociraptor trả về (giữ nguyên case)
    os_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # os_info gốc từ Velociraptor (system, release, fqdn, …)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Velociraptor last_seen
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class DfirHunt(Base):
    """Audit log cho mỗi lần admin chạy Hunt / Collect Artifact qua Velociraptor API.

    - `hunt_id`: Velociraptor hunt_id (None nếu là collect_artifact đơn lẻ).
    - `scope`: `all` (hunt trên nhiều client) hoặc `single` (collect artifact trên 1 client).
    - `status`: `pending` (đã gửi Velociraptor), `completed` (admin đóng thủ công), `error` (Velociraptor trả lỗi).
    - Audit log chính (append-only hash chain) lưu riêng ở `audit_log` với action=`dfir.hunt.create`.
    """

    __tablename__ = "dfir_hunts"
    __table_args__ = (Index("ix_dfir_hunts_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hunt_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artifact: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="all")  # "all" | "single"
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"), nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    velociraptor_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # deep-link portal mở tab mới
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))





class DfirInvestigationRequest(Base):
    """Yêu cầu điều tra DFIR do admin (non-super) tạo → Super Admin duyệt → chạy Velociraptor collect.

    Flow:
      1. Admin (org_admin, admin_global) vào trang máy, click "Yêu cầu điều tra"
         → nhập lý do + chọn artifact cần collect.
      2. Request được lưu với status='pending'.
      3. Super Admin xem list ở /dfir/requests → duyệt/reject.
      4. Khi duyệt (status='approved'), hệ thống tự chạy Velociraptor collect_artifact.
      5. Khi collect xong (Velociraptor trả flow_id), status → 'completed'.

    Mục đích: ẩn chi tiết kỹ thuật (Velociraptor, client_id, GUI URL) khỏi admin.
    Admin chỉ biết "có tính năng điều tra từ xa" và "yêu cầu điều tra".
    """

    __tablename__ = "dfir_investigation_requests"
    __table_args__ = (Index("ix_dfir_requests_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False, index=True)
    artifact: Mapped[str] = mapped_column(String(255), nullable=False)  # artifact Velociraptor sẽ chạy
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # lý do admin yêu cầu điều tra
    urgency: Mapped[str] = mapped_column(String(16), default="normal")  # "low" | "normal" | "high" | "critical"
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # "pending" (admin vừa tạo) | "approved" (super admin duyệt) | "rejected" | "running" | "completed" | "failed"
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Velociraptor internals - chỉ super admin thấy
    velociraptor_flow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    velociraptor_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class DfirSchedule(Base):
    """Lịch chạy hunt/collect định kỳ qua Velociraptor (cron-like).

    - `interval_seconds`: chạy mỗi N giây (60, 300, 3600, 86400).
    - `scope`: `all` (tất cả client) hoặc `multi` (chỉ định list machine_ids).
    - `last_run_at`: lần chạy cuối (null = chưa chạy).
    - `next_run_at`: lần chạy kế tiếp (monitor loop check).
    - Background task trong monitor.py scan mỗi phút, thực thi những schedule có
      next_run_at <= now.
    """

    __tablename__ = "dfir_schedules"
    __table_args__ = (Index("ix_dfir_schedules_next_run", "enabled", "next_run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="all")  # "all" | "multi"
    machine_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # nếu scope=multi
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class DfirAlert(Base):
    """Alert khi có flow/artifact quan trọng xuất hiện (DFIR sensitive pattern).

    - `artifact_pattern`: substring match artifact name (vd "Persistence").
    - `severity`: info / warning / critical.
    - `triggered_at`: lần alert cuối.
    - Hiện tại: chỉ record + show trên UI; chưa gửi email/webhook.
    - Phase 3: tích hợp AlertRule hiện có để gửi qua SMTP/Telegram/Zalo.
    """

    __tablename__ = "dfir_alerts"
    __table_args__ = (Index("ix_dfir_alerts_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    flow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


# ── LLM-DFIR (AI Assistant) ──────────────────────────────────────


class LlmConfig(Base):
    """Cấu hình LLM backend — singleton (id=1), Super Admin cấu hình trên portal.

    Mặc định: Ollama local (http://127.0.0.1:11434/v1) — privacy-first.
    Hỗ trợ: Ollama, LocalAI, vLLM, OpenAI, Qwen/DashScope, DeepSeek (tất cả
    OpenAI-compatible). `api_key_encrypted` AES-256-GCM (None nếu Ollama local).
    """

    __tablename__ = "llm_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(32), default="ollama")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    fallback_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(Numeric(3, 2), default=0.0)
    request_timeout: Mapped[int] = mapped_column(Integer, default=120)
    max_context_chars: Mapped[int] = mapped_column(Integer, default=200_000)
    allow_cloud: Mapped[bool] = mapped_column(Boolean, default=False)
    # External orchestrator: "" (default, dùng local LLM) | "hermes" (đợi Hermes push kết quả)
    external_orchestrator: Mapped[str] = mapped_column(String(32), default="")
    deepagent_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    deepagent_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    deepagent_service_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    daily_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used_today: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ok|error|untested
    test_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(UTC), onupdate=datetime.now(UTC)
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class DfirInvestigation(Base):
    """Mỗi lần admin trigger 'Điều tra AI' 1 máy → 1 row.

    Lifecycle: pending → running → collecting → analyzing → completed (| failed).
    - `artifacts`: list artifact Velociraptor đã collect
    - `report_markdown`: báo cáo cuối cùng từ LLM (tiếng Việt)
    - `severity`: critical|high|medium|low|info — LLM tự đánh giá
    - `raw_artifacts`: JSON thu thập từ Velociraptor (audit + cho Q&A tiếp)
    """

    __tablename__ = "dfir_investigations"
    __table_args__ = (
        Index("ix_dfir_investigations_machine_id", "machine_id"),
        Index("ix_dfir_investigations_status", "status"),
        Index("ix_dfir_investigations_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    velociraptor_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    hunt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifacts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    findings_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_artifacts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # External orchestration (P0-P5 extension): "hermes" nếu đợi external service push kết quả
    external_orchestrator: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    external_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hermes_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hermes_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    findings: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # structured findings từ Hermes
    iocs: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # IoC list từ Hermes
    callback_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(UTC), nullable=False
    )


class DfirInvestigationMessage(Base):
    """Chat Q&A với LLM về 1 cuộc điều tra. ON DELETE CASCADE."""

    __tablename__ = "dfir_investigation_messages"
    __table_args__ = (Index("ix_dfir_investigation_messages_investigation_id", "investigation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dfir_investigations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # system|user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(UTC), nullable=False
    )


# ── Notifications (P0-P5) ───────────────────────────────────────


class Notification(Base):
    """Notification gửi tới user — 4 nguồn: user (admin gửi), system, hermes, velociraptor.

    WebSocket push real-time qua Redis pub/sub `notification:user:{id}`.
    REST polling fallback khi WS không khả dụng.
    """
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient_unread", "recipient_id", "created_at",
              postgresql_where=text("read_at IS NULL")),
        Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
        Index("ix_notifications_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Nguồn & loại
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # "user" | "system" | "hermes" | "velociraptor" | "agent"
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # "investigation" | "alert" | "system" | "machine" | "security" | "message"
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    # "info" | "success" | "warning" | "error" | "critical"

    # Nội dung
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Deep-link & entity reference
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Audit (cho external call)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Read tracking
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(UTC), nullable=False
    )


class NotificationDelivery(Base):
    """Tracking gửi qua các channel ngoài (Telegram, email, webhook).

    Mỗi notification có thể gửi qua nhiều channel; 1 row / channel.
    Cho phép retry, audit, debug khi user báo không nhận được.
    """
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_notif", "notification_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    # "in_app" (đã push WS + lưu DB) | "telegram" | "email" | "webhook"
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # "pending" | "delivered" | "failed" | "skipped"
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(UTC), nullable=False
    )


class TelegramBotConfig(Base):
    """Cấu hình Telegram bot (singleton, id=1) — do Super Admin thiết lập trên portal.

    Tách phần cấu hình bot khỏi biến môi trường để toàn bộ user dùng chung
    bot do Super Admin đăng ký. Token + webhook_secret lưu dạng AES-256-GCM.

    Service layer (`telegram_runtime`) đọc qua hàm `get_bot_config(db)` — DB
    được ưu tiên, fallback env (`settings.telegram_bot_token` /
    `telegram_bot_username` / `telegram_webhook_secret`) khi DB chưa cấu hình.
    """

    __tablename__ = "telegram_bot_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_telegram_bot_config_singleton"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, server_default=text("1"))
    bot_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now(UTC), nullable=False
    )
