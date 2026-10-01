"""Add device_types catalog (seed 8 loại chuẩn).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

SEED_DEVICE_TYPES: list[tuple[str, str, str]] = [
    ("firewall", "Firewall", "🛡️"),
    ("router", "Router", "📡"),
    ("switch", "Switch", "🔀"),
    ("server", "Máy chủ", "🖥️"),
    ("workstation", "Máy trạm", "💻"),
    ("storage", "Hệ thống lưu trữ", "💾"),
    ("ups", "UPS", "🔋"),
    ("other", "Khác", "📦"),
]


def upgrade() -> None:
    op.create_table(
        "device_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for i, (code, label, icon) in enumerate(SEED_DEVICE_TYPES):
        op.execute(
            sa.text(
                "INSERT INTO device_types (id, code, label, icon, sort_order, is_active) "
                "VALUES (:id, :code, :label, :icon, :i, true)"
            ).bindparams(id=uuid.uuid4(), code=code, label=label, icon=icon, i=i)
        )


def downgrade() -> None:
    op.drop_table("device_types")
