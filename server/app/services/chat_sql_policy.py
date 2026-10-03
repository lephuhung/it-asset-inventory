"""Text-to-SQL policy cho Chat Assistant.

Chỉ **superAdmin** dùng được chat (cổng RBAC ở route), nên quyền đọc DB được mở
rộng: role `inventory_chat_ro` được `SELECT` **mọi bảng `public`** TRỪ denylist
(bảng bí mật + log/time-series). Chống **ghi** dữ liệu nằm ở 3 lớp độc lập:

1. Role chỉ được cấp `SELECT` (không INSERT/UPDATE/DELETE/DDL).
2. Transaction `READ ONLY` ở `_execute_readonly`.
3. Guardrail `validate_sql` chỉ cho `SELECT`/`WITH`.

Denylist cấu hình qua `CHAT_SQL_DENYLIST` (rỗng = không chặn bảng nào).
"""

from __future__ import annotations

import time

from sqlalchemy import text

from app.core.config import settings

CHAT_RO_ROLE = "inventory_chat_ro"
CHAT_RO_SCHEMA = "chat_ro_views"
CATALOG_SCHEMAS = ("public", CHAT_RO_SCHEMA)

# Bảng bí mật — KHÔNG bao giờ cho text-to-SQL đọc (hash/key/token).
SECRET_TABLES: tuple[str, ...] = (
    "users",
    "api_keys",
    "refresh_tokens",
    "enroll_tokens",
    "enroll_attempts",
    "token_reservations",
    "llm_config",
    "telegram_bot_config",
    "velociraptor_config",
)

# Log/audit/time-series — không phải dữ liệu nghiệp vụ; query không hữu ích + tốn tài nguyên.
LOG_TABLES: tuple[str, ...] = (
    "audit_log",
    "chat_conversations",
    "chat_messages",
    "chat_turns",
    "chat_tool_calls",
    "chat_audit_intents",
    "system_profile_events",
    "dfir_investigation_messages",
    "notification_deliveries",
)
LOG_PATTERNS: tuple[str, ...] = ("heartbeats%",)

DEFAULT_DENYLIST: tuple[str, ...] = SECRET_TABLES + LOG_TABLES + LOG_PATTERNS


def denylist_items() -> tuple[str, ...]:
    """Danh sách denylist hiện hành (lowercase). `heartbeats%` = prefix pattern."""
    raw = (settings.chat_sql_denylist or "").strip()
    if not raw:
        return ()
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def is_denied(table: str) -> bool:
    """True nếu tên bảng (không schema) nằm trong denylist."""
    name = table.lower()
    for item in denylist_items():
        if item.endswith("%"):
            if name.startswith(item[:-1]):
                return True
        elif name == item:
            return True
    return False


async def _resolve_denied(conn) -> list[tuple[str, str]]:
    """Các relation thực tế (schema, name) khớp denylist."""
    items = denylist_items()
    if not items:
        return []
    exact = {item for item in items if not item.endswith("%")}
    prefixes = tuple(item[:-1] for item in items if item.endswith("%"))
    rows = (
        await conn.execute(
            text(
                "SELECT n.nspname, c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = ANY(:schemas) "
                "AND c.relkind IN ('r','p','v','m','f')"
            ),
            {"schemas": list(CATALOG_SCHEMAS)},
        )
    ).all()
    denied: list[tuple[str, str]] = []
    for schema, name in rows:
        lowered = name.lower()
        if lowered in exact or (prefixes and lowered.startswith(prefixes)):
            denied.append((schema, name))
    return denied


def _pg_literal(value: str) -> str:
    """Literal an toàn cho `ALTER ROLE ... PASSWORD` (không dùng bind trong DDL)."""
    if "\\" in value:
        return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
    return "'" + value.replace("'", "''") + "'"


async def sync_chat_ro_password(conn) -> None:
    """Đồng bộ mật khẩu role chat_ro theo `CHAT_RO_PASSWORD` hiện hành.

    Migration chỉ set password lúc upgrade — nếu env đổi sau đó, app không kết nối
    được pool chat_ro (`password authentication failed`). Đồng bộ mỗi lần khởi động.
    """
    await conn.execute(
        text(
            f"ALTER ROLE {CHAT_RO_ROLE} WITH PASSWORD "
            f"{_pg_literal(settings.chat_ro_password)}"
        )
    )


async def sync_chat_ro_privileges(conn) -> int:
    """Cấp SELECT toàn bộ `public` + thu hồi ghi + thu hồi denylist. Idempotent.

    Gọi lúc khởi động (và trong test) để bảng mới do migration tạo cũng tự có
    SELECT, còn bảng nhạy cảm luôn bị thu hồi. Trả số relation bị chặn.
    """
    role = CHAT_RO_ROLE
    await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    await conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}"))
    await conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {CHAT_RO_SCHEMA} TO {role}"))
    # Phòng thủ: chắc chắn role không có quyền ghi dù tương lai có grant nhầm.
    await conn.execute(
        text(
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
            f"ON ALL TABLES IN SCHEMA public FROM {role}"
        )
    )
    denied = await _resolve_denied(conn)
    for schema, name in denied:
        await conn.execute(
            text(f'REVOKE ALL ON TABLE {schema}."{name}" FROM {role}')
        )
    return len(denied)


# ── Schema catalog cho LLM ───────────────────────────────────────────────────

_CATALOG_CACHE: tuple[float, str] | None = None


async def build_sql_catalog(db, *, force: bool = False) -> str:
    """Catalog bảng/cột được phép, dạng gọn cho LLM. Cache theo TTL."""
    global _CATALOG_CACHE
    ttl = settings.chat_sql_catalog_cache_seconds
    if not force and _CATALOG_CACHE is not None:
        cached_at, cached = _CATALOG_CACHE
        if (time.monotonic() - cached_at) < ttl:
            return cached

    rows = (
        await db.execute(
            text(
                "SELECT table_schema, table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = ANY(:schemas) "
                "ORDER BY table_schema, table_name, ordinal_position"
            ),
            {"schemas": list(CATALOG_SCHEMAS)},
        )
    ).all()

    tables: dict[tuple[str, str], list[str]] = {}
    for schema, table, column, data_type in rows:
        if is_denied(table):
            continue
        tables.setdefault((schema, table), []).append(f"{column} {data_type}")

    lines: list[str] = []
    total = 0
    omitted = 0
    for (schema, table), columns in sorted(tables.items()):
        line = f"{schema}.{table}({', '.join(columns)})"
        if total + len(line) + 1 > settings.chat_sql_schema_max_chars:
            omitted += 1
            continue
        lines.append(line)
        total += len(line) + 1
    if omitted:
        lines.append(f"... ({omitted} bảng khác bị lược bớt do giới hạn catalog)")

    catalog = "\n".join(lines)
    _CATALOG_CACHE = (time.monotonic(), catalog)
    return catalog


def reset_catalog_cache() -> None:
    """Xóa cache catalog (test/đổi cấu hình)."""
    global _CATALOG_CACHE
    _CATALOG_CACHE = None
