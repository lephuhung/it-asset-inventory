"""audit_log hash version + structured details

Task 1 của Chat Assistant P1. Bổ sung:
- `details` (JSONB): metadata có cấu trúc, hash-bound ở v2 (vd `machine_ref`).
- `hash_version` (SMALLINT, server_default=1): backfill hàng legacy = 1; hàng
  mới do `append_audit` ghi = 2.

Backfill giữ nguyên `content_hash` của hàng cũ (không viết lại hash lịch sử);
`verify_chain` dispatch công thức theo giá trị cột này.

Revision ID: c1f2e3d4a5b6
Revises: i0j1k2l3m4n5
Create Date: 2026-10-02 14:50:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c1f2e3d4a5b6"
down_revision = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("details", postgresql.JSONB(), nullable=True))
    op.add_column(
        "audit_log",
        sa.Column("hash_version", sa.SmallInteger(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "hash_version")
    op.drop_column("audit_log", "details")
