"""Route: System Announcements (Thông báo dạng Modal khi đăng nhập & Quản trị SuperAdmin)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_super_admin
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import Organization, SystemAnnouncement, User, UserAnnouncementRead
from app.db.session import get_db
from app.schemas import (
    AnnouncementCreate,
    AnnouncementResponse,
    AnnouncementUpdate,
)

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@router.get("/pending", response_model=list[AnnouncementResponse])
async def get_pending_announcements(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lấy danh sách các thông báo Modal đang kích hoạt mà người dùng hiện tại chưa đọc/xác nhận."""
    # 1. Lấy danh sách id các thông báo user đã đọc
    read_subquery = select(UserAnnouncementRead.announcement_id).where(
        UserAnnouncementRead.user_id == user.id
    )

    # 2. Truy vấn thông báo active, chưa đọc, khớp org_id (hoặc toàn hệ thống)
    stmt = (
        select(SystemAnnouncement)
        .options(
            selectinload(SystemAnnouncement.org),
            selectinload(SystemAnnouncement.creator),
        )
        .where(
            SystemAnnouncement.is_active.is_(True),
            SystemAnnouncement.id.not_in(read_subquery),
            (SystemAnnouncement.org_id.is_(None)) | (SystemAnnouncement.org_id == user.org_id),
        )
        .order_by(SystemAnnouncement.created_at.desc())
    )

    result = await db.execute(stmt)
    announcements = result.scalars().all()

    # 3. Lọc theo target_type: ALL, ROLE, FIRST_LOGIN
    filtered: list[AnnouncementResponse] = []
    for ann in announcements:
        if ann.target_type == "ALL":
            pass
        elif ann.target_type == "ROLE":
            if ann.target_role and ann.target_role != user.role:
                continue
        elif ann.target_type == "FIRST_LOGIN":
            # Thông báo chỉ dành cho người dùng lần đầu
            pass

        filtered.append(
            AnnouncementResponse(
                id=ann.id,
                title=ann.title,
                content_md=ann.content_md,
                target_type=ann.target_type,
                target_role=ann.target_role,
                org_id=ann.org_id,
                org_name=ann.org.name if ann.org else None,
                is_active=ann.is_active,
                created_by=ann.created_by,
                creator_name=ann.creator.full_name if ann.creator else None,
                created_at=ann.created_at,
            )
        )

    return filtered


