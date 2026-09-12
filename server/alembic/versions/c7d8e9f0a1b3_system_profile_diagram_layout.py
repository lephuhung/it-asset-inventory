"""Hồ sơ: bố cục sơ đồ React Flow (vị trí node kéo thả).

Revision ID: c7d8e9f0a1b3
Revises: b6c7d8e9f0a2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c7d8e9f0a1b3"
down_revision = "b6c7d8e9f0a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_profiles", sa.Column("diagram_layout", JSONB(), nullable=True))
    op.add_column("system_profiles", sa.Column("physical_diagram_layout", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("system_profiles", "physical_diagram_layout")
    op.drop_column("system_profiles", "diagram_layout")
