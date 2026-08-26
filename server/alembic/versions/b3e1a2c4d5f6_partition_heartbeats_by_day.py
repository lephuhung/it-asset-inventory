"""partition heartbeats by day

Revision ID: b3e1a2c4d5f6
Revises: a6918c1757eb
Create Date: 2026-08-24

Chuyển `heartbeats` sang bảng PARTITION BY RANGE (ts) theo ngày (mục 5.1 tài liệu gốc).
Có DEFAULT partition → mọi write không bao giờ lỗi; job tự tạo daily partition (services/partition.py).
Note: bước này destructive (drop + recreate) — chỉ áp dụng trước khi có dữ liệu production.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3e1a2c4d5f6"
down_revision = "a6918c1757eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop bảng cũ (dev/prod mới — không giữ dữ liệu)
    op.execute("DROP TABLE IF EXISTS heartbeats")

    # Tạo bảng partition root — RANGE theo ts (ngày). PK phải gồm partition key (ts).
    op.execute(
        """
        CREATE TABLE heartbeats (
            id           BIGSERIAL,
            machine_id   UUID NOT NULL REFERENCES machines(id),
            ts           TIMESTAMPTZ NOT NULL,
            ip           VARCHAR(45),
            logged_user  VARCHAR(255),
            uptime_sec   INTEGER,
            PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )

    # DEFAULT partition — đảm bảo luôn có chỗ ghi (job sẽ chia nhỏ theo ngày)
    op.execute("CREATE TABLE heartbeats_default PARTITION OF heartbeats DEFAULT")

    # Index trên parent (tự áp dụng cho từng partition trong PG)
    op.execute("CREATE INDEX ix_heartbeats_machine_ts ON heartbeats (machine_id, ts)")
    op.execute("CREATE INDEX ix_heartbeats_ts ON heartbeats (ts)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS heartbeats")
    op.create_table(
        "heartbeats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("logged_user", sa.String(length=255), nullable=True),
        sa.Column("uptime_sec", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_heartbeats_machine_ts", "heartbeats", ["machine_id", "ts"], unique=False)
    op.create_index(op.f("ix_heartbeats_ts"), "heartbeats", ["ts"], unique=False)
