"""Theo dõi kích hoạt tài khoản + bắt buộc đổi mật khẩu lần đầu.

- `users.last_login_at`        — lần đăng nhập thành công gần nhất (NULL = chưa kích hoạt).
- `users.must_change_password` — True → mọi API (trừ auth.me/change-password/logout)
  trả 403 PASSWORD_CHANGE_REQUIRED cho tới khi user tự đổi mật khẩu.

Backfill fail-closed: các tài khoản org_admin seed sẵn (email @hatinh.gov.vn)
được gắn cờ phải đổi mật khẩu. Tài khoản đã tự đổi mật khẩu trước đó sẽ phải
đổi thêm một lần nữa — chấp nhận được vì không thể kiểm chứng bcrypt trong SQL
và hướng an toàn là bắt buộc đổi.

Revision ID: w1x2y3z4a5b6
Revises: v0w1x2y3z4a5
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "w1x2y3z4a5b6"
down_revision = "v0w1x2y3z4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # 82 tài khoản quản trị đơn vị seed sẵn vẫn dùng mật khẩu mặc định → bắt đổi lần đầu.
    op.execute(
        "UPDATE users SET must_change_password = true "
        "WHERE role = 'org_admin' AND email LIKE '%@hatinh.gov.vn'"
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "last_login_at")
