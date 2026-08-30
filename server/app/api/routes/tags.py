"""Route tags — quản lý tag linh hoạt (phân loại máy + mục đích).

- `GET /api/tags`       — danh sách tag (ai cũng đọc được, phục vụ lọc/hiển thị).
- `POST /api/tags`      — tạo tag mới (Super Admin). Tag phân loại (classification)
                          chỉ nên thêm qua system seed — 3 key cố định (personal/
                          official/bmnn) là nguồn thống kê; tag mới thường là purpose.

Gán tag cho máy nằm ở `machines.py` (`PUT /api/machines/{id}/tags`, bulk).
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_super_admin
from app.core.client_ip import get_client_ip
from app.core.audit import append_audit
from app.db.models import Tag, TagKind, User
from app.db.session import get_db
from app.schemas import TagCreateRequest, TagOut
from app.services.tags import list_tags

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _to_out(t: Tag) -> TagOut:
    return TagOut(
        id=t.id,
        key=t.key,
        label=t.label,
        kind=t.kind,
        color=t.color,
        sort_order=t.sort_order,
        is_system=t.is_system,
    )


def _slugify(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower().strip()).strip("_")
    return s or uuid.uuid4().hex[:8]


@router.get("", response_model=list[TagOut])
async def get_tags(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return [_to_out(t) for t in await list_tags(db)]


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: TagCreateRequest,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    # Tag classification mới KHÔNG được phép — 3 key hệ thống là bất biến
    # (nguồn thống kê). Tag mới phải là purpose.
    if body.kind == TagKind.CLASSIFICATION.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Không tạo được tag phân loại mới — chỉ có 3 loại máy hệ thống (cá nhân / công vụ / BMNN)",
        )

    key = (body.key or _slugify(body.label)).strip().lower().replace(" ", "_")
    exists = (
        await db.execute(select(Tag).where(Tag.key == key))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Tag '{key}' đã tồn tại")

    tag = Tag(
        key=key,
        label=body.label.strip(),
        kind=body.kind,
        color=body.color,
        sort_order=0,
        is_system=False,
    )
    db.add(tag)
    await append_audit(
        db,
        action="tag.create",
        actor=str(admin.id),
        target=f"{key}:{body.label.strip()}",
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(tag)
    return _to_out(tag)
