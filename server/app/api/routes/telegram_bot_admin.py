"""Telegram bot config (Super Admin only) — cấu hình bot dùng chung cho toàn bộ user.

Endpoints:
  GET   /api/admin/telegram-bot       Trả về cấu hình hiện tại (DB hoặc env fallback).
                                       Token + secret được mask; không lộ plaintext.

  PUT   /api/admin/telegram-bot       Cập nhật / set / xoá một phần config. Token
                                       được mã hoá AES-256-GCM trước khi lưu.

  POST  /api/admin/telegram-bot/test  Gọi `getMe` để verify token hợp lệ + bot
                                       đang live. Không log token ra response.

Cơ chế hoạt động:
- Một row singleton trong bảng `telegram_bot_config` (id=1).
- Service `telegram_runtime.get_bot_config(db)` cache 5s; DB được ưu tiên,
  fallback env. Sau khi PUT thành công, cache được invalidate.
- Toàn bộ user (không phải Super Admin) dùng chung bot này để nhận notification
  và link tài khoản (`/me/telegram/link`, `POST /api/external/telegram/callback`).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.core.config import settings
from app.core.security import encrypt_aes_gcm
from app.db.models import Organization, TelegramBotConfig, User
from app.schemas import (
    Page,
    TelegramBotConfigOut,
    TelegramBotConfigTestOut,
    TelegramBotConfigUpdateIn,
    TelegramLinkedUserOut,
)
from app.services.telegram_runtime import (
    BotConfigView,
    get_bot_config,
    invalidate_bot_cache,
)

logger = logging.getLogger("telegram_bot_admin")

router = APIRouter(
    prefix="/api/admin/telegram-bot",
    tags=["admin-telegram-bot"],
)


# ── Mask helpers ───────────────────────────────────────────────


def _mask(value: str | None, *, head: int = 4, tail: int = 4) -> str | None:
    """Che chuỗi: giữ `head` ký tự đầu + `tail` cuối, thay giữa bằng `***`.

    Token Telegram có dạng `<bot_id>:<base64>`, vd `1234567890:AAEhbp...`.
    """
    if not value:
        return None
    if len(value) <= head + tail + 3:
        return "***"
    return f"{value[:head]}***{value[-tail:]}"


def _callback_url() -> str:
    """URL callback đầy đủ dựa trên `agent_server_url` (cùng URL public dùng
    cho agent). Loại bỏ trailing slash để tránh `//api/...`.
    """
    base = (settings.agent_server_url or "").rstrip("/")
    if not base:
        # Fallback nếu agent_server_url chưa cấu hình
        return "/api/external/telegram/callback"
    return f"{base}/api/external/telegram/callback"


def _build_webhook_commands(cfg: BotConfigView) -> tuple[str | None, str | None]:
    """Sinh 2 snippet curl:
    - `set_webhook`: POST setWebhook kèm url + secret_token
    - `check_webhook`: GET getWebhookInfo để xem trạng thái
    """
    if not cfg.bot_token:
        return None, None
    set_cmd = (
        f"curl -X POST 'https://api.telegram.org/bot{cfg.bot_token}/setWebhook' "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"url\": \"{_callback_url()}\""
    )
    if cfg.webhook_secret:
        # Escape ký tự đặc biệt trong secret (defensive)
        secret_escaped = cfg.webhook_secret.replace("\\", "\\\\").replace('"', '\\"')
        set_cmd += f", \"secret_token\": \"{secret_escaped}\""
    set_cmd += "}'"
    check_cmd = (
        f"curl 'https://api.telegram.org/bot{cfg.bot_token}/getWebhookInfo'"
    )
    return set_cmd, check_cmd


def _to_out(db_row: TelegramBotConfig | None, cfg: BotConfigView) -> TelegramBotConfigOut:
    """Tổng hợp row DB + runtime view thành output.

    - Nếu `db_row is None` → đang dùng env fallback (masked = None, source="env").
    - Nếu có `db_row` → mask theo giá trị đã lưu.
    """
    set_cmd, check_cmd = _build_webhook_commands(cfg)

    if db_row is None:
        return TelegramBotConfigOut(
            configured=cfg.is_configured,
            bot_username=cfg.bot_username,
            bot_token_set=bool(cfg.bot_token),
            bot_token_masked=None,  # env fallback: không mask (tránh lộ length)
            webhook_secret_set=bool(cfg.webhook_secret),
            webhook_secret_masked=None,
            enabled=cfg.enabled,
            source=cfg.source,
            updated_at=None,
            updated_by=None,
            callback_url=_callback_url(),
            webhook_set_command=set_cmd,
            webhook_check_command=check_cmd,
        )

    # Đã lưu DB → plaintext token + secret đã giải mã trong cfg (memory).
    # Mask để hiển thị; KHÔNG trả về plaintext.
    return TelegramBotConfigOut(
        configured=cfg.is_configured,
        bot_username=db_row.bot_username,
        bot_token_set=bool(cfg.bot_token),
        bot_token_masked=_mask(cfg.bot_token),
        webhook_secret_set=bool(db_row.webhook_secret),
        webhook_secret_masked=_mask(db_row.webhook_secret),
        enabled=db_row.enabled,
        source=cfg.source,
        updated_at=db_row.updated_at,
        updated_by=str(db_row.updated_by) if db_row.updated_by else None,
        callback_url=_callback_url(),
        webhook_set_command=set_cmd,
        webhook_check_command=check_cmd,
    )


async def _get_or_create(db: AsyncSession) -> TelegramBotConfig:
    """Đảm bảo row singleton tồn tại (tạo nếu thiếu)."""
    row = (await db.execute(
        select(TelegramBotConfig).where(TelegramBotConfig.id == 1)
    )).scalar_one_or_none()
    if row is None:
        row = TelegramBotConfig(id=1, enabled=True, updated_at=datetime.now(UTC))
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


# ── Endpoints ───────────────────────────────────────────────────


@router.get("", response_model=TelegramBotConfigOut)
async def get_bot_config_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    cfg = await get_bot_config(db)
    row = (await db.execute(
        select(TelegramBotConfig).where(TelegramBotConfig.id == 1)
    )).scalar_one_or_none()
    return _to_out(row, cfg)


@router.put("", response_model=TelegramBotConfigOut)
async def update_bot_config(
    body: TelegramBotConfigUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Update một phần config. Semantics:

    - `bot_token`:
        * `None` (key không gửi)  → KHÔNG đổi
        * `""` (chuỗi rỗng)       → xoá (row.bot_token_encrypted = None)
        * chuỗi khác rỗng         → mã hoá AES-GCM rồi lưu
    - `bot_username`: tương tự — `None` = không đổi; `""` = xoá.
    - `webhook_secret`: tương tự `bot_token` (không mã hoá — chỉ dùng đối chiếu).
    - `enabled`: `None` = không đổi; bool = set.
    """
    row = await _get_or_create(db)
    changed = False

    # bot_token
    if "bot_token" in body.model_fields_set:
        v = body.bot_token
        if v is None or v == "":
            if row.bot_token_encrypted is not None:
                row.bot_token_encrypted = None
                changed = True
        else:
            row.bot_token_encrypted = encrypt_aes_gcm(v.strip())
            changed = True

    # bot_username — lưu plaintext
    if "bot_username" in body.model_fields_set:
        v = body.bot_username
        if v is None:
            pass  # không đổi
        else:
            cleaned = v.strip().lstrip("@")
            if row.bot_username != cleaned:
                row.bot_username = cleaned or None
                changed = True

    # webhook_secret — lưu plaintext (dùng compare_digest, không cần mã hoá)
    if "webhook_secret" in body.model_fields_set:
        v = body.webhook_secret
        if v is None:
            pass  # không đổi
        elif v == "":
            if row.webhook_secret is not None:
                row.webhook_secret = None
                changed = True
        else:
            if row.webhook_secret != v:
                row.webhook_secret = v
                changed = True

    # enabled
    if "enabled" in body.model_fields_set and body.enabled is not None:
        if row.enabled != body.enabled:
            row.enabled = body.enabled
            changed = True

    if changed:
        row.updated_by = admin.id
        row.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(row)
        invalidate_bot_cache()
        logger.info(
            "Super Admin %s updated telegram bot config", admin.email,
        )

    cfg = await get_bot_config(db)
    return _to_out(row, cfg)


