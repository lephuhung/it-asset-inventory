"""Thêm external_orchestrator vào llm_config.

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
Create Date: 2026-08-30 01:30:00.000000

Khi `external_orchestrator='hermes'`: orchestrator chỉ thu thập Velociraptor data,
KHÔNG gọi LLM local. Đợi Hermes (hoặc service khác) POST kết quả về endpoint
`/api/external/llm-dfir/investigations/{id}/result`.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "q5r6s7t8u9v0"
down_revision = "p4q5r6s7t8u9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_config",
        sa.Column("external_orchestrator", sa.String(32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("llm_config", "external_orchestrator")
