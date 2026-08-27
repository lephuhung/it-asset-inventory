"""Route inventory — agent gửi snapshot cấu hình máy (mTLS)."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_machine_id
from app.db.models import Machine, MachineSpec
from app.db.session import get_db
from app.schemas import InventoryRequest, InventoryResponse
from app.services.inventory_normalize import derive_os_fields
from app.services.inventory_sync import upsert_current_and_software

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
logger = logging.getLogger("inventory")


def _config_hash(body: InventoryRequest) -> str:
    """SHA-256 hex của canonical JSON payload (bỏ `config_hash`, bỏ field null).

    Khớp với C# `CanonicalJson.Hash(snapshot, excludeProperty="config_hash")`:
    - C# dùng `DefaultIgnoreCondition.WhenWritingNull` → null fields bị bỏ khỏi JSON.
    - Pydantic mặc định `model_dump()` giữ null → phải `exclude_none=True`.
    - Canonical: sort_keys + separators=(",", ":") + ensure_ascii=False (khớp
      `JavaScriptEncoder.UnsafeRelaxedJsonEscaping` của System.Text.Json).
    """
    data = body.model_dump(exclude={"config_hash"}, exclude_none=True)
    canonical = json.dumps(
        data, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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

    # Chuẩn hóa OS (os_product/os_release/os_family) PHÍA SERVER — agent không cần đổi
    os_fields = derive_os_fields(body.os_name, body.os_version, body.os_build)
    product, release, family = os_fields

    spec = MachineSpec(
        machine_id=machine.id,
        os_name=body.os_name,
        os_product=product,
        os_release=release,
        os_family=family,
        os_version=body.os_version,
        os_build=body.os_build,
        os_arch=body.os_arch,
        os_installed_at=body.os_installed_at,
        activation_status=body.activation_status,
        cpu=body.cpu.model_dump() if body.cpu else None,
        ram_gb=body.ram_gb,
        disks=([d.model_dump() for d in body.disks] if body.disks else None),
        gpu=body.gpu.model_dump() if body.gpu else None,
        mainboard=body.mainboard.model_dump() if body.mainboard else None,
        bios=body.bios.model_dump() if body.bios else None,
        network=([n.model_dump() for n in body.network] if body.network else None),
        logged_user=body.logged_user,
        installed_software=(
            [s.model_dump() for s in body.installed_software] if body.installed_software else None
        ),
        security=body.security.model_dump() if body.security else None,
        public_ip=body.public_ip,
        config_hash=new_hash,
    )
    if body.is_vm is not None:
        machine.is_vm = body.is_vm
    # Cache IP public mới nhất ở bảng máy (hiển thị portal kể cả khi máy offline).
    if body.public_ip is not None:
        machine.public_ip = body.public_ip
    db.add(spec)

    # Đồng bộ bảng "hiện tại" (machine_current + machine_software) cùng transaction
    await upsert_current_and_software(
        db,
        machine.id,
        os_name=body.os_name,
        os_version=body.os_version,
        os_build=body.os_build,
        os_arch=body.os_arch,
        os_installed_at=body.os_installed_at,
        activation_status=body.activation_status,
        cpu=body.cpu.model_dump() if body.cpu else None,
        ram_gb=body.ram_gb,
        disks=([d.model_dump() for d in body.disks] if body.disks else None),
        gpu=body.gpu.model_dump() if body.gpu else None,
        mainboard=body.mainboard.model_dump() if body.mainboard else None,
        bios=body.bios.model_dump() if body.bios else None,
        network=([n.model_dump() for n in body.network] if body.network else None),
        logged_user=body.logged_user,
        is_vm=body.is_vm,
        security=body.security.model_dump() if body.security else None,
        installed_software=(
            [s.model_dump() for s in body.installed_software] if body.installed_software else None
        ),
        public_ip=body.public_ip,
        config_hash=new_hash,
    )
    await db.commit()
    return InventoryResponse(ok=True, config_changed=True)
