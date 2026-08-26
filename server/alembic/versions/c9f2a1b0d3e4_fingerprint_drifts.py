"""fingerprint drifts (Phase 3)

Revision ID: c9f2a1b0d3e4
Revises: 70786f173f6e
Create Date: 2026-08-25 13:40:00.000000

Bảng cảnh báo fingerprint thay đổi (đổi mainboard / ghost Win) — admin duyệt.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c9f2a1b0d3e4"
down_revision = "70786f173f6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fingerprint_drifts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("old_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("new_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("fingerprint_drifts")