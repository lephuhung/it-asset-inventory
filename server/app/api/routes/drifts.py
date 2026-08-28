"""Fingerprint drift (tính năng #4, Phase 3) — admin duyệt khi đổi mainboard / ghost Win.

Enroll phát hiện fingerprint mới lệch máy cũ → tạo bản ghi pending (xem enroll.py).
Admin: approve → cập nhật fingerprint + machine_uuid của máy; reject → giữ nguyên.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, visible_org_ids
from app.core.audit import append_audit
from app.db.models import FingerprintDrift, Machine, User
from app.db.session import get_db
from app.schemas import FingerprintDriftOut, MachineDecision, Page
from app.services.fingerprint import compute_weighted_id

router = APIRouter(prefix="/api/drifts", tags=["drifts"])


async def _to_out(db: AsyncSession, d: FingerprintDrift) -> FingerprintDriftOut:
    m = (
        await db.execute(select(Machine).where(Machine.id == d.machine_id))
    ).scalar_one_or_none()
    return FingerprintDriftOut(
        id=d.id,
        machine_id=d.machine_id,
        hostname=m.hostname if m else None,
        old_fingerprint=d.old_fingerprint,
        new_fingerprint=d.new_fingerprint,
        reason=d.reason,
        status=d.status,
        created_at=d.created_at,
    )


@router.get("", response_model=Page[FingerprintDriftOut])
async def list_drifts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    status_filter: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Danh sách drift trong phạm vi quyền (máy thuộc org user + cấp dưới)."""
    from sqlalchemy import func as sa_func

    visible = await visible_org_ids(db, user)
    q = select(FingerprintDrift).join(Machine, Machine.id == FingerprintDrift.machine_id)
    q = q.where(Machine.org_id.in_(visible))
    if status_filter:
        q = q.where(FingerprintDrift.status == status_filter)

    total = (await db.execute(select(sa_func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(q.order_by(FingerprintDrift.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return Page[FingerprintDriftOut](
        items=[await _to_out(db, d) for d in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _resolve(drift_id: uuid.UUID, decision: str, admin: User, db: AsyncSession) -> FingerprintDriftOut:
    drift = (
        await db.execute(select(FingerprintDrift).where(FingerprintDrift.id == drift_id))
    ).scalar_one_or_none()
    if drift is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Drift không tồn tại")
    machine = (
        await db.execute(select(Machine).where(Machine.id == drift.machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy không tồn tại")
    visible = await visible_org_ids(db, admin)
    if str(machine.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xử lý drift này")
    if drift.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Drift đã được xử lý ({drift.status})")

    if decision == "approved":
        machine.fingerprint = drift.new_fingerprint
        machine.machine_uuid = compute_weighted_id(drift.new_fingerprint)
    drift.status = decision
    drift.resolved_at = datetime.now(UTC)
    drift.resolved_by = admin.id
    await append_audit(
        db, action=f"fingerprint.{decision}", actor=str(admin.id), target=str(machine.id), machine_id=machine.id
    )
    await db.commit()
    return await _to_out(db, drift)


@router.post("/{drift_id}/approve", response_model=FingerprintDriftOut)
async def approve_drift(
    drift_id: uuid.UUID,
    body: MachineDecision,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Chấp nhận fingerprint mới (máy đã đổi mainboard / cài lại Win thật sự)."""
    return await _resolve(drift_id, "approved", admin, db)


@router.post("/{drift_id}/reject", response_model=FingerprintDriftOut)
async def reject_drift(
    drift_id: uuid.UUID,
    body: MachineDecision,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Từ chối — giữ fingerprint cũ (nghi gian lận định danh)."""
    return await _resolve(drift_id, "rejected", admin, db)