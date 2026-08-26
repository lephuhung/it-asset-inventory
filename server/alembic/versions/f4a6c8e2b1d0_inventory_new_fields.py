"""inventory new fields (os_installed_at, activation_status, mainboard, bios, installed_software)

Revision ID: f4a6c8e2b1d0
Revises: e1d2f3a4b5c6
Create Date: 2026-08-26 08:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "f4a6c8e2b1d0"
down_revision = "e1d2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machine_specs", sa.Column("os_installed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("machine_specs", sa.Column("activation_status", sa.String(length=32), nullable=True))
    op.add_column("machine_specs", sa.Column("mainboard", JSONB(), nullable=True))
    op.add_column("machine_specs", sa.Column("bios", JSONB(), nullable=True))
    op.add_column("machine_specs", sa.Column("installed_software", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("machine_specs", "installed_software")
    op.drop_column("machine_specs", "bios")
    op.drop_column("machine_specs", "mainboard")
    op.drop_column("machine_specs", "activation_status")
    op.drop_column("machine_specs", "os_installed_at")
