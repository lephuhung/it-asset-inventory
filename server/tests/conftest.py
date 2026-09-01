"""Fixtures — test DB (PostgreSQL), client, seed admin & org.

Yêu cầu: PostgreSQL đang chạy (địa chỉ trong env POSTGRES_TEST_* hoặc localhost:5432).
Test DB `inventory_test` tự tạo nếu chưa có; mỗi test drop/create schema (isolated).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

# ── Alert engine fixture (dùng chung cho test_alert_engine + test_phase2) ──


@pytest.fixture
async def seeded_templates(db):
    """Seed 7 templates chuẩn từ migration (test DB không chạy alembic)."""
    from importlib import util
    from pathlib import Path
    import sys

    from app.db.models import AlertTemplate

    path = Path(__file__).parents[1] / "alembic/versions/t8u9v0w1x2y3_alert_engine.py"
    spec = util.spec_from_file_location("alert_engine_migration", path)
    mod = util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    for t in mod.SEED_TEMPLATES:
        db.add(AlertTemplate(**t))
    await db.commit()
    return db

# ── Cấu hình test ─────────────────────────────────────────────
POSTGRES_HOST = os.environ.get("POSTGRES_TEST_HOST", "127.0.0.1")
POSTGRES_PORT = os.environ.get("POSTGRES_TEST_PORT", "5432")
POSTGRES_USER = os.environ.get("POSTGRES_TEST_USER", "inventory")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_TEST_PASSWORD", "inventory")
POSTGRES_DB = os.environ.get("POSTGRES_TEST_DB", "inventory_test")

TEST_DB = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# ⚠️ Phải set url TEST TRƯỚC khi import app
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DB
os.environ["SECRET_KEY"] = "test_secret_key_1234567890abcdefghijklmn"
os.environ["DATA_ENCRYPTION_KEY"] = "abcdef0123456789abcdef0123456789"
os.environ["CA_MODE"] = "local"
# Rate-limit không nên chặn test (nhiều login trong thời gian ngắn)
os.environ["RATE_LIMIT_LOGIN"] = "100000/minute"
os.environ["RATE_LIMIT_ENROLL"] = "100000/minute"


# Đảm bảo test DB tồn tại (kết nối postgres DB mặc định để CREATE DATABASE nếu thiếu)
async def _create_test_db_if_missing() -> None:
    admin_url = (
        f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/postgres"
    )
    eng = _create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with eng.connect() as conn:
            row = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": POSTGRES_DB}
            )
            if row.first() is None:
                await conn.execute(text(f'CREATE DATABASE "{POSTGRES_DB}"'))
    finally:
        await eng.dispose()


asyncio.run(_create_test_db_if_missing())


@pytest_asyncio.fixture
async def db_engine() -> AsyncEngine:
    from app.db import models  # noqa: F401
    from app.db.base import Base

    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        # Fresh schema mỗi test
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(session_factory):
    """AsyncClient với dependency override — DB test."""
    from app.db import session as session_module
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    session_module.engine = None
    session_module.AsyncSessionLocal = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides = {}


@pytest_asyncio.fixture
async def seeded_env(client, session_factory):
    """Seed: org root + admin toàn cục. Trả (admin_email, admin_password, org_id)."""
    from sqlalchemy import select

    from app.api.routes.auth import seed_admin
    from app.core.config import settings
    from app.db.models import Organization, OrgType, User

    async with session_factory() as s:
        await seed_admin(s)
        admin = (
            await s.execute(select(User).where(User.email == settings.seed_admin_email))
        ).scalar_one_or_none()
        org = (
            await s.execute(
                select(Organization).where(Organization.type == OrgType.ROOT.value)
            )
        ).scalars().first()

        yield {
            "email": settings.seed_admin_email,
            "password": settings.seed_admin_password,
            "org_id": str(org.id),
            "admin_id": str(admin.id),
        }


@pytest.fixture
def ws_client():
    """TestClient cho test WebSocket — dùng NullPool engine riêng (tránh lỗi
    'Future attached to a different loop' do pool kết nối asyncpg từ loop của
    các test async trước đó). WebSocket route không cần DB, chỉ cần JWT + Redis."""
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from starlette.testclient import TestClient

    from app.db import session as session_module
    from app.main import app

    # Engine riêng, NullPool → mỗi kết nối tạo mới trên loop của TestClient (không tái dùng pool cũ)
    engine = create_async_engine(TEST_DB, poolclass=pool.NullPool)
    # Đảm bảo schema tồn tại (fixture này không dùng db_engine của test async)
    import asyncio

    from app.db import models as _models  # noqa: F401
    from app.db.base import Base

    async def _create_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session_module.engine = None
    session_module.AsyncSessionLocal = session_factory

    with TestClient(app) as tc:
        yield tc

    session_module.engine = None