@router.post("/{announcement_id}/read", status_code=status.HTTP_200_OK)
async def mark_announcement_as_read(
    announcement_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ghi nhận người dùng đã đọc/xác nhận thông báo Modal."""
    ann = (
        await db.execute(
            select(SystemAnnouncement).where(SystemAnnouncement.id == announcement_id)
        )
    ).scalar_one_or_none()
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Thông báo không tồn tại")

    existing = (
        await db.execute(
            select(UserAnnouncementRead).where(
                UserAnnouncementRead.user_id == user.id,
                UserAnnouncementRead.announcement_id == announcement_id,
            )
        )
    ).scalar_one_or_none()

    if not existing:
        ack = UserAnnouncementRead(
            user_id=user.id,
            announcement_id=announcement_id,
            read_at=datetime.now(UTC),
        )
        db.add(ack)
        await append_audit(
            db,
            action="announcement.read",
            actor=str(user.id),
            target=str(announcement_id),
            ip=get_client_ip(request),
        )
        await db.commit()

    return {"status": "ok"}


# ── SuperAdmin Endpoints ──────────────────────────────────────────────


@router.get("/admin", response_model=list[AnnouncementResponse])
async def list_admin_announcements(
    db: AsyncSession = Depends(get_db),
    _super: User = Depends(require_super_admin()),
):
    """Danh sách tất cả thông báo Modal dành cho SuperAdmin quản lý."""
    stmt = (
        select(SystemAnnouncement)
        .options(
            selectinload(SystemAnnouncement.org),
            selectinload(SystemAnnouncement.creator),
        )
        .order_by(SystemAnnouncement.created_at.desc())
    )
    result = await db.execute(stmt)
    announcements = result.scalars().all()

    return [
        AnnouncementResponse(
            id=ann.id,
            title=ann.title,
            content_md=ann.content_md,
            target_type=ann.target_type,
            target_role=ann.target_role,
            org_id=ann.org_id,
            org_name=ann.org.name if ann.org else None,
            is_active=ann.is_active,
            created_by=ann.created_by,
            creator_name=ann.creator.full_name if ann.creator else None,
            created_at=ann.created_at,
        )
        for ann in announcements
    ]


@router.post("/admin", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    body: AnnouncementCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin()),
):
    """SuperAdmin tạo thông báo Modal mới."""
    if body.org_id:
        org = (
            await db.execute(select(Organization).where(Organization.id == body.org_id))
        ).scalar_one_or_none()
        if not org:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Đơn vị không tồn tại")

    ann = SystemAnnouncement(
        title=body.title.strip(),
        content_md=body.content_md.strip(),
        target_type=body.target_type,
        target_role=body.target_role if body.target_type == "ROLE" else None,
        org_id=body.org_id,
        is_active=body.is_active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(ann)
    await db.flush()

    await append_audit(
        db,
        action="announcement.create",
        actor=str(user.id),
        target=str(ann.id),
        ip=get_client_ip(request),
    )
    await db.commit()

    # Re-fetch with relationships
    stmt = (
        select(SystemAnnouncement)
        .options(
            selectinload(SystemAnnouncement.org),
            selectinload(SystemAnnouncement.creator),
        )
        .where(SystemAnnouncement.id == ann.id)
    )
    saved = (await db.execute(stmt)).scalar_one()

    return AnnouncementResponse(
        id=saved.id,
        title=saved.title,
        content_md=saved.content_md,
        target_type=saved.target_type,
        target_role=saved.target_role,
        org_id=saved.org_id,
        org_name=saved.org.name if saved.org else None,
        is_active=saved.is_active,
        created_by=saved.created_by,
        creator_name=saved.creator.full_name if saved.creator else None,
        created_at=saved.created_at,
    )


@router.put("/admin/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: uuid.UUID,
    body: AnnouncementUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin()),
):
    """SuperAdmin cập nhật thông báo Modal."""
    ann = (
        await db.execute(
            select(SystemAnnouncement).where(SystemAnnouncement.id == announcement_id)
        )
    ).scalar_one_or_none()
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Thông báo không tồn tại")

    if body.title is not None:
        ann.title = body.title.strip()
    if body.content_md is not None:
        ann.content_md = body.content_md.strip()
    if body.target_type is not None:
        ann.target_type = body.target_type
        if body.target_type != "ROLE":
            ann.target_role = None
    if body.target_role is not None:
        ann.target_role = body.target_role
    if body.org_id is not None:
        if body.org_id:
            org = (
                await db.execute(select(Organization).where(Organization.id == body.org_id))
            ).scalar_one_or_none()
            if not org:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Đơn vị không tồn tại")
        ann.org_id = body.org_id
    if body.is_active is not None:
        ann.is_active = body.is_active

    await append_audit(
        db,
        action="announcement.update",
        actor=str(user.id),
        target=str(ann.id),
        ip=get_client_ip(request),
    )
    await db.commit()

    stmt = (
        select(SystemAnnouncement)
        .options(
            selectinload(SystemAnnouncement.org),
            selectinload(SystemAnnouncement.creator),
        )
        .where(SystemAnnouncement.id == ann.id)
    )
    saved = (await db.execute(stmt)).scalar_one()

    return AnnouncementResponse(
        id=saved.id,
        title=saved.title,
        content_md=saved.content_md,
        target_type=saved.target_type,
        target_role=saved.target_role,
        org_id=saved.org_id,
        org_name=saved.org.name if saved.org else None,
        is_active=saved.is_active,
        created_by=saved.created_by,
        creator_name=saved.creator.full_name if saved.creator else None,
        created_at=saved.created_at,
    )


@router.delete("/admin/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin()),
):
    """SuperAdmin xóa thông báo Modal."""
    ann = (
        await db.execute(
            select(SystemAnnouncement).where(SystemAnnouncement.id == announcement_id)
        )
    ).scalar_one_or_none()
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Thông báo không tồn tại")

    await db.delete(ann)
    await append_audit(
        db,
        action="announcement.delete",
        actor=str(user.id),
        target=str(announcement_id),
        ip=get_client_ip(request),
    )
    await db.commit()
