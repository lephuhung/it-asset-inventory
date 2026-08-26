"""Route alert rules + lịch sử alert (tính năng #14-15, Phase 2).

Rules: máy mới xuất hiện (`machine_new`), mất liên lạc > N ngày (`machine_lost`),
phần mềm lạ (`software_new`), phần cứng thay đổi (`hardware_changed` — Phase 3 sẽ bật).
Job quét chạy trong `monitor.py`; việc gửi (email/Telegram/Zalo) theo cấu hình
SMTP/bot trong settings — khi chưa cấu hình, chỉ ghi event + log (delivered=False).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, visible_org_ids
from app.db.models import AlertEvent, AlertRule, User
from app.db.session import get_db
from app.schemas import AlertEventOut, AlertRuleCreate, AlertRuleOut, AlertRuleUpdate

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])

VALID_TYPES = {"machine_new", "machine_lost", "software_new", "hardware_changed"}
VALID_CHANNELS = {"email", "telegram", "zalo"}


async def _rule_to_out(r: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=r.id,
        name=r.name,
        rule_type=r.rule_type,
        org_id=r.org_id,
        enabled=r.enabled,
        threshold_days=r.threshold_days,
        channels=r.channels or [],
        notify_targets=r.notify_targets or [],
        created_at=r.created_at,
    )


@router.get("", response_model=list[AlertRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """Danh sách rule trong phạm vi quyền (rule org nằm trong cây con của admin)."""
    visible = await visible_org_ids(db, admin)
    rows = (
        (await db.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))).scalars().all()
    )
    return [
        await _rule_to_out(r)
        for r in rows
        if r.org_id is None or str(r.org_id) in visible
    ]


@router.post("", response_model=AlertRuleOut)
async def create_rule(
    body: AlertRuleCreate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    if body.rule_type not in VALID_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Loại rule không hợp lệ")
    bad = set(body.channels) - VALID_CHANNELS
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Kênh không hợp lệ: {sorted(bad)}")
    if body.rule_type == "machine_lost" and not body.threshold_days:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rule mất liên lạc cần threshold_days")

    visible = await visible_org_ids(db, admin)
    if body.org_id and str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo rule cho tổ chức này")

    rule = AlertRule(
        name=body.name,
        rule_type=body.rule_type,
        org_id=body.org_id,
        enabled=body.enabled,
        threshold_days=body.threshold_days,
        channels=body.channels,
        notify_targets=body.notify_targets,
        created_by=admin.id,
    )
    db.add(rule)
    await db.commit()
    return await _rule_to_out(rule)


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
    if rule.org_id:
        visible = await visible_org_ids(db, admin)
        if str(rule.org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền sửa rule này")

    if body.name is not None:
        rule.name = body.name
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.threshold_days is not None:
        rule.threshold_days = body.threshold_days
    if body.channels is not None:
        bad = set(body.channels) - VALID_CHANNELS
        if bad:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Kênh không hợp lệ: {sorted(bad)}")
        rule.channels = body.channels
    if body.notify_targets is not None:
        rule.notify_targets = body.notify_targets
    await db.commit()
    return await _rule_to_out(rule)


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if rule.org_id:
        visible = await visible_org_ids(db, admin)
        if str(rule.org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xóa rule này")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


@router.get("/events", response_model=list[AlertEventOut])
async def list_events(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
    limit: int = 100,
):
    """Lịch sử alert đã kích hoạt (mới nhất trước)."""
    rows = (
        (
            await db.execute(select(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(limit))
        )
        .scalars()
        .all()
    )
    return [
        AlertEventOut(
            id=e.id,
            rule_id=e.rule_id,
            machine_id=e.machine_id,
            severity=e.severity,
            message=e.message,
            channels=e.channels or [],
            delivered=e.delivered,
            created_at=e.created_at,
        )
        for e in rows
    ]