"""velociraptor — tích hợp Velociraptor Server cho DFIR

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-08-28 10:00:00.000000

Tích hợp Velociraptor (https://github.com/velocidex/velociraptor) phục vụ DFIR
(Digital Forensics & Incident Response). Backend đồng bộ hostname ↔ client_id
qua REST API mỗi 5 phút; portal deep-link sang Velociraptor GUI để admin
chạy hunt/collect artifact.

3 bảng mới:
- `velociraptor_config`: cấu hình singleton (URL + encrypted API token + allowlist)
- `velociraptor_links`: mapping machine_id ↔ Velociraptor client_id (1-1)
- `dfir_hunts`: audit log cho mỗi lần admin chạy hunt/collect
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "i8j9k0l1m2n3"
down_revision = "h7i8j9k0l1m2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. velociraptor_config — singleton (id=1)
    op.create_table(
        "velociraptor_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("server_url", sa.String(length=512), nullable=True),
        sa.Column("api_token_encrypted", sa.Text(), nullable=True),
        sa.Column("allowlist", JSONB, nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("last_sync_linked", sa.Integer(), nullable=True),
        sa.Column("last_sync_total", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "updated_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 2. velociraptor_links — mapping machine ↔ Velociraptor client
    op.create_table(
        "velociraptor_links",
        sa.Column(
            "machine_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("os_info", JSONB, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_velociraptor_links_client_id",
        "velociraptor_links",
        ["client_id"],
        unique=True,
    )
    op.create_index(
        "ix_velociraptor_links_hostname_lower",
        "velociraptor_links",
        [sa.text("lower(hostname)")],
    )

    # 3. dfir_hunts — audit log cho hunt/collect
    op.create_table(
        "dfir_hunts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("hunt_id", sa.String(length=64), nullable=True),
        sa.Column("artifact", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="all"),
        sa.Column(
            "machine_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("velociraptor_url", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_dfir_hunts_created_at", "dfir_hunts", ["created_at"])
    op.create_index(
        "ix_dfir_hunts_hunt_id",
        "dfir_hunts",
        ["hunt_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dfir_hunts_hunt_id", table_name="dfir_hunts")
    op.drop_index("ix_dfir_hunts_created_at", table_name="dfir_hunts")
    op.drop_table("dfir_hunts")
    op.drop_index("ix_velociraptor_links_hostname_lower", table_name="velociraptor_links")
    op.drop_index("ix_velociraptor_links_client_id", table_name="velociraptor_links")
    op.drop_table("velociraptor_links")
    op.drop_table("velociraptor_config")
