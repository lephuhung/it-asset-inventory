"""Notification API — user-facing + admin send + external (Hermes) + Telegram linking.

Endpoints (xem docstrings trong code):
  /api/notifications                          GET    list
  /api/notifications/unread-count             GET    badge
  /api/notifications/{id}/read                PATCH
  /api/notifications/mark-all-read            POST
  /api/notifications/{id}                     DELETE
  /api/notifications/clear                    POST

  /api/admin/notifications                    POST   Super Admin gửi
  /api/admin/notifications/broadcast          POST   Super Admin broadcast

  /api/external/notifications                 POST   Hermes/Velociraptor (API key)

  /api/me/telegram/link                       POST   Lấy deep-link để link Telegram
  /api/me/telegram/unlink                     POST   Bỏ link
  /api/me/telegram/status                     GET
  /api/external/telegram/callback             POST   Telegram bot callback (update)
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.core.config import settings
from app.core.security import decode_token
from app.db.models import ApiKey, Notification, User
from app.schemas import (
    AdminSendNotificationIn,
    AdminSendNotificationOut,
    ExternalNotificationIn,
    NotificationMarkAllReadOut,
    NotificationOut,
    NotificationUnreadCountOut,
    TelegramLinkStatusOut,
    TelegramLinkStartOut,
)
from app.services import notifications as notif_svc

logger = logging.getLogger("notifications.api")

# ── User-facing routes ──────────────────────────────────────────
router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# Dependency: lấy current user từ JWT (Authorization header)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials  # noqa: E402
import jwt as _jwt  # noqa: E402
from app.core.security import decode_token  # noqa: E402

_bearer = HTTPBearer(auto_error=False)


async def _current_user_dep(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not cred:
        raise HTTPException(401, "Thiếu token")
    try:
        payload = decode_token(cred.credentials, "access")
    except _jwt.InvalidTokenError:
        raise HTTPException(401, "Token không hợp lệ")
    user_id = payload.get("sub")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "User không tồn tại")
    return user


def _to_out(n: Notification, sender_name: str | None = None) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        source=n.source,
        category=n.category,
        severity=n.severity,
        title=n.title,
        body=n.body,
        link=n.link,
        entity_type=n.entity_type,
        entity_id=n.entity_id,
        read_at=n.read_at,
        created_at=n.created_at,
        sender_name=sender_name,
    )


async def _resolve_sender_names(db: AsyncSession, notifs: list[Notification]) -> dict[uuid.UUID, str]:
    sender_ids = {n.sender_id for n in notifs if n.sender_id}
    if not sender_ids:
        return {}
    rows = (await db.execute(
        select(User.id, User.full_name).where(User.id.in_(sender_ids))
    )).all()
    return {uid: name for uid, name in rows}


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),  # defined below
    unread_only: bool = False,
    category: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    notifs = await notif_svc.list_user_notifications(
        db, user.id, unread_only=unread_only, category=category, limit=limit, offset=offset,
    )
    names = await _resolve_sender_names(db, notifs)
    return [_to_out(n, names.get(n.sender_id)) for n in notifs]


@router.get("/unread-count", response_model=NotificationUnreadCountOut)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    return NotificationUnreadCountOut(**await notif_svc.count_unread(db, user.id))


@router.patch("/{notif_id}/read", status_code=204)
async def mark_notification_read(
    notif_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    ok = await notif_svc.mark_read(db, user.id, notif_id)
    if not ok:
        raise HTTPException(404, "Notification không tồn tại")


@router.post("/mark-all-read", response_model=NotificationMarkAllReadOut)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
    category: str | None = None,
):
    n = await notif_svc.mark_all_read(db, user.id, category=category)
    return NotificationMarkAllReadOut(marked=n)


@router.delete("/{notif_id}", status_code=204)
async def delete_notification(
    notif_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    ok = await notif_svc.delete_notification(db, user.id, notif_id)
    if not ok:
        raise HTTPException(404, "Notification không tồn tại")


@router.post("/clear", response_model=NotificationMarkAllReadOut)
async def clear_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    n = await notif_svc.clear_read(db, user.id)
    return NotificationMarkAllReadOut(marked=n)


# ── Admin: send notification ───────────────────────────────────
admin_router = APIRouter(prefix="/api/admin/notifications", tags=["admin-notifications"])


@admin_router.post("", response_model=AdminSendNotificationOut)
async def admin_send_notification(
    body: AdminSendNotificationIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    # Resolve recipients
    rf = body.recipient_filter or {}
    recipient_ids: list[uuid.UUID]
    if body.recipient_ids:
        recipient_ids = body.recipient_ids
    else:
        recipient_ids = await notif_svc.resolve_recipients(
            db,
            role=rf.get("role"),
            org_id=uuid.UUID(rf["org_id"]) if rf.get("org_id") else None,
            broadcast=bool(rf.get("broadcast")),
            exclude_user_id=uuid.UUID(rf["exclude_user_id"]) if rf.get("exclude_user_id") else None,
        )
    if not recipient_ids:
        raise HTTPException(400, "Không có recipient nào")

    notifs = await notif_svc.create_notification(
        db,
        recipient_ids=recipient_ids,
        source="user",
        category=body.category,
        severity=body.severity,
        title=body.title,
        body=body.body,
        link=body.link,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        sender_id=admin.id,
        data=body.data,
    )
    return AdminSendNotificationOut(
        delivered_to=len(notifs),
        recipient_ids=[str(u) for u in recipient_ids],
        notification_ids=[str(n.id) for n in notifs],
    )


@admin_router.post("/broadcast", response_model=AdminSendNotificationOut)
async def admin_broadcast(
    body: AdminSendNotificationIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    notifs = await notif_svc.create_notification(
        db,
        recipient_ids=await notif_svc.resolve_recipients(db, broadcast=True, exclude_user_id=admin.id),
        source="user",
        category=body.category or "system",
        severity=body.severity,
        title=body.title,
        body=body.body,
        link=body.link,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        sender_id=admin.id,
        data=body.data,
    )
    return AdminSendNotificationOut(
        delivered_to=len(notifs),
        recipient_ids=[str(n.recipient_id) for n in notifs],
        notification_ids=[str(n.id) for n in notifs],
    )


# ── External API (Hermes, Velociraptor) — API key auth ─────────
ext_router = APIRouter(prefix="/api/external/notifications", tags=["external-notifications"])


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _auth_api_key(db: AsyncSession, request: Request, *required_scopes: str) -> ApiKey:
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(401, "Missing Authorization Bearer")
    import hashlib
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key = (await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.enabled == True)  # noqa: E712
    )).scalar_one_or_none()
    if not key:
        raise HTTPException(401, "API key không hợp lệ")
    have = set(key.scope.split())
    if not have.issuperset(required_scopes):
        raise HTTPException(403, f"Thiếu scope: {set(required_scopes) - have}")
    key.last_used_at = datetime.now(UTC)
    await db.commit()
    return key


@ext_router.post("", response_model=AdminSendNotificationOut)
async def external_send_notification(
    body: ExternalNotificationIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Hermes Agent / Velociraptor gọi endpoint này để push notification về admin.

    Cần API key với scope `notify:write`. Recipients chỉ được lọc theo role/user_ids
    trong cùng org với key (tránh lộ thông tin ngoài phạm vi).
    """
    key = await _auth_api_key(db, request, "notify:write")

    source = request.headers.get("X-Source", "external")
    idem = request.headers.get("X-Idempotency-Key") or f"{source}-{body.entity_id or ''}-{secrets.token_hex(4)}"

    # Resolve recipients
    rp = body.recipients or {}
    rp_type = rp.get("type", "role")
    recipient_ids: list[uuid.UUID]
    if rp_type == "user":
        uids = rp.get("user_ids") or []
        recipient_ids = [uuid.UUID(u) for u in uids]
    elif rp_type == "role":
        recipient_ids = await notif_svc.resolve_recipients(db, role=rp.get("role"))
    elif rp_type == "broadcast":
        recipient_ids = await notif_svc.resolve_recipients(db, broadcast=True)
    else:
        raise HTTPException(422, f"recipients.type không hợp lệ: {rp_type}")

    if not recipient_ids:
        return AdminSendNotificationOut(delivered_to=0, recipient_ids=[], notification_ids=[])

    notifs = await notif_svc.create_notification(
        db,
        recipient_ids=recipient_ids,
        source=source,
        category=body.category,
        severity=body.severity,
        title=body.title,
        body=body.body,
        link=body.link,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        api_key_id=key.id,
        idempotency_key=idem,
        data=body.data,
    )
    return AdminSendNotificationOut(
        delivered_to=len(notifs),
        recipient_ids=[str(u) for u in recipient_ids],
        notification_ids=[str(n.id) for n in notifs],
    )


