"""Add system_profiles, system_devices, system_profile_machines tables.

Revision ID: a1b2c3d4e5f7
Revises: z4a5b6c7d8e9
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="drafted", index=True),
        sa.Column("decision_number", sa.String(length=255), nullable=True),
        sa.Column("decision_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_agency", sa.String(length=255), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("diagram_mermaid", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "code", name="uq_system_profiles_org_code"),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_system_profiles_level"),
    )
    op.create_table(
        "system_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("device_code", sa.String(length=128), nullable=True),
        sa.Column("tag", sa.String(length=128), nullable=True),
        sa.Column("device_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "system_profile_machines",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("system_profile_machines")
    op.drop_table("system_devices")
    op.drop_table("system_profiles")
