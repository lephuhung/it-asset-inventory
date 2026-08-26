"""Route stats — thống kê tổng quan dashboard."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, visible_org_ids
from app.db.models import EnrollToken, Machine, TokenStatus, User
from app.db.session import get_db
from app.schemas import StatsOverview

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverview)
async def overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    visible = await visible_org_ids(db, user)
    qm = select(Machine).where(Machine.org_id.in_(visible))
    qt = select(EnrollToken).where(EnrollToken.org_id.in_(visible))

    machines = (await db.execute(qm)).scalars().all()
    tokens = (await db.execute(qt)).scalars().all()

    # Lazy-expire: token pending quá hạn → đánh dấu expired (phễu + KPI đúng logic)
    now = datetime.now(UTC)
    for t in tokens:
        if t.status == TokenStatus.PENDING.value and t.expires_at.replace(tzinfo=UTC) < now:
            t.status = TokenStatus.EXPIRED.value
    await db.commit()

    total = len(machines)
    online = sum(1 for m in machines if m.status == "online")
    offline = sum(1 for m in machines if m.status == "offline")
    lost = sum(1 for m in machines if m.status == "lost")
    pending = sum(1 for t in tokens if t.status == TokenStatus.PENDING.value)
    expired = sum(1 for t in tokens if t.status == TokenStatus.EXPIRED.value)

    return StatsOverview(
        total_machines=total,
        online=online,
        offline=offline,
        lost=lost,
        pending_tokens=pending,
        expired_tokens=expired,
    )