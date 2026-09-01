"""Notification service — in-app + Telegram + future channels.

API:
  - create_notification(db, *, recipient_ids, source, category, severity, title, body, link, ...):
      Tạo row + push Redis pub/sub → WebSocket gateway forward tới admin browser.
      Trả list[Notification].

  - notify_investigation_completed / notify_investigation_failed:
      Helper tự resolve recipients (admin yêu cầu + tất cả SuperAdmin).

  - send_telegram (background): gửi qua Telegram bot nếu user đã link.

Bot token lấy từ `services.telegram_runtime.get_bot_config` (DB → env),
không đọc thẳng `settings.telegram_bot_token`.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    ApiKey,
    Notification,
    NotificationDelivery,
    User,
)
from app.services.realtime import _redis
from app.services.telegram_runtime import get_bot_config

logger = logging.getLogger("notifications")

# Redis channel pattern: notification:user:{user_id}
def _channel(user_id: str | uuid.UUID) -> str:
    return f"notification:user:{user_id}"


# ── Recipients resolution ────────────────────────────────────────

# Tập role "admin" — dùng cho virtual role "admin" trong resolve_recipients
# (gồm cả alias legacy admin_global / admin_org).
ADMIN_ROLES = ("super_admin", "admin_global", "org_admin", "admin_org")


async def resolve_recipients(
    db: AsyncSession,
    *,
    recipient_ids: list[uuid.UUID] | None = None,
    role: str | None = None,
    org_id: uuid.UUID | None = None,
    broadcast: bool = False,
    exclude_user_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Resolve danh sách user_id sẽ nhận notification.

    Args:
        recipient_ids: chỉ định cụ thể (ưu tiên cao nhất)
        role: lọc theo role — giá trị đặc biệt "admin"/"admins" = mọi vai trò
              admin (super_admin + org_admin + alias legacy)
        org_id: lọc theo org
        broadcast: True → tất cả active user
        exclude_user_id: loại trừ (VD người gửi)
    """
    stmt = select(User.id).where(User.is_active == True)  # noqa: E712
    if recipient_ids is not None:
        stmt = stmt.where(User.id.in_(recipient_ids))
    if role is not None:
        if role in ("admin", "admins"):
            stmt = stmt.where(User.role.in_(ADMIN_ROLES))
        else:
            stmt = stmt.where(User.role == role)
    if org_id is not None:
        stmt = stmt.where(User.org_id == org_id)
    if broadcast:
        pass  # không filter thêm
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    rows = (await db.execute(stmt.distinct())).scalars().all()
    return list(rows)



# ── Core: create + publish ───────────────────────────────────────


async def create_notification(
    db: AsyncSession,
    *,
    recipient_ids: list[uuid.UUID],
    source: str,
    category: str,
    severity: str = "info",
    title: str = "",
    body: str | None = None,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    sender_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    data: dict | None = None,
) -> list[Notification]:
    """Tạo 1 row / recipient + push Redis pub/sub realtime.

    - Idempotency: nếu `idempotency_key` đã tồn tại → trả list rỗng (không tạo duplicate)
    - Trả list[Notification] các row vừa tạo (1 / recipient)
    """
    if not recipient_ids:
        return []

    # Check idempotency
    if idempotency_key:
        existing = (await db.execute(
            select(Notification).where(Notification.idempotency_key == idempotency_key)
        )).scalars().all()
        if existing:
            logger.debug("Notification idempotent skip: key=%s", idempotency_key)
            return []

    # Bulk insert (PostgreSQL ON CONFLICT DO NOTHING cho idempotency_key)
    now = datetime.now(UTC)
    rows: list[Notification] = []
    for rid in recipient_ids:
        n = Notification(
            recipient_id=rid,
            sender_id=sender_id,
            source=source,
            category=category,
            severity=severity,
            title=title[:255],
            body=body,
            link=link,
            entity_type=entity_type,
            entity_id=entity_id,
            api_key_id=api_key_id,
            idempotency_key=idempotency_key,
            data=data,
            created_at=now,
        )
        db.add(n)
        rows.append(n)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        # Có thể do duplicate idempotency_key (race) — query lại
        if idempotency_key:
            existing = (await db.execute(
                select(Notification).where(Notification.idempotency_key == idempotency_key)
            )).scalars().all()
            return list(existing)
        raise

    for n in rows:
        await db.refresh(n)

    # Push realtime
    await _publish_realtime(rows)

    # Trigger Telegram delivery cho mỗi user (background, non-blocking)
    for n in rows:
        await _maybe_deliver_telegram(db, n)

    return rows


