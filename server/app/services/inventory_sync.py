"""Đồng bộ bảng "hiện tại" (`machine_current` + `machine_software`) khi có snapshot mới.

Dùng chung bởi `POST /api/inventory` (agent online) và `POST /api/offline/import`
(máy cách ly) — luôn chạy CÙNG TRANSACTION với insert `machine_specs` để đảm bảo
tính nhất quán (spec lịch sử + current + software luôn khớp).

`machine_current`: upsert (1:1 với machines).
`machine_software`: replace toàn bộ app của máy (delete + insert) — tần suất thấp.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MachineCurrent, MachineSoftware
from app.services.inventory_normalize import derive_os_fields, derive_security_fields, software_rows


async def upsert_current_and_software(
    db: AsyncSession,
    machine_id: uuid.UUID,
    *,
    os_name: str | None = None,
    os_version: str | None = None,
    os_build: str | None = None,
    os_arch: str | None = None,
    os_installed_at: datetime | None = None,
    activation_status: str | None = None,
    cpu: dict | None = None,
    ram_gb: float | None = None,
    disks: list | None = None,
    gpu: dict | None = None,
    mainboard: dict | None = None,
    bios: dict | None = None,
    network: list | None = None,
    logged_user: str | None = None,
    is_vm: bool | None = None,
    security: dict | None = None,
    installed_software: list | None = None,
    public_ip: str | None = None,
    collected_at: datetime | None = None,
    config_hash: str | None = None,
) -> tuple[str | None, str | None, str]:
    """Upsert `machine_current` + replace `machine_software`. Trả (os_product, os_release, os_family)."""
    product, release, family = derive_os_fields(os_name, os_version, os_build)
    sec = derive_security_fields(security)
    ts = collected_at or datetime.now(UTC)

    current = await db.get(MachineCurrent, machine_id)
    if current is None:
        current = MachineCurrent(machine_id=machine_id)
        db.add(current)
    current.collected_at = ts
    current.config_hash = config_hash
    current.os_name = os_name
    current.os_product = product
    current.os_release = release
    current.os_family = family
    current.os_version = os_version
    current.os_build = os_build
    current.os_arch = os_arch
    current.os_installed_at = os_installed_at
    current.activation_status = activation_status
    current.cpu = cpu
    current.ram_gb = ram_gb
    current.disks = disks
    current.gpu = gpu
    current.mainboard = mainboard
    current.bios = bios
    current.network = network
    current.logged_user = logged_user
    current.is_vm = is_vm
    current.public_ip = public_ip
    current.antivirus = sec["antivirus"]
    current.antivirus_enabled = sec["antivirus_enabled"]
    current.antivirus_up_to_date = sec["antivirus_up_to_date"]
    current.windows_update_status = sec["windows_update_status"]
    current.windows_update_enabled = sec["windows_update_enabled"]
    current.bitlocker = sec["bitlocker"]
    current.firewall_enabled = sec["firewall_enabled"]
    current.uac_enabled = sec["uac_enabled"]
    current.secure_boot_enabled = sec["secure_boot_enabled"]
    current.rdp_enabled = sec["rdp_enabled"]
    current.usb_storage_blocked = sec["usb_storage_blocked"]

    # Replace toàn bộ app của máy (trong cùng transaction)
    await db.execute(sa_delete(MachineSoftware).where(MachineSoftware.machine_id == machine_id))
    for row in software_rows(installed_software):
        db.add(MachineSoftware(machine_id=machine_id, collected_at=ts, **row))

    return product, release, family
