"""Route CRUD danh sách cán bộ phụ trách (SuperAdmin only).

Cán bộ phụ trách đại diện tổ chức bên ngoài hệ thống (Sở TT&TT, đơn vị tư vấn…)
— không gắn vào `organizations`. 1 cán bộ có thể được chỉ định cho nhiều hồ sơ
cấp độ (FK `system_profiles.officer_id`). Chỉ Super Admin CRUD.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_super_admin
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import Officer, SystemProfile, User
from app.db.session import get_db
from app.schemas import OfficerIn, OfficerOut, OfficerUpdate

router = APIRouter(prefix="/api/officers", tags=["officers"])


async def _profile_counts(db: AsyncSession, officer_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not officer_ids:
        return {}
    rows = (
        await db.execute(
            select(SystemProfile.officer_id, func.count())
            .where(SystemProfile.officer_id.in_(officer_ids))
            .group_by(SystemProfile.officer_id)
        )
    ).all()
    return {oid: c for oid, c in rows}


def _to_out(o: Officer, profile_count: int) -> OfficerOut:
    return OfficerOut(
        id=o.id,
        name=o.name,
        organization=o.organization,
        title=o.title,
        phone=o.phone,
        email=o.email,
        note=o.note,
        profile_count=profile_count,
        created_at=o.created_at,
        updated_at=o.updated_at,
    )


@router.get("", response_model=list[OfficerOut])
async def list_officers(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Danh sách cán bộ — mọi user đăng nhập đều xem được (tham khảo)."""
    conds = []
    if q:
        like = f"%{q}%"
        conds.append(
            Officer.name.ilike(like)
            | Officer.organization.ilike(like)
            | Officer.title.ilike(like)
        )
    rows = (
        (
            await db.execute(
                select(Officer).where(*conds).order_by(Officer.name)
            )
        )
        .scalars()
        .all()
    )
    counts = await _profile_counts(db, {o.id for o in rows})
    return [_to_out(o, counts.get(o.id, 0)) for o in rows]


@router.get("/{officer_id}", response_model=OfficerOut)
async def get_officer(
    officer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    o = (
        await db.execute(select(Officer).where(Officer.id == officer_id))
    ).scalar_one_or_none()
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cán bộ")
    counts = await _profile_counts(db, {o.id})
    return _to_out(o, counts.get(o.id, 0))


@router.post("", response_model=OfficerOut, status_code=status.HTTP_201_CREATED)
async def create_officer(
    body: OfficerIn,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Tên cán bộ không được để trống")
    o = Officer(
        name=name,
        organization=(body.organization or "").strip() or None,
        title=(body.title or "").strip() or None,
        phone=(body.phone or "").strip() or None,
        email=(str(body.email) if body.email else "").strip() or None,
        note=(body.note or "").strip() or None,
        created_by=admin.id,
    )
    db.add(o)
    await append_audit(
        db, action="officer.create", actor=str(admin.id), target=f"{o.id}:{o.name}",
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(o)
    return _to_out(o, 0)


@router.patch("/{officer_id}", response_model=OfficerOut)
async def update_officer(
    officer_id: uuid.UUID,
    body: OfficerUpdate,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    o = (
        await db.execute(select(Officer).where(Officer.id == officer_id))
    ).scalar_one_or_none()
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cán bộ")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Tên cán bộ không được để trống")
        data["name"] = new_name
    for f in ("organization", "title", "phone", "note"):
        if f in data and data[f] is not None:
            data[f] = (data[f] or "").strip() or None
    if "email" in data and data["email"] is not None:
        data["email"] = str(data["email"]).strip() or None
    for field, value in data.items():
        setattr(o, field, value)
    await append_audit(
        db, action="officer.update", actor=str(admin.id), target=str(o.id),
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(o)
    counts = await _profile_counts(db, {o.id})
    return _to_out(o, counts.get(o.id, 0))


@router.delete("/{officer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_officer(
    officer_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    o = (
        await db.execute(select(Officer).where(Officer.id == officer_id))
    ).scalar_one_or_none()
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cán bộ")
    # FK on_delete=SET NULL nên các hồ sơ đang trỏ tới sẽ tự set officer_id=NULL.
    await append_audit(
        db, action="officer.delete", actor=str(admin.id), target=f"{o.id}:{o.name}",
        ip=get_client_ip(request),
    )
    await db.delete(o)
    await db.commit()
