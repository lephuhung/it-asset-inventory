"""Route catalog loại thiết bị — quản trị động bởi Super Admin.

- `GET /api/device-types`          — danh sách (mọi user đã đăng nhập; filter `active_only`).
- `POST /api/device-types`         — thêm loại mới (Super Admin).
- `PATCH /api/device-types/{id}`   — sửa nhãn/icon/thứ tự/bật-tắt (Super Admin).
- `DELETE /api/device-types/{id}`  — xóa (Super Admin; chặn nếu đã có thiết bị dùng).

`system_devices.device_type` lưu `DeviceType.code`; loại `is_active=false`
không hiện trong dropdown chọn khi nhập thiết bị mới nhưng vẫn giữ ở dữ liệu cũ.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_super_admin
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import DeviceType, SystemDevice, User
from app.db.session import get_db
from app.schemas import DeviceTypeIn, DeviceTypeOut, DeviceTypeUpdate

router = APIRouter(prefix="/api/device-types", tags=["device-types"])


def _to_out(t: DeviceType) -> DeviceTypeOut:
    return DeviceTypeOut(
        id=t.id, code=t.code, label=t.label, icon=t.icon,
        sort_order=t.sort_order, is_active=t.is_active,
    )


@router.get("", response_model=list[DeviceTypeOut])
async def list_device_types(
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(DeviceType).order_by(DeviceType.sort_order, DeviceType.code)
    if active_only:
        q = q.where(DeviceType.is_active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    return [_to_out(t) for t in rows]


@router.post("", response_model=DeviceTypeOut, status_code=status.HTTP_201_CREATED)
async def create_device_type(
    body: DeviceTypeIn,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    code = body.code.strip().lower().replace(" ", "_")
    exists = (await db.execute(select(DeviceType).where(DeviceType.code == code))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Loại thiết bị '{code}' đã tồn tại")
    t = DeviceType(
        code=code, label=body.label.strip(), icon=body.icon,
        sort_order=body.sort_order, is_active=body.is_active,
    )
    db.add(t)
    await append_audit(db, action="device_type.create", actor=str(admin.id), target=code, ip=get_client_ip(request))
    await db.commit()
    await db.refresh(t)
    return _to_out(t)


@router.patch("/{type_id}", response_model=DeviceTypeOut)
async def update_device_type(
    type_id: uuid.UUID,
    body: DeviceTypeUpdate,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    t = (await db.execute(select(DeviceType).where(DeviceType.id == type_id))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy loại thiết bị")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(t, field, value)
    await append_audit(db, action="device_type.update", actor=str(admin.id), target=str(type_id), ip=get_client_ip(request))
    await db.commit()
    await db.refresh(t)
    return _to_out(t)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_type(
    type_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    t = (await db.execute(select(DeviceType).where(DeviceType.id == type_id))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy loại thiết bị")
    used = (
        await db.execute(select(func.count()).select_from(SystemDevice).where(SystemDevice.device_type == t.code))
    ).scalar_one()
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Loại thiết bị đang được dùng trong hồ sơ — hãy tắt bật (is_active=false) thay vì xóa",
        )
    await append_audit(db, action="device_type.delete", actor=str(admin.id), target=str(type_id), ip=get_client_ip(request))
    await db.delete(t)
    await db.commit()
