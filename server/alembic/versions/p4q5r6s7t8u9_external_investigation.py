"""External investigation orchestration — Hermes push kết quả.

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
Create Date: 2026-08-30 01:00:00.000000

Thêm cột cho DfirInvestigation để hỗ trợ external orchestrator (Hermes):
- `external_orchestrator`: "hermes" nếu đang đợi external service push kết quả
- `external_job_id`: job id phía Hermes (correlate)
- `external_polled_at`: lần cuối Hermes poll
- `hermes_status`, `hermes_response`, `findings`, `iocs`, `callback_received_at`

Không thay đổi flow cũ (local LLM vẫn hoạt động bình thường).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "p4q5r6s7t8u9"
down_revision = "o3p4q5r6s7t8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_config",
        sa.Column("external_orchestrator", sa.String(32), nullable=False, server_default=""),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("external_orchestrator", sa.String(32), nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("external_job_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("external_polled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("hermes_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("hermes_response", JSONB, nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("findings", JSONB, nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("iocs", JSONB, nullable=True),
    )
    op.add_column(
        "dfir_investigations",
        sa.Column("callback_received_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dfir_investigations_external_job_id",
        "dfir_investigations",
        ["external_job_id"],
    )
    op.create_index(
        "ix_dfir_investigations_external_orchestrator",
        "dfir_investigations",
        ["external_orchestrator"],
    )


def downgrade() -> None:
    op.drop_column("llm_config", "external_orchestrator")
    op.drop_index("ix_dfir_investigations_external_orchestrator", table_name="dfir_investigations")
    op.drop_index("ix_dfir_investigations_external_job_id", table_name="dfir_investigations")
    op.drop_column("dfir_investigations", "callback_received_at")
    op.drop_column("dfir_investigations", "iocs")
    op.drop_column("dfir_investigations", "findings")
    op.drop_column("dfir_investigations", "hermes_response")
    op.drop_column("dfir_investigations", "hermes_status")
    op.drop_column("dfir_investigations", "external_polled_at")
    op.drop_column("dfir_investigations", "external_job_id")
    op.drop_column("dfir_investigations", "external_orchestrator")