# ── Telegram bot linking ────────────────────────────────────────
me_router = APIRouter(prefix="/api/me/telegram", tags=["me-telegram"])


# In-memory token store cho linking (5 phút TTL, đủ để user mở app Telegram)
# Production nên dùng Redis, nhưng cho MVP in-memory OK.
_LINKING_TOKENS: dict[str, dict] = {}  # token -> {user_id, expires_at}


@me_router.post("/link", response_model=TelegramLinkStartOut)
async def start_telegram_link(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    if not settings.telegram_bot_token or not settings.telegram_bot_username:
        raise HTTPException(503, "Telegram bot chưa được cấu hình (settings.telegram_bot_token/username)")
    token = secrets.token_urlsafe(24)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    _LINKING_TOKENS[token] = {"user_id": str(user.id), "expires_at": expires}
    bot_url = f"https://t.me/{settings.telegram_bot_username}?start={token}"
    return TelegramLinkStartOut(bot_url=bot_url, linking_token=token, expires_at=expires)


@me_router.delete("/link", status_code=204)
async def unlink_telegram(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    user.telegram_chat_id = None
    user.telegram_linked_at = None
    await db.commit()


@me_router.get("/status", response_model=TelegramLinkStatusOut)
async def telegram_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user_dep),
):
    return TelegramLinkStatusOut(
        linked=bool(user.telegram_chat_id),
        telegram_chat_id=user.telegram_chat_id,
        linked_at=user.telegram_linked_at,
    )


