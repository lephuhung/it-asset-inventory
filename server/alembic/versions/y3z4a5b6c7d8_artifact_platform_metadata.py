"""Add explicit platform eligibility and priority to custom artifacts.

Revision ID: y3z4a5b6c7d8
Revises: x2y3z4a5b6c7
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "y3z4a5b6c7d8"
down_revision = "x2y3z4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "velociraptor_artifacts",
        sa.Column(
            "supported_platforms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"windows\"]'::jsonb"),
        ),
    )
    op.add_column(
        "velociraptor_artifacts",
        sa.Column("selection_priority", sa.Integer(), nullable=False, server_default="100"),
    )


def downgrade() -> None:
    op.drop_column("velociraptor_artifacts", "selection_priority")
    op.drop_column("velociraptor_artifacts", "supported_platforms")