@router.post("/test", response_model=TelegramBotConfigTestOut)
async def test_bot_token(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    """Gọi `getMe` để verify token đang dùng (DB → env fallback) hợp lệ.

    Không log token ra response. Trả về `ok=True` + bot info khi Telegram trả 200.
    """
    cfg = await get_bot_config(db)
    if not cfg.bot_token:
        return TelegramBotConfigTestOut(
            ok=False,
            error="Chưa cấu hình token bot. Hãy set trước khi test.",
        )
    try:
        url = f"https://api.telegram.org/bot{cfg.bot_token}/getMe"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
    except Exception as e:  # noqa: BLE001
        return TelegramBotConfigTestOut(
            ok=False,
            error=f"Không kết nối được Telegram API: {type(e).__name__}",
        )

    if r.status_code != 200:
        return TelegramBotConfigTestOut(
            ok=False,
            error=f"Telegram trả HTTP {r.status_code}: {r.text[:200]}",
        )

    data = r.json() or {}
    if not data.get("ok"):
        return TelegramBotConfigTestOut(
            ok=False,
            error=f"Telegram báo lỗi: {data.get('description', 'unknown')}",
        )
    result = data.get("result") or {}
    return TelegramBotConfigTestOut(
        ok=True,
        bot_id=result.get("id"),
        bot_username=result.get("username"),
        error=None,
    )


@router.get("/linked-users", response_model=Page[TelegramLinkedUserOut])
async def list_linked_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Danh sách user đã liên kết Telegram (có `telegram_chat_id` IS NOT NULL).

    Super Admin dùng để:
    - Kiểm tra ai đang nhận notification qua bot
    - Debug khi user liên kết nhầm account Telegram
    - Audit: bao nhiêu % user trong hệ thống đã enable Telegram

    Hỗ trợ filter `q` (tìm theo email / full_name / chat_id, case-insensitive).
    Pagination chuẩn `Page[T]`.
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy import or_

    base = select(User).where(User.telegram_chat_id.is_not(None))
    count_stmt = select(sa_func.count()).select_from(User).where(
        User.telegram_chat_id.is_not(None)
    )
    if q:
        like = f"%{q.strip()}%"
        cond = or_(
            User.email.ilike(like),
            User.full_name.ilike(like),
            User.telegram_chat_id.ilike(like),
        )
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = (await db.execute(count_stmt)).scalar_one() or 0
    rows = (await db.execute(
        base.order_by(User.telegram_linked_at.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )).scalars().all()

    # Resolve org name 1 lượt (tránh N+1)
    org_ids = {r.org_id for r in rows}
    org_names: dict = {}
    if org_ids:
        org_rows = (await db.execute(
            select(Organization.id, Organization.name).where(Organization.id.in_(org_ids))
        )).all()
        org_names = {oid: name for oid, name in org_rows}

    items = [
        TelegramLinkedUserOut(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            org_id=str(u.org_id),
            org_name=org_names.get(u.org_id),
            telegram_chat_id=u.telegram_chat_id,
            telegram_linked_at=u.telegram_linked_at,
            is_active=u.is_active,
        )
        for u in rows
    ]
    return Page[TelegramLinkedUserOut](
        items=items, total=total, limit=limit, offset=offset,
    )


@router.delete("/linked-users/{user_id}", status_code=204)
async def force_unlink_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Bỏ liên kết Telegram của user bất kỳ (Super Admin).

    Dùng khi user liên kết nhầm account Telegram cá nhân, hoặc account bị
    compromise. KHÔNG xoá user — chỉ clear `telegram_chat_id`.

    Ghi audit log với actor = super admin thực hiện.
    """
    import uuid as _uuid
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(422, "user_id không hợp lệ")

    target = (await db.execute(
        select(User).where(User.id == uid)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User không tồn tại")
    if not target.telegram_chat_id:
        raise HTTPException(409, "User này chưa liên kết Telegram")

    target.telegram_chat_id = None
    target.telegram_linked_at = None
    await db.commit()

    from app.core.audit import append_audit
    from app.core.client_ip import get_client_ip
    await append_audit(
        db,
        actor=admin.email,
        action="telegram.force_unlink",
        target=f"user:{target.id}",
        ip=get_client_ip(request),
    )
    logger.info(
        "Super Admin %s force-unlinked Telegram on %s", admin.email, target.email,
    )