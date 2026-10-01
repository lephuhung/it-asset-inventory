"""Hồ sơ dossier: parties, applications, ip_ranges + scope fields + device location/purpose.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mở rộng system_profiles — phạm vi & quy mô + sơ đồ vật lý
    op.add_column("system_profiles", sa.Column("physical_diagram_mermaid", sa.Text(), nullable=True))
    op.add_column("system_profiles", sa.Column("physical_location", sa.Text(), nullable=True))
    op.add_column("system_profiles", sa.Column("user_accounts", sa.Integer(), nullable=True))
    op.add_column("system_profiles", sa.Column("data_volume", sa.Text(), nullable=True))
    op.add_column("system_profiles", sa.Column("service_audience", sa.String(length=32), nullable=True, server_default="internal"))

    # Mở rộng system_devices — vị trí triển khai + mục đích sử dụng
    op.add_column("system_devices", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("system_devices", sa.Column("purpose", sa.Text(), nullable=True))

    op.create_table(
        "system_profile_parties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="owner"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mandate_document", sa.Text(), nullable=True),
        sa.Column("legal_representative", sa.String(length=255), nullable=True),
        sa.Column("representative_title", sa.String(length=128), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("profile_id", "role", name="uq_system_profile_party_role"),
    )
    op.create_table(
        "system_profile_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("server_name", sa.String(length=255), nullable=True),
        sa.Column("os_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_table(
        "system_profile_ip_ranges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("zone", sa.String(length=128), nullable=False),
        sa.Column("zone_description", sa.Text(), nullable=True),
        sa.Column("cidr", sa.String(length=64), nullable=False),
        sa.Column("ip_kind", sa.String(length=16), nullable=False, server_default="private"),
        sa.Column("gateway", sa.String(length=45), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("system_profile_ip_ranges")
    op.drop_table("system_profile_applications")
    op.drop_table("system_profile_parties")
    op.drop_column("system_devices", "purpose")
    op.drop_column("system_devices", "location")
    op.drop_column("system_profiles", "service_audience")
    op.drop_column("system_profiles", "data_volume")
    op.drop_column("system_profiles", "user_accounts")
    op.drop_column("system_profiles", "physical_location")
    op.drop_column("system_profiles", "physical_diagram_mermaid")
