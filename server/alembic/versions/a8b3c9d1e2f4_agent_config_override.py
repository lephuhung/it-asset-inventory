"""agent config override — bảng 1 dòng cho cấu hình agent chỉnh từ portal

Revision ID: a8b3c9d1e2f4
Revises: d7e8f9a0b1c2
Create Date: 2026-08-26 12:30:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a8b3c9d1e2f4"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_config_override",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("heartbeat_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("heartbeat_jitter_seconds", sa.Integer(), nullable=True),
        sa.Column("inventory_interval_hours", sa.Integer(), nullable=True),
        sa.Column("agent_server_url", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_config_override")
