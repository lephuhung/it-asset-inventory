"""Alert rules (subscriptions) — schema mới: template_code + scope_mode + recipient_mode.

- List/create/update/delete theo quyền (visible_org_ids).
- POST /{id}/test: dry-run render + resolve recipients — KHÔNG gửi notification thật.
- History events nằm ở route riêng (alert_events.py).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, is_super_admin, require_admin, visible_org_ids
from app.db.models import AlertRule, User
from app.schemas import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleTestOut,
    AlertRuleUpdate,
    Page,
)
from app.services.alert_templates import get_template, render_template, validate_template_vars
from app.services.org_scope import scope_orgs

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])


async def _rule_to_out(db: AsyncSession, r: AlertRule) -> AlertRuleOut:
    tpl = await get_template(db, r.template_code)
    return AlertRuleOut(
        id=r.id,
        name=r.name,
        template_code=r.template_code,
        template_name=tpl.name if tpl else None,
        org_id=r.org_id,
        scope_mode=r.scope_mode,
        recipient_mode=r.recipient_mode,
        config=r.config or {},
        enabled=r.enabled,
        created_at=r.created_at,
    )


async def _can_access(db: AsyncSession, admin: User, rule: AlertRule) -> bool:
    """Admin được phép xem/sửa rule nếu rule org nằm trong cây con của họ."""
    if is_super_admin(admin):
        return True
    visible = await visible_org_ids(db, admin)
    return rule.org_id is None or str(rule.org_id) in visible


@router.get("", response_model=Page[AlertRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    visible = await visible_org_ids(db, admin)
    all_rows = (
        (await db.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))).scalars().all()
    )
    filtered = [r for r in all_rows if r.org_id is None or str(r.org_id) in visible]
    total = len(filtered)
    items = [await _rule_to_out(db, r) for r in filtered[offset : offset + limit]]
    return Page[AlertRuleOut](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=AlertRuleOut)
async def create_rule(
    body: AlertRuleCreate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    # Validate template tồn tại
    tpl = await get_template(db, body.template_code)
    if tpl is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Template không tồn tại")

    # scope_mode=system chỉ Super Admin
    if body.scope_mode == "system" and not is_super_admin(admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ Super Admin tạo rule phạm vi hệ thống")
    if body.scope_mode != "system" and body.org_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scope_mode != system cần org_id")

    visible = await visible_org_ids(db, admin)
    if body.org_id and str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo rule cho tổ chức này")

    # Merge config với default_config template
    config = {**(tpl.default_config or {}), **(body.config or {})}

    rule = AlertRule(
        name=body.name,
        template_code=body.template_code,
        org_id=body.org_id,
        scope_mode=body.scope_mode,
        recipient_mode=body.recipient_mode,
        config=config,
        enabled=body.enabled,
        created_by=admin.id,
    )
    db.add(rule)
    await db.commit()
    return await _rule_to_out(db, rule)


@router.patch("/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if not await _can_access(db, admin, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền sửa rule này")

    if body.name is not None:
        rule.name = body.name
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.template_code is not None:
        tpl = await get_template(db, body.template_code)
        if tpl is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Template không tồn tại")
        rule.template_code = body.template_code
        rule.config = {**(tpl.default_config or {}), **(rule.config or {})}
    if body.org_id is not None:
        visible = await visible_org_ids(db, admin)
        if str(body.org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền gán org này")
        rule.org_id = body.org_id
    if body.scope_mode is not None:
        if body.scope_mode == "system" and not is_super_admin(admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ Super Admin set scope system")
        rule.scope_mode = body.scope_mode
    if body.recipient_mode is not None:
        rule.recipient_mode = body.recipient_mode
    if body.config is not None:
        rule.config = body.config
    await db.commit()
    return await _rule_to_out(db, rule)


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if not await _can_access(db, admin, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xóa rule này")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


@router.post("/{rule_id}/test", response_model=AlertRuleTestOut)
async def test_rule(
    rule_id: uuid.UUID,
    body: dict | None = None,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run: render title/body + resolve recipients. KHÔNG gửi."""
    body = body or {}
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if not await _can_access(db, admin, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền test rule này")

    tpl = await get_template(db, rule.template_code)
    if tpl is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Template không tồn tại")

    ctx = dict(body.get("context") or {})
    ctx.setdefault("hostname", "[test]")
    ctx.setdefault("org_name", "[org test]")
    ctx.setdefault("threshold_days", (rule.config or {}).get("threshold_days", 7))

    title = render_template(tpl.title_template, tpl.allowed_vars or [], ctx)
    body_text = render_template(tpl.body_template or "", tpl.allowed_vars or [], ctx) or None
    warnings = validate_template_vars(tpl.title_template, tpl.body_template, tpl.allowed_vars or [])

    scope_ids = await scope_orgs(db, org_id=rule.org_id, scope_mode=rule.scope_mode)
    from app.services.alert_engine import AlertEngine
    recipients = await AlertEngine()._resolve_recipients(db, rule, tpl, scope_ids)

    return AlertRuleTestOut(
        template_code=rule.template_code,
        title=title,
        body=body_text,
        recipients=[
            {"user_id": str(u.id), "email": u.email, "full_name": u.full_name,
             "telegram_linked": bool(u.telegram_chat_id)}
            for u in recipients
        ],
        total_recipients=len(recipients),
        warnings=warnings,
    )
