"""Telegram bot config — singleton row do Super Admin cấu hình trên portal.

Revision ID: s7t8u9v0w1x2
Revises: r6s7t8u9v0w1

Tách phần cấu hình bot Telegram ra khỏi biến môi trường (.env):
- `telegram_bot_config` — 1 dòng (id=1), lưu token + username + webhook secret (đã mã hoá AES-GCM).
- Bot token / username dùng cho: gửi notification (delivery), tạo deep-link `/start <token>`
  để user link tài khoản, webhook callback `/api/external/telegram/callback`.

Trước đây 3 giá trị này nằm trong `settings.telegram_*` (env). Nay Super Admin có
thể set trên portal tại `/admin/telegram-bot`. Service layer sẽ ưu tiên giá trị
trong DB, fallback env khi DB chưa có.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "s7t8u9v0w1x2"
down_revision = "r6s7t8u9v0w1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_bot_config",
        sa.Column("id", sa.Integer(), primary_key=True, server_default=sa.text("1")),
        # Token + secret: lưu dạng AES-256-GCM (base64). Username plaintext để hiển thị / deep-link.
        sa.Column("bot_token_encrypted", sa.Text(), nullable=True),
        sa.Column("bot_username", sa.String(64), nullable=True),
        sa.Column("webhook_secret", sa.String(128), nullable=True),
        # Tuỳ chọn bật/tắt: super admin có thể tắt để tạm dừng delivery.
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Audit
        sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("id = 1", name="ck_telegram_bot_config_singleton"),
    )


def downgrade() -> None:
    op.drop_table("telegram_bot_config")