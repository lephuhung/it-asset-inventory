"""User notification preferences — /api/me/notification-prefs."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.schemas import UserNotificationPrefOut, UserNotificationPrefUpdateIn
from app.services.user_notification_prefs import (
    get_prefs_with_template,
    upsert_prefs,
)

router = APIRouter(prefix="/api/me/notification-prefs", tags=["me-notification-prefs"])


class PrefsOut(BaseModel):
    items: list[UserNotificationPrefOut]


@router.get("", response_model=PrefsOut)
async def get_my_prefs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await get_prefs_with_template(db, user.id)
    return PrefsOut(items=[UserNotificationPrefOut(**r) for r in rows])


@router.patch("", response_model=PrefsOut)
async def patch_my_prefs(
    body: UserNotificationPrefUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await upsert_prefs(db, user, [p.model_dump() for p in body.prefs])
    return PrefsOut(items=[UserNotificationPrefOut(**r) for r in rows])