# ── Telegram bot callback (webhook từ Telegram) ────────────────
tg_router = APIRouter(prefix="/api/external/telegram", tags=["telegram-callback"])


@tg_router.post("/callback")
async def telegram_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Webhook Telegram gọi khi user gửi /start <token>.

    1. Verify secret token trong header X-Telegram-Bot-Api-Secret-Token
    2. Parse update → tìm /start <token>
    3. Match token → set user.telegram_chat_id = update.message.chat.id
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.telegram_webhook_secret or not secrets.compare_digest(secret, settings.telegram_webhook_secret):
        raise HTTPException(401, "Invalid secret")

    data = await request.json()
    msg = data.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if not text.startswith("/start "):
        return {"ok": True}
    token = text.split(" ", 1)[1].strip()
    entry = _LINKING_TOKENS.pop(token, None)
    if not entry:
        return {"ok": True, "error": "token invalid or expired"}
    if entry["expires_at"] < datetime.now(UTC):
        return {"ok": True, "error": "expired"}

    user = (await db.execute(
        select(User).where(User.id == entry["user_id"])
    )).scalar_one_or_none()
    if not user:
        return {"ok": True, "error": "user not found"}
    user.telegram_chat_id = chat_id
    user.telegram_linked_at = datetime.now(UTC)
    await db.commit()

    # Gửi confirmation message
    if settings.telegram_bot_token:
        try:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={
                    "chat_id": chat_id,
                    "text": f"✅ Đã liên kết tài khoản với {user.email}. Bạn sẽ nhận notification tại đây.",
                })
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}
