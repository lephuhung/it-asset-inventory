"""Tests: seed danh sách tổ chức cấp tỉnh (UBND cấp xã + Sở ban ngành)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Organization, OrgType
from app.db.seed_orgs import (
    SO_BAN_NGANH_NAMES,
    UBND_XA_NAMES,
    seed_all,
    seed_so_ban_nganh,
    seed_ubnd_xa,
)


async def _names_by_type(db, org_type: str) -> set[str]:
    root = (await db.execute(select(Organization).where(Organization.name == "Root"))).scalar_one()
    rows = (
        (
            await db.execute(
                select(Organization).where(
                    Organization.type == org_type,
                    Organization.parent_id == root.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {o.name for o in rows}


async def test_seed_ubnd_xa_creates_all_under_root(db):
    created, skipped = await seed_ubnd_xa(db)
    assert created == len(UBND_XA_NAMES)
    assert skipped == 0
    assert await _names_by_type(db, OrgType.UBND_XA.value) == set(UBND_XA_NAMES)


async def test_seed_so_ban_nganh_creates_all_under_root(db):
    created, skipped = await seed_so_ban_nganh(db)
    assert created == len(SO_BAN_NGANH_NAMES)
    assert skipped == 0
    assert await _names_by_type(db, OrgType.SO_BAN_NGANH.value) == set(SO_BAN_NGANH_NAMES)


async def test_seed_all_both_types(db):
    result = await seed_all(db)
    assert result["ubnd_xa"] == (len(UBND_XA_NAMES), 0)
    assert result["so_ban_nganh"] == (len(SO_BAN_NGANH_NAMES), 0)


async def test_seed_is_idempotent(db):
    await seed_all(db)

    created2, skipped2 = await seed_ubnd_xa(db)
    assert (created2, skipped2) == (0, len(UBND_XA_NAMES))
    created3, skipped3 = await seed_so_ban_nganh(db)
    assert (created3, skipped3) == (0, len(SO_BAN_NGANH_NAMES))

    total = (
        await db.execute(
            select(func.count()).select_from(Organization).where(
                Organization.type.in_([OrgType.UBND_XA.value, OrgType.SO_BAN_NGANH.value])
            )
        )
    ).scalar_one()
    assert total == len(UBND_XA_NAMES) + len(SO_BAN_NGANH_NAMES)
