"""Opt-out per (user, template) — muted / min_severity."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertTemplate, User, UserNotificationPref


async def get_pref(
    db: AsyncSession, user_id: uuid.UUID, template_code: str
) -> UserNotificationPref | None:
    return (await db.execute(
        select(UserNotificationPref).where(
            UserNotificationPref.user_id == user_id,
            UserNotificationPref.template_code == template_code,
        )
    )).scalar_one_or_none()


async def get_prefs_with_template(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Prefs của user + metadata template (để UI render control theo opt_out_controls)."""
    templates = (await db.execute(
        select(AlertTemplate).where(AlertTemplate.enabled.is_(True))
        .order_by(AlertTemplate.category, AlertTemplate.code)
    )).scalars().all()
    prefs = (await db.execute(
        select(UserNotificationPref).where(UserNotificationPref.user_id == user_id)
    )).scalars().all()
    by_code = {p.template_code: p for p in prefs}

    out = []
    for t in templates:
        p = by_code.get(t.code)
        out.append({
            "template_code": t.code,
            "template_name": t.name,
            "category": t.category,
            "default_severity": t.default_severity,
            "opt_out_controls": t.opt_out_controls or [],
            "muted": bool(p.muted) if p else False,
            "min_severity": p.min_severity if p else None,
        })
    return out


async def upsert_prefs(
    db: AsyncSession, user: User, items: list[dict]
) -> list[dict]:
    """Upsert prefs. Validate từng item theo template.opt_out_controls.

    - muted=true chỉ được nếu template có "template" trong opt_out_controls
    - min_severity chỉ được nếu template có "severity" trong opt_out_controls
    """
    for item in items:
        code = item.get("template_code")
        template = (await db.execute(
            select(AlertTemplate).where(AlertTemplate.code == code)
        )).scalar_one_or_none()
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Template không tồn tại: {code}")

        controls = set(template.opt_out_controls or [])
        if item.get("muted") and "template" not in controls:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Template '{code}' không cho phép mute (opt_out_controls={sorted(controls)})",
            )
        if item.get("min_severity") and "severity" not in controls:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Template '{code}' không cho phép chọn min_severity (opt_out_controls={sorted(controls)})",
            )

        row = await get_pref(db, user.id, code)
        if row is None:
            row = UserNotificationPref(
                user_id=user.id,
                template_code=code,
                muted=bool(item.get("muted", False)),
                min_severity=item.get("min_severity"),
            )
            db.add(row)
        else:
            row.muted = bool(item.get("muted", row.muted))
            row.min_severity = item.get("min_severity", row.min_severity)
        row.updated_at = datetime.now(UTC)
    await db.commit()
    return await get_prefs_with_template(db, user.id)
