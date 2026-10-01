"""Add refresh_tokens table, users.totp_last_counter; drop enroll_tokens.max_uses.

- refresh_tokens: lưu SHA-256 hash của refresh token đã phát hành → hỗ trợ
  rotation, revoke khi đổi/reset mật khẩu, reuse detection theo family.
- users.totp_last_counter: time-step TOTP cuối được chấp nhận → chống replay
  mã 2FA (mã đúng nhưng counter cũ bị từ chối).
- enroll_tokens.max_uses: dead field — enroll luôn mark USED sau 1 lần,
  bỏ để khỏi gây hiểu nhầm "1 token nhiều máy".

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "i0j1k2l3m4n5"
down_revision = "h9i0j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.add_column("users", sa.Column("totp_last_counter", sa.Integer(), nullable=True))
    op.drop_column("enroll_tokens", "max_uses")


def downgrade() -> None:
    op.add_column(
        "enroll_tokens",
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_column("users", "totp_last_counter")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
