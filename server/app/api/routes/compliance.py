"""Route compliance — thông báo tuân thủ pháp lý (mục 7.4).

Portal hiển thị bản hiện hành; bắt buộc xác nhận trước khi tiếp tục dùng.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.audit import append_audit
from app.db.models import ComplianceNotice, NoticeStatus, User, UserAcknowledgment
from app.db.session import get_db
from app.schemas import AcknowledgeRequest, ComplianceNoticeResponse

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.get("/current", response_model=ComplianceNoticeResponse | None)
async def get_current_notice(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bản thông báo tuân thủ đang hiệu lực."""
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(ComplianceNotice)
            .where(
                ComplianceNotice.status == NoticeStatus.ACTIVE.value,
                ComplianceNotice.effective_from <= now,
            )
            .order_by(ComplianceNotice.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return ComplianceNoticeResponse(
        id=row.id, version=row.version, title=row.title, content_md=row.content_md,
        effective_from=row.effective_from,
    )


@router.get("/pending", response_model=bool)
async def has_pending_ack(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Người dùng có bản tuân thủ chưa xác nhận không (bản đang hiệu lực)?"""
    now = datetime.now(UTC)
    notice = (
        await db.execute(
            select(ComplianceNotice)
            .where(
                ComplianceNotice.status == NoticeStatus.ACTIVE.value,
                ComplianceNotice.effective_from <= now,
            )
            .order_by(ComplianceNotice.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if notice is None:
        return False
    ack = (
        await db.execute(
            select(UserAcknowledgment).where(
                UserAcknowledgment.user_id == user.id, UserAcknowledgment.notice_id == notice.id
            )
        )
    ).scalar_one_or_none()
    return ack is None


@router.post("/acknowledge")
async def acknowledge(
    body: AcknowledgeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ghi nhận người dùng đã đọc thông báo tuân thủ."""
    notice = (
        await db.execute(select(ComplianceNotice).where(ComplianceNotice.id == body.notice_id))
    ).scalar_one_or_none()
    if notice is None or notice.status != NoticeStatus.ACTIVE.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Thông báo không tồn tại")

    existing = (
        await db.execute(
            select(UserAcknowledgment).where(
                UserAcknowledgment.user_id == user.id, UserAcknowledgment.notice_id == notice.id
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"ok": True, "already": True}

    db.add(
        UserAcknowledgment(
            user_id=user.id,
            notice_id=notice.id,
            ip=request.client.host if request.client else None,
            source="portal",
        )
    )
    await append_audit(
        db, action="compliance.acknowledge", actor=str(user.id),
        target=str(notice.id), ip=request.client.host if request.client else None,
    )
    await db.commit()
    return {"ok": True, "already": False}
