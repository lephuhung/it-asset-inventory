"""Route inventory — agent gửi snapshot cấu hình máy (mTLS)."""
from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_machine_id
from app.db.models import Machine, MachineSpec
from app.db.session import get_db
from app.schemas import InventoryRequest, InventoryResponse

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _config_hash(body: InventoryRequest) -> str:
    data = body.model_dump(exclude={"config_hash"})
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@router.post("", response_model=InventoryResponse)
async def submit_inventory(
    body: InventoryRequest,
    db: AsyncSession = Depends(get_db),
    machine_cn: str = Depends(get_client_machine_id),
):
    """Lưu snapshot cấu hình. Lưu mới nếu hash thay đổi (tránh lưu trùng)."""
    try:
        machine_id = uuid.UUID(machine_cn)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="CN không hợp lệ")

    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Máy không tồn tại")

    new_hash = body.config_hash or _config_hash(body)
    latest = (
        await db.execute(
            select(MachineSpec)
            .where(MachineSpec.machine_id == machine.id)
            .order_by(MachineSpec.collected_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is not None and latest.config_hash == new_hash:
        # Cấu hình không đổi — không lưu snapshot trùng
        return InventoryResponse(ok=True, config_changed=False)

    spec = MachineSpec(
        machine_id=machine.id,
        os_name=body.os_name,
        os_version=body.os_version,
        os_build=body.os_build,
        os_arch=body.os_arch,
        cpu=body.cpu,
        ram_gb=body.ram_gb,
        disks=body.disks,
        gpu=body.gpu,
        network=([n.model_dump() for n in body.network] if body.network else None),
        logged_user=body.logged_user,
        security=body.security.model_dump() if body.security else None,
        config_hash=new_hash,
    )
    if body.is_vm is not None:
        machine.is_vm = body.is_vm
    db.add(spec)
    await db.commit()
    return InventoryResponse(ok=True, config_changed=True)
