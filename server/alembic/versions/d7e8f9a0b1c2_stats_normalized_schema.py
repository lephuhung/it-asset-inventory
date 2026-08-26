"""stats normalized schema — machine_current + machine_software + OS fields

Refactor schema phục vụ thống kê (docs/REFACTOR_SCHEMA_THONG_KE.md):
- `machine_current`  — snapshot cấu hình MỚI NHẤT của mỗi máy (1:1, denormalized,
  upsert mỗi lần nhận inventory). Mọi câu đếm "hiện tại" là GROUP BY trên cột có index.
- `machine_software` — phần mềm đã cài 1 dòng/app/máy (đếm top app, độ phủ, alert software_new).
- `machine_specs`    — thêm os_product/os_release/os_family (chuẩn hóa phía server).

Revision ID: d7e8f9a0b1c2
Revises: f4a6c8e2b1d0
Create Date: 2026-08-26 09:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "f4a6c8e2b1d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── machine_specs: cột OS chuẩn hóa ─────────────────────────────
    op.add_column("machine_specs", sa.Column("os_product", sa.String(length=128), nullable=True))
    op.add_column("machine_specs", sa.Column("os_release", sa.String(length=32), nullable=True))
    op.add_column("machine_specs", sa.Column("os_family", sa.String(length=32), nullable=True))
    op.create_index("ix_machine_specs_os_family", "machine_specs", ["os_family"])

    # ── machine_current: trạng thái hiện tại 1:1 với machines ────────
    op.create_table(
        "machine_current",
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("os_name", sa.String(length=128), nullable=True),
        sa.Column("os_product", sa.String(length=128), nullable=True),
        sa.Column("os_release", sa.String(length=32), nullable=True),
        sa.Column("os_family", sa.String(length=32), nullable=True),
        sa.Column("os_version", sa.String(length=64), nullable=True),
        sa.Column("os_build", sa.String(length=32), nullable=True),
        sa.Column("os_arch", sa.String(length=16), nullable=True),
        sa.Column("os_installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_status", sa.String(length=32), nullable=True),
        sa.Column("cpu", JSONB(), nullable=True),
        sa.Column("ram_gb", sa.Float(), nullable=True),
        sa.Column("disks", JSONB(), nullable=True),
        sa.Column("gpu", JSONB(), nullable=True),
        sa.Column("mainboard", JSONB(), nullable=True),
        sa.Column("bios", JSONB(), nullable=True),
        sa.Column("network", JSONB(), nullable=True),
        sa.Column("is_vm", sa.Boolean(), nullable=True),
        sa.Column("logged_user", sa.String(length=255), nullable=True),
        sa.Column("antivirus", JSONB(), nullable=True),
        sa.Column("antivirus_enabled", sa.Boolean(), nullable=True),
        sa.Column("antivirus_up_to_date", sa.Boolean(), nullable=True),
        sa.Column("windows_update_status", sa.String(length=32), nullable=True),
        sa.Column("windows_update_enabled", sa.Boolean(), nullable=True),
        sa.Column("bitlocker", sa.String(length=16), nullable=True),
        sa.Column("firewall_enabled", sa.Boolean(), nullable=True),
        sa.Column("uac_enabled", sa.Boolean(), nullable=True),
        sa.Column("secure_boot_enabled", sa.Boolean(), nullable=True),
        sa.Column("rdp_enabled", sa.Boolean(), nullable=True),
        sa.Column("usb_storage_blocked", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_id"),
    )
    op.create_index("ix_machine_current_os_family", "machine_current", ["os_family"])
    op.create_index("ix_machine_current_firewall_enabled", "machine_current", ["firewall_enabled"])
    op.create_index("ix_machine_current_windows_update_status", "machine_current", ["windows_update_status"])
    op.create_index("ix_machine_current_windows_update_enabled", "machine_current", ["windows_update_enabled"])
    op.create_index("ix_machine_current_antivirus_enabled", "machine_current", ["antivirus_enabled"])
    op.create_index("ix_machine_current_antivirus_up_to_date", "machine_current", ["antivirus_up_to_date"])

    # ── machine_software: app đã cài, 1 dòng/app/máy ─────────────────
    op.create_table(
        "machine_software",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("install_date", sa.String(length=16), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique theo tên KHÔNG phân biệt hoa thường + index cho GROUP BY top apps
    op.create_index(
        "uq_machine_software_machine_name",
        "machine_software",
        ["machine_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "ix_machine_software_name",
        "machine_software",
        [sa.text("lower(name)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_machine_software_name", table_name="machine_software")
    op.drop_index("uq_machine_software_machine_name", table_name="machine_software")
    op.drop_table("machine_software")

    op.drop_index("ix_machine_current_antivirus_up_to_date", table_name="machine_current")
    op.drop_index("ix_machine_current_antivirus_enabled", table_name="machine_current")
    op.drop_index("ix_machine_current_windows_update_enabled", table_name="machine_current")
    op.drop_index("ix_machine_current_windows_update_status", table_name="machine_current")
    op.drop_index("ix_machine_current_firewall_enabled", table_name="machine_current")
    op.drop_index("ix_machine_current_os_family", table_name="machine_current")
    op.drop_table("machine_current")

    op.drop_index("ix_machine_specs_os_family", table_name="machine_specs")
    op.drop_column("machine_specs", "os_family")
    op.drop_column("machine_specs", "os_release")
    op.drop_column("machine_specs", "os_product")
