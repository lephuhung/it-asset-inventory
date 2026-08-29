"""velociraptor_schedules + dfir_alerts — cho Phase 2 (bulk + schedule + alerts)

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-08-29 03:30:00.000000

Thêm 2 bảng mới:
- `dfir_schedules`: lịch chạy hunt/collect artifact định kỳ (cron-like, đơn giản hóa
  thành interval_seconds). Background task trong monitor.py scan mỗi phút.
- `dfir_alerts`: ghi nhận alert khi có flow/artifact sensitive xuất hiện. Hiện tại chỉ
  record + show trên UI (Phase 3 sẽ gửi qua AlertRule channels SMTP/Telegram/Zalo).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "l1m2n3o4p5q6"
down_revision = "k0l1m2n3o4p5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dfir_schedules
    op.create_table(
        "dfir_schedules",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("artifact", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="all"),
        sa.Column("machine_ids", JSONB, nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_dfir_schedules_next_run", "dfir_schedules", ["enabled", "next_run_at"])

    # dfir_alerts
    op.create_table(
        "dfir_alerts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("artifact_pattern", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="warning"),
        sa.Column("flow_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("machine_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_dfir_alerts_created_at", "dfir_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_dfir_alerts_created_at", table_name="dfir_alerts")
    op.drop_table("dfir_alerts")
    op.drop_index("ix_dfir_schedules_next_run", table_name="dfir_schedules")
    op.drop_table("dfir_schedules")
