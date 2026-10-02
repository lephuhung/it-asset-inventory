"""chat assistant schema (conversations, turns, messages, tool_calls, audit_intents, token_reservations)

Task 2 của Chat Assistant P1. Tạo 6 bảng mới theo spec §"Hợp đồng dữ liệu":
chat_conversations → chat_turns → chat_messages → chat_tool_calls →
chat_audit_intents → token_reservations.

Ghi chú:
- `chat_audit_intents` cố ý KHÔNG có FK tới bảng chat (R2: sống sót khi xoá
  hội thoại/user).
- `chat_messages` có composite FK `(conversation_id, turn_id)` →
  `chat_turns(conversation_id, id)` buộc message thuộc đúng hội thoại; đích cần
  `UNIQUE (conversation_id, id)` trên chat_turns.
- `uq_chat_turn_active` là partial unique index: 1 turn active/hội thoại.
- `audit_intent_id`/`audit_outcome_id` là INTEGER khớp `audit_log.id`.

Revision ID: d2e3f4a5b6c7
Revises: c1f2e3d4a5b6
Create Date: 2026-10-02 15:05:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1f2e3d4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_chat_conv_owner",
        "chat_conversations",
        ["created_by", sa.text("last_message_at DESC")],
    )

    op.create_table(
        "chat_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Snapshot actor — plain UUID, không FK (intent/audit sống sót theo vết).
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Snapshot per-turn (mutable lookup, KHÔNG nằm trong hash).
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Định danh bất biến (client_id/hostname) — có hash.
        sa.Column("machine_ref", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("finish_reason", sa.String(length=16), nullable=True),
        sa.Column("completion_token_hash", sa.String(length=64), nullable=True),
        sa.Column("completion_committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=48), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("conversation_id", "idempotency_key", name="uq_chat_turn_idem"),
        # Đích cho composite FK của chat_messages.
        sa.UniqueConstraint("conversation_id", "id", name="uq_chat_turn_conv_id"),
    )
    op.create_index(
        "uq_chat_turn_active",
        "chat_turns",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','streaming')"),
    )
    op.create_index("ix_chat_turn_status", "chat_turns", ["status", "created_at"])

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Snapshot ngữ cảnh lượt — không hash.
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_category", sa.String(length=48), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Composite FK: message phải thuộc cùng hội thoại với turn của nó.
        sa.ForeignKeyConstraint(
            ["conversation_id", "turn_id"],
            ["chat_turns.conversation_id", "chat_turns.id"],
            name="fk_chat_msg_turn",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("role = 'system' OR turn_id IS NOT NULL", name="ck_chat_msg_turn"),
    )
    op.create_index("ix_chat_msg_conv", "chat_messages", ["conversation_id", "created_at", "id"])

    op.create_table(
        "chat_tool_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_call_id", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("args_digest", sa.String(length=64), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("byte_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("flow_id", sa.String(length=64), nullable=True),
        sa.Column(
            "audit_intent_id",
            sa.Integer(),
            sa.ForeignKey("audit_log.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "audit_outcome_id",
            sa.Integer(),
            sa.ForeignKey("audit_log.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("turn_id", "tool_call_id", name="uq_chat_tool_call"),
    )
    op.create_index("ix_chat_tool_calls_turn", "chat_tool_calls", ["turn_id"])

    # Bền vững, KHÔNG FK tới bảng chat (sống sót khi xoá hội thoại/user).
    op.create_table(
        "chat_audit_intents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("args_digest", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("flow_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("turn_id", "tool_call_id", name="uq_chat_audit_intent"),
    )
    op.create_index(
        "ix_chat_audit_intents_open", "chat_audit_intents", ["outcome", "created_at"]
    )

    op.create_table(
        "token_reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("association_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("budget_date", sa.Date(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("actual", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="reserved"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("scope", "operation_id", name="uq_token_reservation"),
    )
    op.create_index("ix_token_reservations_day", "token_reservations", ["budget_date", "state"])


def downgrade() -> None:
    op.drop_index("ix_token_reservations_day", table_name="token_reservations")
    op.drop_table("token_reservations")

    op.drop_index("ix_chat_audit_intents_open", table_name="chat_audit_intents")
    op.drop_table("chat_audit_intents")

    op.drop_index("ix_chat_tool_calls_turn", table_name="chat_tool_calls")
    op.drop_table("chat_tool_calls")

    op.drop_index("ix_chat_msg_conv", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_turn_status", table_name="chat_turns")
    op.drop_index("uq_chat_turn_active", table_name="chat_turns")
    op.drop_table("chat_turns")

    op.drop_index("ix_chat_conv_owner", table_name="chat_conversations")
    op.drop_table("chat_conversations")
