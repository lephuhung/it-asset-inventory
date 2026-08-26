"""Route báo cáo — xuất Excel (mục 5.4: POST /api/reports/export, Sprint 4).

Phạm vi dữ liệu theo RBAC: admin cơ quan chỉ thấy máy trong org của mình;
admin toàn cục xem tất cả. Số điện thoại mask mặc định.
"""
from __future__ import annotations

import asyncio
import io
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, visible_org_ids
from app.core.audit import append_audit
from app.db.models import EnrollToken, Machine, User
from app.db.session import get_db
from app.services.report import build_machines_pdf, build_machines_workbook

router = APIRouter(prefix="/api/reports", tags=["reports"])

_STATUS_FILTERS = {"online", "offline", "lost", "decommissioned", "pending"}


async def _load_machines(
    db: AsyncSession,
    user: User,
    org_id: uuid.UUID | None,
    status_filter: str | None,
    q: str | None,
) -> tuple[list[Any], dict[uuid.UUID, dict]]:
    """Query máy theo phạm vi quyền + metadata token enroll. Dùng chung Excel/PDF."""
    visible = await visible_org_ids(db, user)
    if org_id and str(org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xuất báo cáo tổ chức này")

    query = (
        select(Machine)
        .options(
            selectinload(Machine.org),
            selectinload(Machine.assigned_user),
            selectinload(Machine.specs),
        )
        .where(Machine.org_id.in_(visible))
        .order_by(Machine.enrolled_at.desc())
    )
    if org_id:
        query = query.where(Machine.org_id == org_id)
    if status_filter:
        query = query.where(Machine.status == status_filter)
    if q:
        like = f"%{q}%"
        query = query.where(Machine.hostname.ilike(like) | Machine.machine_uuid.ilike(like))

    machines = list((await db.execute(query)).scalars().all())

    token_meta: dict[uuid.UUID, dict] = {}
    if machines:
        mids = [m.id for m in machines]
        tokens = (
            (
                await db.execute(
                    select(EnrollToken).where(EnrollToken.used_by.in_(mids))
                )
            )
            .scalars()
            .all()
        )
        for t in tokens:
            if t.used_by:
                token_meta[t.used_by] = {
                    "full_name": t.full_name,
                    "email": t.email,
                    "department": t.department,
                    "position": t.position,
                }
    return machines, token_meta


def _show_full(user: User, include_phone_full: bool) -> bool:
    from app.api.deps import ADMIN_ROLES

    return include_phone_full and user.role in ADMIN_ROLES


@router.post("/export")
async def export_machines(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    include_phone_full: bool = False,
):
    """Xuất Excel danh sách máy. Query params: org_id, status, q (hostname/uuid), include_phone_full."""
    if status_filter and status_filter not in _STATUS_FILTERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Trạng thái không hợp lệ")

    machines, token_meta = await _load_machines(db, user, org_id, status_filter, q)

    content = await build_machines_workbook(
        list(machines),
        token_meta=token_meta,
        show_full_phone=_show_full(user, include_phone_full),
        generated_by=str(user.id),
    )

    await append_audit(
        db,
        action="report.export",
        actor=str(user.id),
        target=f"machines:{len(machines)}",
    )
    await db.commit()

    filename = f"danh-sach-may-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/export-pdf")
async def export_machines_pdf(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    include_phone_full: bool = False,
):
    """Báo cáo PDF theo biểu mẫu hành chính (WeasyPrint — Phase 4)."""
    if status_filter and status_filter not in _STATUS_FILTERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Trạng thái không hợp lệ")

    machines, token_meta = await _load_machines(db, user, org_id, status_filter, q)

    content = await asyncio.to_thread(
        build_machines_pdf,
        list(machines),
        token_meta=token_meta,
        show_full_phone=_show_full(user, include_phone_full),
        generated_by=str(user.id),
    )

    await append_audit(
        db,
        action="report.export_pdf",
        actor=str(user.id),
        target=f"machines:{len(machines)}",
    )
    await db.commit()

    filename = f"danh-sach-may-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.pdf"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )