"""Route danh bạ chuyên trách CNTT / tổ chức vận hành.

- `GET /api/it-contacts`          — danh sách (scope theo org của user; filter org_id/kind/q).
- `POST /api/it-contacts`         — thêm (Admin: đơn vị mình; Super Admin: mọi đơn vị).
- `PATCH /api/it-contacts/{id}`   — sửa (đổi org_id/kind không cho phép).
- `DELETE /api/it-contacts/{id}`  — xóa (các liên kết hồ sơ bị gỡ theo CASCADE).

`kind=person` — cá nhân chuyên trách CNTT; `kind=org` — tổ chức được giao
vận hành (đầu mối liên hệ trong `contact_person`). Gắn vào hồ sơ cấp độ qua
`POST/DELETE /api/system-profiles/{id}/contacts/{contact_id}` (xem
system_profiles.py).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_super_admin, require_admin, visible_org_ids
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import ItContact, Organization, SystemProfileContact, User
from app.db.session import get_db
from app.schemas import ItContactIn, ItContactOut, ItContactUpdate

router = APIRouter(prefix="/api/it-contacts", tags=["it-contacts"])


async def _org_names(db: AsyncSession, org_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not org_ids:
        return {}
    rows = (await db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(org_ids)))).all()
    return {oid: name for oid, name in rows}


async def _profile_counts(db: AsyncSession, contact_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not contact_ids:
        return {}
    rows = (
        await db.execute(
            select(SystemProfileContact.contact_id, func.count())
            .where(SystemProfileContact.contact_id.in_(contact_ids))
            .group_by(SystemProfileContact.contact_id)
        )
    ).all()
    return {cid: c for cid, c in rows}


def _to_out(c: ItContact, org_name: str | None, profile_count: int) -> ItContactOut:
    return ItContactOut(
        id=c.id, org_id=c.org_id, org_name=org_name, kind=c.kind, name=c.name,
        position=c.position, contact_person=c.contact_person, phone=c.phone,
        email=c.email, address=c.address, note=c.note,
        profile_count=profile_count, created_at=c.created_at, updated_at=c.updated_at,
    )


@router.get("", response_model=list[ItContactOut])
async def list_contacts(
    org_id: uuid.UUID | None = None,
    kind: str | None = Query(default=None, pattern="^(person|org)$"),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conds = []
    if is_super_admin(user):
        if org_id is not None:
            conds.append(ItContact.org_id == org_id)
    else:
        visible = await visible_org_ids(db, user)
        if org_id is not None:
            if str(org_id) not in visible:
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Đơn vị ngoài phạm vi của bạn")
            conds.append(ItContact.org_id == org_id)
        else:
            conds.append(ItContact.org_id.in_(visible))
    if kind:
        conds.append(ItContact.kind == kind)
    if q:
        like = f"%{q}%"
        conds.append(ItContact.name.ilike(like) | ItContact.contact_person.ilike(like))

    rows = (await db.execute(select(ItContact).where(*conds).order_by(ItContact.kind, ItContact.name))).scalars().all()
    org_names = await _org_names(db, {c.org_id for c in rows})
    counts = await _profile_counts(db, {c.id for c in rows})
    return [_to_out(c, org_names.get(c.org_id), counts.get(c.id, 0)) for c in rows]


@router.post("", response_model=ItContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ItContactIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    if not is_super_admin(admin) and str(admin.org_id) != str(body.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ thêm danh bạ cho đơn vị của bạn")
    contact = ItContact(
        org_id=body.org_id, kind=body.kind, name=body.name.strip(),
        position=body.position, contact_person=body.contact_person,
        phone=body.phone, email=body.email, address=body.address, note=body.note,
        created_by=admin.id,
    )
    db.add(contact)
    await append_audit(db, action="it_contact.create", actor=str(admin.id), target=f"{body.org_id}:{contact.name}", ip=get_client_ip(request))
    await db.commit()
    await db.refresh(contact)
    org_names = await _org_names(db, {contact.org_id})
    return _to_out(contact, org_names.get(contact.org_id), 0)


@router.patch("/{contact_id}", response_model=ItContactOut)
async def update_contact(
    contact_id: uuid.UUID,
    body: ItContactUpdate,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    contact = (await db.execute(select(ItContact).where(ItContact.id == contact_id))).scalar_one_or_none()
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy contact")
    if not is_super_admin(admin) and str(admin.org_id) != str(contact.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Contact ngoài phạm vi của bạn")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    await append_audit(db, action="it_contact.update", actor=str(admin.id), target=str(contact_id), ip=get_client_ip(request))
    await db.commit()
    await db.refresh(contact)
    org_names = await _org_names(db, {contact.org_id})
    counts = await _profile_counts(db, {contact.id})
    return _to_out(contact, org_names.get(contact.org_id), counts.get(contact.id, 0))


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    contact = (await db.execute(select(ItContact).where(ItContact.id == contact_id))).scalar_one_or_none()
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy contact")
    if not is_super_admin(admin) and str(admin.org_id) != str(contact.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Contact ngoài phạm vi của bạn")
    await append_audit(db, action="it_contact.delete", actor=str(admin.id), target=f"{contact.org_id}:{contact.name}", ip=get_client_ip(request))
    await db.delete(contact)
    await db.commit()
