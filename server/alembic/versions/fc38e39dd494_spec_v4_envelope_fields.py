"""spec v4 envelope fields — store agent + os_metadata + schema_version per snapshot

Revision ID: fc38e39dd494
Revises: 46ec4332a98e
Create Date: 2026-08-30 15:52:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "fc38e39dd494"
down_revision = "46ec4332a98e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machine_specs", sa.Column("agent", JSONB, nullable=True))
    op.add_column("machine_specs", sa.Column("os_metadata", JSONB, nullable=True))
    op.add_column("machine_specs", sa.Column("inventory_schema_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("machine_specs", "inventory_schema_version")
    op.drop_column("machine_specs", "os_metadata")
    op.drop_column("machine_specs", "agent")