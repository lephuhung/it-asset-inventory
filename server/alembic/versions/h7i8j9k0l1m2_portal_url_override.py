"""portal_url override — thêm cột IP/Domain Portal công khai vào agent_config_override

Revision ID: h7i8j9k0l1m2
Revises: c5416fb6b905
Create Date: 2026-08-27 10:00:00.000000

Trước đây portal chỉ nhúng URL vào `install_command` (lệnh copy khi sinh token) và
`enroll_url` (self-service) từ biến môi trường `PORTAL_URL`. Khi triển khai nhiều
môi trường (dev/staging/prod) mà quên đổi `.env` → URL bị `127.0.0.1` → user copy
lệnh chạy trên máy thật không kết nối được server.

Thêm cột `portal_url` vào bảng 1-dòng `agent_config_override` để Super Admin chỉnh
trực tiếp từ portal (UI "Cấu hình Agent" — trang /agent-config), không cần SSH vào
server để sửa .env + alembic upgrade.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "h7i8j9k0l1m2"
down_revision = "c5416fb6b905"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_config_override",
        sa.Column("portal_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_config_override", "portal_url")