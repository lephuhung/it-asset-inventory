"""FastAPI app entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.api.routes import (
    agent_config,
    alert_events,
    alert_rules,
    alert_templates_admin,
    announcements,
    api_keys,
    audit,
    auth,
    compliance,
    dfir_requests,
    downloads,
    drifts,
    enroll,
    heartbeat,
    install,
    inventory,
    llm_dfir,
    llm_dfir_external,
    machines,
    notifications,
    offline_import,
    orgs,
    renew,
    reports,
    self_service,
    stats,
    tags,
    telegram_bot_admin,
    tokens,
    user_notification_prefs,
    users,
    velociraptor,
    velociraptor_artifacts,
    ws,
)
from app.core.config import settings

# ── Logging ───────────────────────────────────────────────────
# Uvicorn không cấu hình handler cho logger của ứng dụng → log từ service
# (monitor, realtime...) bị "nuốt" im lặng. Gắn handler chuẩn cho root logger.
_LOGGING_CONFIGURED = False


def _configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    _LOGGING_CONFIGURED = True


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()

    # Fail-fast nếu DB chưa migrate — bắt lỗi `UndefinedColumnError` 500 từ code
    # mới truy vấn cột mới trong khi migration chưa chạy. Bỏ qua trong test env
    # (conftest tự tạo schema bằng Base.metadata.create_all, không qua alembic).
    if settings.app_env != "test":
        from app.core.migrations import assert_schema_at_head
        from app.db.session import engine as db_engine

        await assert_schema_at_head(db_engine)

    # Seed admin + danh sách tổ chức cấp tỉnh (UBND xã, Sở ban ngành) khi khởi động (dev/khởi tạo)
    if settings.app_env in ("dev", "test"):
        from app.db.seed_org_admins import seed_org_admins
        from app.db.seed_orgs import seed_all
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db, db.begin():
            # Nhiều Uvicorn workers cùng khởi động; khóa transaction này giúp
            # chỉ một worker seed dữ liệu hệ thống trên mỗi PostgreSQL database.
            await db.execute(text("SELECT pg_advisory_xact_lock(84620931)"))
            await auth.seed_admin(db, commit=False)
            await seed_all(db, commit=False)
            await seed_org_admins(db, commit=False)
            # 3 tag phân loại máy (cá nhân / công vụ / BMNN) — tự seed nếu thiếu
            from app.services.tags import ensure_system_tags

            await ensure_system_tags(db, commit=False)

            # Seed thông báo modal chào mừng lần đầu đăng nhập
            from app.db.seed_announcements import seed_first_login_announcement

            await seed_first_login_announcement(db, commit=False)

    # Background monitor: phát hiện offline + đảm bảo partition heartbeats
    from app.services.monitor import start_monitor

    monitor_task = await start_monitor()
    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="IT Asset Inventory API",
    version="0.1.0",
    description="Hệ thống quản lý tài sản máy tính — API cho agent + portal",
    lifespan=lifespan,
)

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Quá nhiều yêu cầu — vui lòng thử lại sau"})


app.include_router(auth.router)
app.include_router(enroll.router)
app.include_router(heartbeat.router)
app.include_router(inventory.router)
app.include_router(tokens.router)
app.include_router(machines.router)
app.include_router(stats.router)
app.include_router(tags.router)
app.include_router(orgs.router)
app.include_router(alert_rules.router)
app.include_router(self_service.router)
app.include_router(drifts.router)
app.include_router(offline_import.router)
app.include_router(api_keys.router)
app.include_router(api_keys.public_router)
app.include_router(audit.router)
app.include_router(compliance.router)
app.include_router(announcements.router)
app.include_router(reports.router)
from app.api.routes import agent_settings

app.include_router(agent_settings.router)
app.include_router(agent_config.router)
app.include_router(renew.router)
app.include_router(install.router)
app.include_router(downloads.router)
app.include_router(ws.router)
app.include_router(users.router)
app.include_router(velociraptor.router)
app.include_router(velociraptor_artifacts.router)
app.include_router(dfir_requests.router)
app.include_router(llm_dfir.router)
app.include_router(llm_dfir_external.router)
app.include_router(notifications.router)
app.include_router(notifications.admin_router)
app.include_router(notifications.ext_router)
app.include_router(notifications.me_router)
app.include_router(notifications.tg_router)
app.include_router(telegram_bot_admin.router)
app.include_router(alert_templates_admin.router)
app.include_router(alert_events.router)
app.include_router(user_notification_prefs.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": "asset-inventory-server"}
