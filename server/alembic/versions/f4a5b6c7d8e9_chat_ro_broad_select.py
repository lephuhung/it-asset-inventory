"""chat_ro: mở SELECT toàn bộ `public` (trừ denylist bí mật/log)

Text-to-SQL cho Chat Assistant: chỉ superAdmin dùng chat, nên bỏ allowlist 6 view →
role `inventory_chat_ro` được `SELECT` mọi bảng `public` (và view `chat_ro_views`),
**trừ** denylist bí mật + log/time-series. Chống ghi vẫn giữ nguyên: role chỉ được
cấp `SELECT`, transaction `READ ONLY`, guardrail chỉ cho `SELECT`/`WITH`.

Denylist snapshot tại thời điểm migration = hằng số code `DEFAULT_DENYLIST`
(deterministic). Runtime còn có `sync_chat_ro_privileges` đọc `CHAT_SQL_DENYLIST`
để tự đồng bộ khi khởi động (bảng mới + thay đổi denylist).

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-10-03 11:00:00.000000
"""
from __future__ import annotations

from sqlalchemy import text

from alembic import op
from app.services.chat_sql_policy import DEFAULT_DENYLIST

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

CHAT_RO_ROLE = "inventory_chat_ro"
CHAT_RO_SCHEMA = "chat_ro_views"


def _revoke_denied(bind) -> int:
    rows = bind.execute(
        text(
            "SELECT n.nspname, c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('public', :schema) "
            "AND c.relkind IN ('r','p','v','m','f')"
        ),
        {"schema": CHAT_RO_SCHEMA},
    ).fetchall()
    count = 0
    for schema, name in rows:
        lowered = name.lower()
        if any(
            lowered == item or (item.endswith("%") and lowered.startswith(item[:-1]))
            for item in DEFAULT_DENYLIST
        ):
            bind.execute(
                text(f'REVOKE ALL ON TABLE {schema}."{name}" FROM {CHAT_RO_ROLE}')
            )
            count += 1
    return count


def upgrade() -> None:
    op.execute(f"GRANT USAGE ON SCHEMA public TO {CHAT_RO_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {CHAT_RO_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {CHAT_RO_SCHEMA} TO {CHAT_RO_ROLE}")
    op.execute(
        f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
        f"ON ALL TABLES IN SCHEMA public FROM {CHAT_RO_ROLE}"
    )
    _revoke_denied(op.get_bind())


def downgrade() -> None:
    # Quay lại mô hình view-only: thu hồi SELECT trên mọi bảng `public`.
    op.execute(f"REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM {CHAT_RO_ROLE}")
