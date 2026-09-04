"""agent public_ip field

Lưu IP public (WAN) mà agent phát hiện được — dùng cho:
- Hiển thị trên portal (mỗi máy → IP public)
- Phát hiện máy ra/vào VPN, IP WAN động
- Tương quan với heartbeat IP (LAN) — phát hiện NAT/proxy

Revision ID: g8h9j0k1l2m3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-27 12:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "g8h9j0k1l2m3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
# machine_current is created on the sibling stats-schema branch.
depends_on = "d7e8f9a0b1c2"


def upgrade() -> None:
    # Snapshot lịch sử — IP public thay đổi theo thời gian nên muốn xem lịch sử
    op.add_column("machine_specs", sa.Column("public_ip", sa.String(length=45), nullable=True))

    # Bảng current — IP public mới nhất (denormalized cho stats/list)
    op.add_column("machine_current", sa.Column("public_ip", sa.String(length=45), nullable=True, index=True))

    # Bảng máy — cache IP mới nhất (để hiển thị nhanh ngay cả khi máy offline lâu)
    op.add_column("machines", sa.Column("public_ip", sa.String(length=45), nullable=True))


def downgrade() -> None:
    op.drop_column("machines", "public_ip")
    op.drop_column("machine_current", "public_ip")
    op.drop_column("machine_specs", "public_ip")
