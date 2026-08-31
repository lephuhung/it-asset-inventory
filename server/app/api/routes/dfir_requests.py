"""Route /api/dfir/requests — Admin gửi yêu cầu điều tra, Super Admin duyệt.

Mục đích: Ẩn chi tiết kỹ thuật Velociraptor khỏi admin. Admin chỉ thấy:
- "Tôi đã gửi yêu cầu điều tra, trạng thái: pending/approved/completed"
Super Admin thấy thêm: client_id, GUI URL, flow_id.

Endpoints:
  POST   /api/dfir/requests           - Admin tạo request mới
  GET    /api/dfir/requests           - List requests (admin chỉ thấy của mình)
  GET    /api/dfir/requests/{id}      - Chi tiết 1 request
  PATCH  /api/dfir/requests/{id}      - Super Admin duyệt/reject/complete
  POST   /api/dfir/requests/{id}/approve  - shortcut approve
  POST   /api/dfir/requests/{id}/reject   - shortcut reject
  POST   /api/dfir/requests/{id}/complete - shortcut complete (chạy Velociraptor collect)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_admin,
    require_super_admin,
)
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db import session as db_session
from app.db.models import (
    DfirInvestigationRequest,
    Machine,
    User,
)
from app.schemas import (
    DfirInvestigationRequestCreate,
    DfirInvestigationRequestDetail,
    DfirInvestigationRequestOut,
    DfirInvestigationRequestReview,
)

router = APIRouter(prefix="/api/dfir/requests", tags=["dfir-requests"])


async def _request_to_out(req: DfirInvestigationRequest, include_vendor: bool) -> DfirInvestigationRequestOut:
    """Convert model → schema, ẩn chi tiết Velociraptor nếu non-super-admin."""
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Requester info
        requester = (await db.execute(select(User).where(User.id == req.requested_by))).scalar_one_or_none()
        # Machine hostname
        machine = (await db.execute(select(Machine).where(Machine.id == req.machine_id))).scalar_one_or_none()

    return DfirInvestigationRequestOut(
        id=req.id,
        machine_id=req.machine_id,
        machine_hostname=machine.hostname if machine else None,
        artifact=req.artifact,
        reason=req.reason,
        urgency=req.urgency,
        status=req.status,
        requested_by=requester.full_name if requester else None,
        requested_at=req.created_at,
        review_notes=req.review_notes,
        completed_at=req.completed_at,
        # Ẩn các field Velociraptor nếu không phải super_admin
        velociraptor_flow_id=req.velociraptor_flow_id if include_vendor else None,
        velociraptor_url=req.velociraptor_url if include_vendor else None,
        reviewed_by=None,
        reviewed_at=None,
    )


@router.post("", response_model=DfirInvestigationRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    body: DfirInvestigationRequestCreate,
    request_obj: Request,
    db: AsyncSession = Depends(db_session.get_db),
    user: User = Depends(require_admin()),
):
    """Admin (org_admin/admin_global/super_admin) gửi yêu cầu điều tra."""
    # Check machine exists
    machine = (
        await db.execute(select(Machine).where(Machine.id == body.machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy không tồn tại")

    req = DfirInvestigationRequest(
        machine_id=body.machine_id,
        artifact=body.artifact,
        reason=body.reason,
        urgency=body.urgency,
        status="pending",
        requested_by=user.id,
    )
    db.add(req)
    await db.flush()
    await append_audit(
        db,
        action="dfir.request.create",
        actor=str(user.id),
        target=str(req.id),
        ip=get_client_ip(request_obj),
        machine_id=req.machine_id,
    )
    await db.commit()
    await db.refresh(req)

    # Admin không thấy chi tiết Velociraptor
    return await _request_to_out(req, include_vendor=False)


@router.get("", response_model=None)
async def list_requests(
    db: AsyncSession = Depends(db_session.get_db),
    user: User = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    machine_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[DfirInvestigationRequestOut]:
    """List requests. Admin chỉ thấy của mình; Super Admin thấy tất cả."""
    is_super = user.role == "super_admin"
    q = select(DfirInvestigationRequest).order_by(DfirInvestigationRequest.created_at.desc())
    if not is_super:
        q = q.where(DfirInvestigationRequest.requested_by == user.id)
    if status_filter:
        q = q.where(DfirInvestigationRequest.status == status_filter)
    if machine_id:
        q = q.where(DfirInvestigationRequest.machine_id == machine_id)
    rows = (await db.execute(q.limit(limit))).scalars().all()
    return [await _request_to_out(r, include_vendor=is_super) for r in rows]


@router.get("/{req_id}", response_model=DfirInvestigationRequestDetail)
async def get_request(
    req_id: uuid.UUID,
    db: AsyncSession = Depends(db_session.get_db),
    user: User = Depends(get_current_user),
):
    """Chi tiết 1 request. Admin chỉ thấy của mình."""
    req = (
        await db.execute(select(DfirInvestigationRequest).where(DfirInvestigationRequest.id == req_id))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Yêu cầu không tồn tại")
    if user.role != "super_admin" and req.requested_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem yêu cầu này")
    return await _request_to_out(req, include_vendor=user.role == "super_admin")


@router.post("/{req_id}/approve", response_model=DfirInvestigationRequestOut)
async def approve_request(
    req_id: uuid.UUID,
    request_obj: Request,
    db: AsyncSession = Depends(db_session.get_db),
    admin: User = Depends(require_super_admin()),
):
    """Super Admin duyệt request → status='approved'. Sau đó có thể chạy Velociraptor collect."""
    req = (
        await db.execute(select(DfirInvestigationRequest).where(DfirInvestigationRequest.id == req_id))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Yêu cầu không tồn tại")
    if req.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Yêu cầu đang ở trạng thái {req.status}, không thể duyệt")
    req.status = "approved"
    req.reviewed_by = admin.id
    await append_audit(
        db,
        action="dfir.request.approve",
        actor=str(admin.id),
        target=str(req.id),
        ip=get_client_ip(request_obj),
        machine_id=req.machine_id,
    )
    await db.commit()
    await db.refresh(req)
    return await _request_to_out(req, include_vendor=True)


@router.post("/{req_id}/reject", response_model=DfirInvestigationRequestOut)
async def reject_request(
    req_id: uuid.UUID,
    body: DfirInvestigationRequestReview,
    request_obj: Request,
    db: AsyncSession = Depends(db_session.get_db),
    admin: User = Depends(require_super_admin()),
):
    """Super Admin từ chối request → status='rejected'."""
    req = (
        await db.execute(select(DfirInvestigationRequest).where(DfirInvestigationRequest.id == req_id))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Yêu cầu không tồn tại")
    if req.status not in ("pending", "approved"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Yêu cầu đang ở trạng thái {req.status}")
    req.status = "rejected"
    req.reviewed_by = admin.id
    req.review_notes = body.notes
    await append_audit(
        db,
        action="dfir.request.reject",
        actor=str(admin.id),
        target=str(req.id),
        ip=get_client_ip(request_obj),
        machine_id=req.machine_id,
    )
    await db.commit()
    await db.refresh(req)
    return await _request_to_out(req, include_vendor=True)


@router.post("/{req_id}/complete", response_model=DfirInvestigationRequestOut)
async def complete_request(
    req_id: uuid.UUID,
    body: DfirInvestigationRequestReview,
    request_obj: Request,
    db: AsyncSession = Depends(db_session.get_db),
    admin: User = Depends(require_super_admin()),
):
    """Super Admin đánh dấu request đã chạy xong (đã collect qua Velociraptor)."""
    req = (
        await db.execute(select(DfirInvestigationRequest).where(DfirInvestigationRequest.id == req_id))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Yêu cầu không tồn tại")
    if req.status not in ("approved", "running"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Yêu cầu phải ở trạng thái approved/running, hiện tại: {req.status}")
    req.status = "completed"
    req.completed_at = datetime.now(UTC)
    if body.velociraptor_flow_id:
        req.velociraptor_flow_id = body.velociraptor_flow_id
    if body.notes:
        req.review_notes = body.notes
    await append_audit(
        db,
        action="dfir.request.complete",
        actor=str(admin.id),
        target=str(req.id),
        ip=get_client_ip(request_obj),
        machine_id=req.machine_id,
    )
    await db.commit()
    await db.refresh(req)
    return await _request_to_out(req, include_vendor=True)


@router.patch("/{req_id}", response_model=DfirInvestigationRequestOut)
async def patch_request(
    req_id: uuid.UUID,
    body: DfirInvestigationRequestReview,
    request_obj: Request,
    db: AsyncSession = Depends(db_session.get_db),
    admin: User = Depends(require_super_admin()),
):
    """Generic patch endpoint cho super admin (alias cho /approve /reject /complete)."""
    if body.action == "approve":
        return await approve_request(req_id, request_obj, db, admin)
    elif body.action == "reject":
        return await reject_request(req_id, body, request_obj, db, admin)
    elif body.action == "complete":
        return await complete_request(req_id, body, request_obj, db, admin)
    elif body.action == "fail":
        req = (
            await db.execute(select(DfirInvestigationRequest).where(DfirInvestigationRequest.id == req_id))
        ).scalar_one_or_none()
        if req is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Yêu cầu không tồn tại")
        req.status = "failed"
        req.completed_at = datetime.now(UTC)
        req.review_notes = body.notes
        await append_audit(
            db,
            action="dfir.request.fail",
            actor=str(admin.id),
            target=str(req.id),
            ip=get_client_ip(request_obj),
            machine_id=req.machine_id,
        )
        await db.commit()
        await db.refresh(req)
        return await _request_to_out(req, include_vendor=True)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"action không hợp lệ: {body.action}")
