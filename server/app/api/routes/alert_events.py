"""Lịch sử alert events (read-only) — giữ path cũ /api/alert-rules/events."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.db.models import AlertEvent
from app.schemas import AlertEventOut, Page

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])


@router.get("/events", response_model=Page[AlertEventOut])
async def list_events(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin()),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Lịch sử alert đã kích hoạt (mới nhất trước)."""
    base = select(AlertEvent)
    total = (await db.execute(select(sa_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(AlertEvent.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return Page[AlertEventOut](
        items=[
            AlertEventOut(
                id=e.id,
                rule_id=e.rule_id,
                template_code=e.template_code,
                machine_id=e.machine_id,
                org_id=e.org_id,
                severity=e.severity,
                title=e.title,
                body=e.body,
                recipient_user_ids=[str(x) for x in (e.recipient_user_ids or [])],
                created_at=e.created_at,
            )
            for e in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
