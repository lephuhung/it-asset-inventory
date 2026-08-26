"""Audit log read-only (Sprint 4, mục 7.2) — phân quyền đọc theo vai trò.

- Super Admin (kèm legacy): xem mọi dòng.
- Org Admin: chỉ xem các dòng audit gắn với máy thuộc cây tổ chức của mình.
- Viewer: bị từ chối (403).
- `GET /api/audit/verify` — kiểm tra toàn bộ hash chain (phát hiện dòng bị sửa/xóa).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SUPER_ADMIN_ROLES, get_current_user, visible_org_ids
from app.core.audit import anchor_hash, verify_chain
from app.db.models import AuditLog, User
from app.db.session import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _to_out(e: AuditLog) -> dict:
    return {
        "id": e.id,
        "actor": e.actor,
        "action": e.action,
        "target": e.target,
        "ts": e.ts.isoformat(),
        "ip": e.ip,
        "prev_hash": e.prev_hash,
        "content_hash": e.content_hash,
        "request_id": e.request_id,
        "machine_id": str(e.machine_id) if e.machine_id else None,
    }


@router.get("")
async def list_audit(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    action: str | None = None,
    actor: str | None = None,
    machine_id: uuid.UUID | None = None,
    q: str | None = None,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Danh sách audit log mới nhất trước, có lọc + phân trang."""
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if user.role not in SUPER_ADMIN_ROLES:
        if user.role not in {"org_admin", "admin_org"}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem audit log")
        # Org admin: chỉ audit gắn với máy trong cây tổ chức của mình
        visible = await visible_org_ids(db, user)
        from app.db.models import Machine

        sub = (
            select(AuditLog.id)
            .join(Machine, Machine.id == AuditLog.machine_id)
            .where(Machine.org_id.in_(visible))
        )
        query = query.where(AuditLog.id.in_(sub))
        count_query = count_query.where(AuditLog.id.in_(sub))

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if actor:
        query = query.where(AuditLog.actor.ilike(f"%{actor}%"))
        count_query = count_query.where(AuditLog.actor.ilike(f"%{actor}%"))
    if machine_id:
        query = query.where(AuditLog.machine_id == machine_id)
        count_query = count_query.where(AuditLog.machine_id == machine_id)
    if q:
        like = f"%{q}%"
        query = query.where(
            AuditLog.action.ilike(like)
            | AuditLog.target.ilike(like)
            | AuditLog.actor.ilike(like)
        )
        count_query = count_query.where(
            AuditLog.action.ilike(like)
            | AuditLog.target.ilike(like)
            | AuditLog.actor.ilike(like)
        )
    if from_ts:
        query = query.where(AuditLog.ts >= from_ts)
        count_query = count_query.where(AuditLog.ts >= from_ts)
    if to_ts:
        query = query.where(AuditLog.ts <= to_ts)
        count_query = count_query.where(AuditLog.ts <= to_ts)

    total = (await db.execute(count_query)).scalar_one()
    rows = (
        (await db.execute(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return {
        "items": [_to_out(e) for e in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/actions")
async def list_actions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Danh sách các action đã xuất hiện (cho bộ lọc)."""
    if user.role not in SUPER_ADMIN_ROLES and user.role not in {"org_admin", "admin_org"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem audit log")
    rows = (
        (await db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action)))
        .scalars()
        .all()
    )
    return rows


@router.get("/verify")
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Kiểm tra hash chain toàn bộ — phát hiện dòng bị sửa/xóa (mục 7.2)."""
    if user.role not in SUPER_ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ Super Admin kiểm tra hash chain")
    ok, broken = await verify_chain(db)
    anchor = await anchor_hash(db)
    return {
        "ok": ok,
        "broken_index": broken,  # index dòng đầu tiên đứt chuỗi (None nếu OK)
        "checked": (await db.execute(select(func.count(AuditLog.id)))).scalar_one(),
        "anchor_hash": anchor,
    }