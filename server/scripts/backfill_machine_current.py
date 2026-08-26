"""Backfill 1 lần: `machine_specs` → `machine_current` + `machine_software`.

Chạy sau khi migration `d7e8f9a0b1c2` trên DB đã có dữ liệu cũ:

1. Pass 1 — điền `os_product`/`os_release`/`os_family` cho TOÀN BỘ `machine_specs`
   (gộp theo tổ hợp os_name/os_version/os_build để update theo batch).
2. Pass 2 — với mỗi máy lấy snapshot MỚI NHẤT (collected_at desc, hòa id desc) →
   upsert `machine_current` + replace `machine_software`.

Cách chạy (từ thư mục server/, dùng DB trong .env):
    .venv/bin/python -m scripts.backfill_machine_current
Hoặc chỉ định DB:
    DATABASE_URL="postgresql+asyncpg://user:pass@host/db" .venv/bin/python -m scripts.backfill_machine_current
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from sqlalchemy import select
from sqlalchemy import update as sa_update

from app.db.models import MachineSpec
from app.db.session import AsyncSessionLocal
from app.services.inventory_normalize import derive_os_fields
from app.services.inventory_sync import upsert_current_and_software


async def _backfill_spec_os_fields(db) -> int:
    """Pass 1: chuẩn hóa OS cho mọi dòng lịch sử (update theo batch theo tổ hợp)."""
    rows = (
        await db.execute(
            select(MachineSpec.id, MachineSpec.os_name, MachineSpec.os_version, MachineSpec.os_build)
        )
    ).all()
    combos: dict[tuple, list[int]] = {}
    for sid, os_name, os_version, os_build in rows:
        combos.setdefault((os_name, os_version, os_build), []).append(sid)

    updated = 0
    for (os_name, os_version, os_build), ids in combos.items():
        product, release, family = derive_os_fields(os_name, os_version, os_build)
        await db.execute(
            sa_update(MachineSpec)
            .where(MachineSpec.id.in_(ids))
            .values(os_product=product, os_release=release, os_family=family)
        )
        updated += len(ids)
    return updated


async def _backfill_current(db) -> int:
    """Pass 2: snapshot mới nhất/máy → machine_current + machine_software."""
    specs = (
        await db.execute(
            select(MachineSpec).order_by(
                MachineSpec.machine_id, MachineSpec.collected_at.desc(), MachineSpec.id.desc()
            )
        )
    ).scalars().all()

    seen: set = set()
    synced = 0
    for s in specs:
        if s.machine_id in seen:
            continue
        seen.add(s.machine_id)
        await upsert_current_and_software(
            db,
            s.machine_id,
            os_name=s.os_name,
            os_version=s.os_version,
            os_build=s.os_build,
            os_arch=s.os_arch,
            os_installed_at=s.os_installed_at,
            activation_status=s.activation_status,
            cpu=s.cpu,
            ram_gb=s.ram_gb,
            disks=s.disks,
            gpu=s.gpu,
            mainboard=s.mainboard,
            bios=s.bios,
            network=s.network,
            logged_user=s.logged_user,
            is_vm=None,
            security=s.security,
            installed_software=s.installed_software,
            collected_at=s.collected_at,
            config_hash=s.config_hash,
        )
        synced += 1
    return synced


async def main() -> None:
    async with AsyncSessionLocal() as db:
        normalized = await _backfill_spec_os_fields(db)
        synced = await _backfill_current(db)
        await db.commit()
        print(f"OK — normalized {normalized} spec rows, synced {synced} machines "
              f"(machine_current + machine_software)")


if __name__ == "__main__":
    asyncio.run(main())
