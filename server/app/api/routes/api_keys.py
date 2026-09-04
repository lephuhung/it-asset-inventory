"""API mở (tính năng #22, Phase 4) — API key theo scope cho hệ thống khác.

- `GET/POST/PATCH/DELETE /api/keys` — quản lý key (chỉ Super Admin).
- `GET /api/public/machines` — endpoint công khai xác thực bằng `X-API-Key`;
  scope `read:machines`; key có org_id → chỉ thấy org đó + cấp dưới.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin, visible_org_ids
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import ApiKey, Machine, User
from app.db.session import get_db
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ApiKeyUpdate,
    MachineListItem,
    Page,
)

router = APIRouter(prefix="/api/keys", tags=["api-keys"])
public_router = APIRouter(prefix="/api/public", tags=["api-public"])


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_key() -> str:
    return "ai_" + secrets.token_urlsafe(24).replace("-", "").replace("_", "")


def _to_out(k: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=k.id, name=k.name, scope=k.scope, org_id=k.org_id,
        enabled=k.enabled, last_used_at=k.last_used_at, created_at=k.created_at,
    )


@router.get("", response_model=Page[ApiKeyOut])
async def list_keys(
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    from sqlalchemy import func as sa_func

    base = select(ApiKey)
    total = (await db.execute(select(sa_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(base.order_by(ApiKey.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return Page[ApiKeyOut](
        items=[_to_out(k) for k in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ApiKeyCreated)
async def create_key(
    body: ApiKeyCreate,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    if body.scope not in {"read:machines"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Scope không được hỗ trợ")
    if body.org_id:
        visible = await visible_org_ids(db, admin)
        if str(body.org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo key cho tổ chức này")
    plain = _generate_key()
    key = ApiKey(
        name=body.name, key_hash=_hash_key(plain), scope=body.scope,
        org_id=body.org_id, created_by=admin.id,
    )
    db.add(key)
    await append_audit(db, action="apikey.create", actor=str(admin.id), target=str(key.id), ip=get_client_ip(request))
    await db.commit()
    return ApiKeyCreated(**_to_out(key).model_dump(), key=plain)


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def update_key(
    key_id: uuid.UUID,
    body: ApiKeyUpdate,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    key = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Key không tồn tại")
    if body.name is not None:
        key.name = body.name
    if body.scope is not None:
        if body.scope not in {"read:machines"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Scope không được hỗ trợ")
        key.scope = body.scope
    if body.enabled is not None:
        key.enabled = body.enabled
    await db.commit()
    return _to_out(key)


@router.delete("/{key_id}")
async def delete_key(
    key_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    key = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Key không tồn tại")
    await db.delete(key)
    await append_audit(db, action="apikey.delete", actor=str(admin.id), target=str(key_id), ip=get_client_ip(request))
    await db.commit()
    return {"ok": True}


# ── Public endpoints (X-API-Key) ────────────────────────────────


async def get_api_key(
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Thiếu X-API-Key")
    key = (
        await db.execute(
            select(ApiKey).where(ApiKey.key_hash == _hash_key(x_api_key))
        )
    ).scalar_one_or_none()
    if key is None or not key.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="API key không hợp lệ hoặc đã bị vô hiệu")
    key.last_used_at = datetime.now(UTC)
    await db.commit()
    return key


@public_router.get("/machines", response_model=list[MachineListItem])
async def public_machines(
    api_key: ApiKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID | None = None,
    status_filter: str | None = None,
):
    """Danh sách máy cho hệ thống ngoài — xác thực bằng X-API-Key (scope read:machines)."""
    if api_key.scope != "read:machines":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Scope không cho phép")
    # User ảo để tái dùng visible_org_ids (chỉ đọc role/org_id)
    fake_user = SimpleNamespace(
        role="super_admin" if api_key.org_id is None else "org_admin",
        org_id=api_key.org_id,
    )
    visible = await visible_org_ids(db, fake_user)
    if org_id and str(org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập tổ chức này")

    q = select(Machine).where(Machine.org_id.in_(visible))
    if org_id:
        q = q.where(Machine.org_id == org_id)
    if status_filter:
        q = q.where(Machine.status == status_filter)
    rows = (await db.execute(q.order_by(Machine.enrolled_at.desc()))).scalars().all()
    return [
        MachineListItem(
            id=m.id, hostname=m.hostname, machine_uuid=m.machine_uuid, status=m.status,
            lifecycle=m.lifecycle, is_vm=m.is_vm, last_seen_at=m.last_seen_at,
            enrolled_at=m.enrolled_at, org_id=m.org_id, assigned_user_id=m.assigned_user_id,
        )
        for m in rows
    ]