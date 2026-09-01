"""Store portal-managed DeepAgent service settings.

Revision ID: r6s7t8u9v0w1
Revises: 87c54eca9b35
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r6s7t8u9v0w1"
down_revision = "87c54eca9b35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_config", sa.Column("deepagent_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("llm_config", sa.Column("deepagent_url", sa.String(length=512), nullable=True))
    op.add_column("llm_config", sa.Column("deepagent_service_token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_config", "deepagent_service_token_encrypted")
    op.drop_column("llm_config", "deepagent_url")
    op.drop_column("llm_config", "deepagent_enabled")
