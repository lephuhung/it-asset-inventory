"""Danh bạ chuyên trách CNTT/tổ chức vận hành + liên kết hồ sơ.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "it_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="person"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=255), nullable=True),
        sa.Column("contact_person", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "system_profile_contacts",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("it_contacts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_profile_contacts")
    op.drop_table("it_contacts")