async def _publish_realtime(notifications: list[Notification]) -> None:
    """Publish lên Redis pub/sub — WebSocket gateway sẽ forward tới browser."""
    if not notifications:
        return
    try:
        r = _redis()
        # Group theo recipient_id để gộp message
        by_user: dict[str, list[dict]] = {}
        for n in notifications:
            uid = str(n.recipient_id)
            by_user.setdefault(uid, []).append({
                "id": str(n.id),
                "category": n.category,
                "severity": n.severity,
                "source": n.source,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "entity_type": n.entity_type,
                "entity_id": n.entity_id,
                "created_at": n.created_at.isoformat(),
            })
        for uid, notifs in by_user.items():
            payload = json.dumps(
                {"type": "notification:new", "notifications": notifs},
                ensure_ascii=False,
            )
            await r.publish(_channel(uid), payload)
        await r.aclose()
    except Exception as e:  # noqa: BLE001
        logger.debug("Realtime push failed (Redis?): %s", e)


# ── Telegram delivery (background) ──────────────────────────────


async def _maybe_deliver_telegram(db: AsyncSession, n: Notification) -> None:
    """Nếu user link Telegram → gửi message qua bot. Best-effort, log lỗi.

    Bot token lấy qua `telegram_runtime.get_bot_config(db)` (DB do Super
    Admin cấu hình; fallback env). Không đọc trực tiếp `settings.telegram_bot_token`.
    """
    cfg = await get_bot_config(db)
    if not cfg.can_send:
        return
    user = (await db.execute(
        select(User).where(User.id == n.recipient_id)
    )).scalar_one_or_none()
    if not user or not user.telegram_chat_id:
        return

    # Track delivery
    delivery = NotificationDelivery(
        notification_id=n.id, channel="telegram", status="pending",
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)

    text = f"*{n.title}*\n"
    if n.body:
        text += f"\n{n.body[:1000]}\n"
    if n.link:
        text += f"\n🔗 {n.link}"

    try:
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json={
                "chat_id": user.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
        if r.status_code == 200:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
        else:
            delivery.status = "failed"
            delivery.error = f"HTTP {r.status_code}: {r.text[:200]}"
        await db.commit()
    except Exception as e:  # noqa: BLE001
        delivery.status = "failed"
        delivery.error = f"{type(e).__name__}: {e}"[:500]
        await db.commit()
        logger.warning("Telegram delivery failed for notif %s: %s", n.id, e)


# ── High-level helpers ───────────────────────────────────────────



# ── User-facing queries ─────────────────────────────────────────


async def list_user_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    stmt = select(Notification).where(Notification.recipient_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if category:
        stmt = stmt.where(Notification.category == category)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


async def count_unread(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Trả {total, by_severity: {...}}."""
    from sqlalchemy import func as sa_func
    rows = (await db.execute(
        select(Notification.severity, sa_func.count())
        .where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
        .group_by(Notification.severity)
    )).all()
    by_sev: dict[str, int] = {}
    total = 0
    for sev, cnt in rows:
        by_sev[sev] = cnt
        total += cnt
    return {"total": total, "by_severity": by_sev}


async def mark_read(
    db: AsyncSession, user_id: uuid.UUID, notif_id: uuid.UUID
) -> bool:
    n = (await db.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.recipient_id == user_id,
        )
    )).scalar_one_or_none()
    if not n:
        return False
    n.read_at = datetime.now(UTC)
    await db.commit()
    return True


async def mark_all_read(
    db: AsyncSession, user_id: uuid.UUID, category: str | None = None
) -> int:
    """Đánh dấu tất cả (tuỳ chọn theo category) là đã đọc. Trả số row update."""
    from sqlalchemy import update
    stmt = (
        update(Notification)
        .where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    if category:
        stmt = stmt.where(Notification.category == category)
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount or 0


async def delete_notification(
    db: AsyncSession, user_id: uuid.UUID, notif_id: uuid.UUID
) -> bool:
    n = (await db.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.recipient_id == user_id,
        )
    )).scalar_one_or_none()
    if not n:
        return False
    await db.delete(n)
    await db.commit()
    return True


async def clear_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    from sqlalchemy import delete as sa_delete
    res = await db.execute(
        sa_delete(Notification).where(
            Notification.recipient_id == user_id,
            Notification.read_at.is_not(None),
        )
    )
    await db.commit()
    return res.rowcount or 0

