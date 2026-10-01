"""Add enroll_attempts — hàng đợi yêu cầu enroll bị từ chối (token cũ/hết hạn).

Revision ID: h9i0j1k2l3m4
Revises: d8e9f0a1b2c4
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "h9i0j1k2l3m4"
down_revision = "d8e9f0a1b2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enroll_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("enroll_tokens.id"), nullable=True),
        sa.Column("token_status", sa.String(length=16), nullable=False),
        sa.Column("token_prefix", sa.String(length=24), nullable=True),
        sa.Column("machine_uuid", sa.String(length=64), nullable=True, index=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("fingerprint", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("matched_machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_enroll_attempts_status", "enroll_attempts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_enroll_attempts_status", table_name="enroll_attempts")
    op.drop_table("enroll_attempts")
