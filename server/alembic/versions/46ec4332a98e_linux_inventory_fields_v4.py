"""linux inventory fields v4 — add cross-platform columns to machine_current

Adds columns to `machine_current` for cross-platform stats (Linux + Windows).
Existing legacy columns (`windows_update_*`, `rdp_enabled`, `bitlocker`)
are KEPT for backward compat. New v4 columns are additive.

Revision ID: 46ec4332a98e
Revises: q5r6s7t8u9v0
Create Date: 2026-08-30 15:51:00.968743
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "46ec4332a98e"
down_revision = "q5r6s7t8u9v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machine_current", sa.Column("platform", sa.String(length=16), nullable=True))
    op.add_column("machine_current", sa.Column("agent_version", sa.String(length=32), nullable=True))
    op.add_column("machine_current", sa.Column("update_status", sa.String(length=32), nullable=True))
    op.add_column("machine_current", sa.Column("update_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("updates_pending", sa.Integer(), nullable=True))
    op.add_column("machine_current", sa.Column("endpoint_protection_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("disk_encryption_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("disk_encryption_technology", sa.String(length=32), nullable=True))
    op.add_column("machine_current", sa.Column("ssh_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("remote_desktop_enabled", sa.Boolean(), nullable=True))
    op.create_index("ix_machine_current_platform", "machine_current", ["platform"])
    op.create_index("ix_machine_current_update_status", "machine_current", ["update_status"])


def downgrade() -> None:
    op.drop_index("ix_machine_current_update_status", table_name="machine_current")
    op.drop_index("ix_machine_current_platform", table_name="machine_current")
    op.drop_column("machine_current", "remote_desktop_enabled")
    op.drop_column("machine_current", "ssh_enabled")
    op.drop_column("machine_current", "disk_encryption_technology")
    op.drop_column("machine_current", "disk_encryption_enabled")
    op.drop_column("machine_current", "endpoint_protection_enabled")
    op.drop_column("machine_current", "updates_pending")
    op.drop_column("machine_current", "update_enabled")
    op.drop_column("machine_current", "update_status")
    op.drop_column("machine_current", "agent_version")
    op.drop_column("machine_current", "platform")