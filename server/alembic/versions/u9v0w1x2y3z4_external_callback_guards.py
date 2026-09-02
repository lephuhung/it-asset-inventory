"""Add callback idempotency binding for external investigations.

Revision ID: u9v0w1x2y3z4
Revises: t8u9v0w1x2y3
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "u9v0w1x2y3z4"
down_revision = "t8u9v0w1x2y3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dfir_investigations",
        sa.Column("external_callback_idempotency_key", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dfir_investigations", "external_callback_idempotency_key")
