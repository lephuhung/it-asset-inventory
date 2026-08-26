"""Tự gán tổ chức theo rule (tính năng #13, Phase 2).

Rule khớp hostname pattern (VD `KT-*`) hoặc dải IP (VD `10.0.`) → gán máy cho org.
Áp dụng khi enroll tạo máy MỚI (xem `enroll.py`). Admin tạo rule cho org trong phạm vi mình.
"""
from __future__ import annotations

import fnmatch
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, visible_org_ids
from app.db.models import OrgAssignRule, User
from app.db.session import get_db
from app.schemas import OrgAssignRuleCreate, OrgAssignRuleOut

router = APIRouter(prefix="/api/org-rules", tags=["org-rules"])

VALID_FIELDS = {"hostname", "ip_prefix"}


@router.get("", response_model=list[OrgAssignRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    visible = await visible_org_ids(db, admin)
    rows = (
        (await db.execute(select(OrgAssignRule).order_by(OrgAssignRule.priority, OrgAssignRule.name)))
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rows if str(r.org_id) in visible]


@router.post("", response_model=OrgAssignRuleOut)
async def create_rule(
    body: OrgAssignRuleCreate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    if body.match_field not in VALID_FIELDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="match_field không hợp lệ")
    visible = await visible_org_ids(db, admin)
    if str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo rule cho tổ chức này")
    rule = OrgAssignRule(
        name=body.name,
        org_id=body.org_id,
        match_field=body.match_field,
        pattern=body.pattern,
        enabled=body.enabled,
        priority=body.priority,
        created_by=admin.id,
    )
    db.add(rule)
    await db.commit()
    return _to_out(rule)


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    rule = (await db.execute(select(OrgAssignRule).where(OrgAssignRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    visible = await visible_org_ids(db, admin)
    if str(rule.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xóa rule này")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


def _to_out(r: OrgAssignRule) -> OrgAssignRuleOut:
    return OrgAssignRuleOut(
        id=r.id,
        name=r.name,
        org_id=r.org_id,
        match_field=r.match_field,
        pattern=r.pattern,
        enabled=r.enabled,
        priority=r.priority,
        created_at=r.created_at,
    )


def find_assign_org_id(
    rules: list[OrgAssignRule], hostname: str | None, client_ip: str | None
) -> uuid.UUID | None:
    """Áp dụng rule (ưu tiên cao trước) cho 1 máy — trả org_id hoặc None."""
    for r in sorted(rules, key=lambda x: (x.priority, x.created_at)):
        if not r.enabled:
            continue
        if r.match_field == "hostname" and hostname:
            if fnmatch.fnmatch(hostname.lower(), r.pattern.lower()):
                return r.org_id
        elif r.match_field == "ip_prefix" and client_ip and client_ip.startswith(r.pattern):
            return r.org_id
    return None