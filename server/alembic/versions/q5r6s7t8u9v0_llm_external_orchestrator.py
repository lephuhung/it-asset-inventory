"""Thêm external_orchestrator vào llm_config.

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
Create Date: 2026-08-30 01:30:00.000000

Khi `external_orchestrator='hermes'`: orchestrator chỉ thu thập Velociraptor data,
KHÔNG gọi LLM local. Đợi Hermes (hoặc service khác) POST kết quả về endpoint
`/api/external/llm-dfir/investigations/{id}/result`.
"""
from __future__ import annotations

revision = "q5r6s7t8u9v0"
down_revision = "p4q5r6s7t8u9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # p4q5r6s7t8u9 already owns creation of this column.
    pass


def downgrade() -> None:
    # p4q5r6s7t8u9 owns removal after this child revision is downgraded.
    pass
