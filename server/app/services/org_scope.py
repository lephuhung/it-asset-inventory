"""Resolve phạm vi org cho alert rule (scope_mode: org_only | org_tree | system)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Organization


async def all_org_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Toàn bộ org id (cho scope_mode='system')."""
    rows = (await db.execute(select(Organization.id))).scalars().all()
    return list(rows)


async def scope_orgs(
    db: AsyncSession, *, org_id: uuid.UUID | None, scope_mode: str
) -> list[uuid.UUID]:
    """Trả list org_id mà subscription bao phủ.

    - system:  tất cả org
    - org_only: [org_id]
    - org_tree: [org_id] + mọi descendants
    """
    if scope_mode == "system":
        return await all_org_ids(db)
    if org_id is None:
        return []
    if scope_mode == "org_only":
        return [org_id]

    # org_tree — walk cây
    rows = (await db.execute(select(Organization.id, Organization.parent_id))).all()
    by_parent: dict[str, list[uuid.UUID]] = {}
    for oid, parent_id in rows:
        by_parent.setdefault(str(parent_id) if parent_id else "", []).append(oid)

    out: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    def walk(oid: uuid.UUID) -> None:
        if oid in seen:
            return
        seen.add(oid)
        out.append(oid)
        for child in by_parent.get(str(oid), []):
            walk(child)

    walk(org_id)
    return out
