"""Phiên làm việc với DB (async)."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.db_echo, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# ── Pool read-only inventory cho Chat Assistant (T3) ──────────────────────────
# Role `inventory_chat_ro` chỉ có USAGE trên schema `chat_ro_views` + SELECT 6 view.
# `search_path` đặt lúc tạo connection (server_settings) **và** reset lại mỗi lần
# checkout để session setting của lần dùng trước không rò sang lần sau.
# `statement_timeout` do tầng service (T9) đặt theo từng truy vấn.
CHAT_RO_SEARCH_PATH = "chat_ro_views, pg_catalog"


def _register_chat_ro_hygiene(engine_: AsyncEngine) -> None:
    """RESET ALL + đặt lại `search_path` trên mỗi lần mượn connection từ pool.

    Thực thi qua **autocommit** bằng cách gọi thẳng asyncpg `Connection.execute`
    (không qua `cursor()` của adapter). `cursor.execute` khiến adapter
    `_start_transaction()` mở transaction ẩn — `RESET ALL`/`SET` khi đó nằm trong
    transaction và bị rollback khi kết thúc dùng connection, làm hygiene mất tác dụng.
    Gọi thẳng asyncpg không mở transaction nên hai câu lệnh có hiệu lực session ngay.
    """

    @event.listens_for(engine_.sync_engine, "checkout")
    def _reset_session_state(dbapi_conn, connection_record, connection_proxy):
        raw = getattr(dbapi_conn, "_connection", None)
        if raw is None:  # DBAPI không phải asyncpg — bỏ qua an toàn
            return
        dbapi_conn.await_(raw.execute("RESET ALL"))
        dbapi_conn.await_(raw.execute(f"SET search_path TO {CHAT_RO_SEARCH_PATH}"))


def create_chat_ro_engine(url: str | None = None, **kwargs) -> AsyncEngine:
    """Tạo engine pool chat_ro (search_path + RESET ALL mỗi checkout).

    Test truyền `poolclass`/`pool_size` để kiểm tra tái sử dụng connection.
    """
    engine_ = create_async_engine(
        url or settings.effective_chat_ro_database_url(),
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": CHAT_RO_SEARCH_PATH}},
        **kwargs,
    )
    _register_chat_ro_hygiene(engine_)
    return engine_


chat_ro_engine = create_chat_ro_engine()
AsyncChatRoSessionLocal = async_sessionmaker(
    chat_ro_engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — trả 1 session theo request."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_chat_ro_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — session read-only inventory (role `inventory_chat_ro`)."""
    async with AsyncChatRoSessionLocal() as session:
        yield session
