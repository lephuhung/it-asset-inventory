"""Raise the DFIR LLM completion-token default to 64000.

Revision ID: v0w1x2y3z4a5
Revises: u9v0w1x2y3z4
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "v0w1x2y3z4a5"
down_revision = "u9v0w1x2y3z4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "llm_config",
        "max_tokens",
        existing_type=sa.Integer(),
        server_default="64000",
    )
    op.execute("UPDATE llm_config SET max_tokens = 64000")


def downgrade() -> None:
    op.alter_column(
        "llm_config",
        "max_tokens",
        existing_type=sa.Integer(),
        server_default="4096",
    )
