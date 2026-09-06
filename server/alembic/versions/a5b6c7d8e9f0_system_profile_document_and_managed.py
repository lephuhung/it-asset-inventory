"""Hồ sơ: số văn bản đề nghị + ngày văn bản + tên chủ quản.

Revision ID: a5b6c7d8e9f0
Revises: d4e5f6a7b8c9
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_profiles", sa.Column("document_number", sa.String(length=128), nullable=True))
    op.add_column("system_profiles", sa.Column("document_date", sa.Date(), nullable=True))
    op.add_column("system_profiles", sa.Column("managed_by", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("system_profiles", "managed_by")
    op.drop_column("system_profiles", "document_date")
    op.drop_column("system_profiles", "document_number")
