"""LLM-DFIR — bảng cấu hình LLM + investigation + chat messages.

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-08-29 16:00:00.000000

Tạo 3 bảng mới phục vụ tích hợp Model LLM (Ollama/OpenAI-compatible) để
phân tích, điều tra sự cố an ninh mạng qua Velociraptor:

- `llm_config` (singleton, id=1): URL + provider + model + API key (mã hoá).
- `dfir_investigations`: mỗi lần admin trigger điều tra 1 máy → 1 row.
- `dfir_investigation_messages`: chat Q&A với LLM về cuộc điều tra.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. llm_config — singleton
    op.create_table(
        "llm_config",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.String(32), nullable=False, server_default="ollama"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("fallback_model", sa.String(128), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="4096"),
        sa.Column("temperature", sa.Numeric(3, 2), nullable=False, server_default="0.0"),
        sa.Column("request_timeout", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("max_context_chars", sa.Integer(), nullable=False, server_default="200000"),
        sa.Column("allow_cloud", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("daily_token_budget", sa.Integer(), nullable=True),
        sa.Column("tokens_used_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_status", sa.String(32), nullable=True),
        sa.Column("test_error", sa.Text(), nullable=True),
        sa.Column("test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )

    # Seed default row (id=1) — disabled, pointing to local Ollama
    op.execute(
        """
        INSERT INTO llm_config (id, enabled, provider, base_url, model)
        VALUES (1, false, 'ollama', 'http://127.0.0.1:11434/v1', 'qwen2.5:14b-instruct-q4_K_M')
        ON CONFLICT (id) DO NOTHING
        """
    )

    # 2. dfir_investigations
    op.create_table(
        "dfir_investigations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("machine_id", UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("velociraptor_client_id", sa.String(64), nullable=True),
        sa.Column("hunt_id", sa.String(64), nullable=True),
        sa.Column("flow_id", sa.String(64), nullable=True),
        sa.Column("artifacts", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("llm_provider", sa.String(32), nullable=True),
        sa.Column("llm_model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("report_markdown", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("findings_count", sa.Integer(), nullable=True),
        sa.Column("raw_artifacts", JSONB, nullable=True),
        sa.Column("custom_instructions", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_dfir_investigations_machine_id", "dfir_investigations", ["machine_id"])
    op.create_index(
        "ix_dfir_investigations_velociraptor_client_id",
        "dfir_investigations",
        ["velociraptor_client_id"],
    )
    op.create_index("ix_dfir_investigations_status", "dfir_investigations", ["status"])
    op.create_index("ix_dfir_investigations_created_at", "dfir_investigations", ["created_at"])

    # 3. dfir_investigation_messages
    op.create_table(
        "dfir_investigation_messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "investigation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dfir_investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_dfir_investigation_messages_investigation_id",
        "dfir_investigation_messages",
        ["investigation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dfir_investigation_messages_investigation_id", table_name="dfir_investigation_messages"
    )
    op.drop_table("dfir_investigation_messages")

    op.drop_index("ix_dfir_investigations_created_at", table_name="dfir_investigations")
    op.drop_index("ix_dfir_investigations_status", table_name="dfir_investigations")
    op.drop_index(
        "ix_dfir_investigations_velociraptor_client_id", table_name="dfir_investigations"
    )
    op.drop_index("ix_dfir_investigations_machine_id", table_name="dfir_investigations")
    op.drop_table("dfir_investigations")

    op.drop_table("llm_config")
