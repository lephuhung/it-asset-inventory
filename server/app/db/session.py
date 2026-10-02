"""Phiên làm việc với DB (async)."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.db_echo, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# ── Pool read-only inventory cho Chat Assistant (T3) ──────────────────────────
# Role `inventory_chat_ro` chỉ có USAGE trên schema `chat_ro_views` + SELECT view.
# `search_path` đặt ở mức connection (asyncpg `server_settings`) nên mọi kết nối
# trong pool đều khởi tạo với `chat_ro_views, pg_catalog`. `statement_timeout` do
# tầng service (T9) đặt theo từng truy vấn.
chat_ro_engine = create_async_engine(
    settings.effective_chat_ro_database_url(),
    pool_pre_ping=True,
    connect_args={"server_settings": {"search_path": "chat_ro_views,pg_catalog"}},
)
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
