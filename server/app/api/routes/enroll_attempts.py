"""Route enroll attempts — hàng đợi máy "xin vào" bị từ chối ở cổng token.

Case xử lý: 1 máy chạy lại lệnh cài với token ĐÃ DÙNG / hết hạn / lạ → trước đây
server chỉ 401 im lặng (admin không thấy, agent retry vô hạn). Giờ mỗi lần như vậy
được ghi vào `enroll_attempts` và hiển thị ở đây để admin quyết:
  - Approve → sinh token thay thế cho org của attempt + trả lệnh cài mới.
  - Reject  → đánh dấu chặn (không sinh token).

Attempt không xác định được org (token lạ) chỉ Super Admin thấy được — tránh lộ
hostname/IP của máy lạ cho org admin khác.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import is_super_admin, require_admin, visible_org_ids
from app.api.routes.tokens import (
    _install_command,
    _install_command_linux,
    _install_command_org_only,
    _validate_install_urls,
)
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.core.security import generate_enroll_token, hash_token
from app.db.models import EnrollAttempt, EnrollToken, Machine, TokenStatus, User
from app.db.session import get_db
from app.schemas import (
    EnrollAttemptApproveResponse,
    EnrollAttemptDecision,
    EnrollAttemptOut,
)
from app.services.agent_settings import effective_agent_config

router = APIRouter(prefix="/api/enroll/attempts", tags=["enroll-attempts"])


async def _get_attempt_in_scope(
    attempt_id: uuid.UUID, admin: User, db: AsyncSession
) -> EnrollAttempt:
    attempt = (
        await db.execute(select(EnrollAttempt).where(EnrollAttempt.id == attempt_id))
    ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu enroll")
    if attempt.org_id is None:
        if not is_super_admin(admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ Super Admin xử lý attempt token lạ")
    else:
        visible = await visible_org_ids(db, admin)
        if str(attempt.org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền với yêu cầu này")
    return attempt


def _attempt_out(attempt: EnrollAttempt, org_name: str | None, matched_hostname: str | None) -> EnrollAttemptOut:
    return EnrollAttemptOut(
        id=attempt.id,
        org_id=attempt.org_id,
        org_name=org_name,
        token_status=attempt.token_status,
        token_prefix=attempt.token_prefix,
        hostname=attempt.hostname,
        ip=attempt.ip,
        fingerprint=attempt.fingerprint or {},
        matched_machine_id=attempt.matched_machine_id,
        matched_machine_hostname=matched_hostname,
        status=attempt.status,
        note=attempt.note,
        created_at=attempt.created_at,
        decided_at=attempt.decided_at,
    )


@router.get("", response_model=list[EnrollAttemptOut])
async def list_attempts(
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Danh sách yêu cầu enroll bị từ chối (mặc định: pending trước, mới nhất trước)."""
    q = select(EnrollAttempt)
    visible = await visible_org_ids(db, admin)
    if is_super_admin(admin):
        # Super Admin thấy hết, kể cả attempt token lạ (org_id=None)
        pass
    else:
        q = q.where(EnrollAttempt.org_id.in_({uuid.UUID(o) for o in visible}))
    if status_filter:
        q = q.where(EnrollAttempt.status == status_filter)

    rows = (
        await db.execute(
            q.order_by(EnrollAttempt.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    out: list[EnrollAttemptOut] = []
    for r in rows:
        org_name = None
        matched_hostname = None
        if r.org_id is not None:
            from app.db.models import Organization

            org = (
                await db.execute(
                    select(Organization.name).where(Organization.id == r.org_id)
                )
            ).scalar_one_or_none()
            org_name = org
        if r.matched_machine_id is not None:
            matched_hostname = (
                await db.execute(
                    select(Machine.hostname).where(Machine.id == r.matched_machine_id)
                )
            ).scalar_one_or_none()
        out.append(_attempt_out(r, org_name, matched_hostname))
    return out


@router.post("/{attempt_id}/approve", response_model=EnrollAttemptApproveResponse)
async def approve_attempt(
    attempt_id: uuid.UUID,
    body: EnrollAttemptDecision,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Approve → sinh token thay thế (TTL 72h) cho org của attempt + lệnh cài mới.

    Máy chưa có trong hệ thống — lần enroll kế tiếp (với token mới) sẽ tạo máy
    status=pending như thường lệ (vẫn qua bước duyệt máy).
    """
    attempt = await _get_attempt_in_scope(attempt_id, admin, db)
    if attempt.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Yêu cầu đã được xử lý")
    if attempt.org_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Token lạ không xác định được tổ chức — sinh token thủ công theo org đúng",
        )

    now = datetime.now(UTC)
    token = generate_enroll_token()
    expires = now + timedelta(hours=72)
    row = EnrollToken(
        token_hash=hash_token(token),
        org_id=attempt.org_id,
        created_by=admin.id,
        note=(
            f"Thay thế cho enroll attempt — máy {attempt.hostname or '?'}, "
            f"IP {attempt.ip or '?'}, token cũ {attempt.token_status}"
        ),
        expires_at=expires,
        status=TokenStatus.PENDING.value,
    )
    db.add(row)
    attempt.status = "approved"
    attempt.decided_by = admin.id
    attempt.decided_at = now
    if body.note:
        attempt.note = body.note

    await append_audit(
        db, action="enroll_attempt.approve", actor=str(admin.id),
        target=str(attempt.id), ip=get_client_ip(request),
    )
    await db.commit()

    agent_cfg = await effective_agent_config(db)
    portal_url = agent_cfg["portal_url"]
    return EnrollAttemptApproveResponse(
        attempt_id=attempt.id,
        token=token,
        install_command=_install_command(token, portal_url, agent_cfg["agent_server_url"]),
        install_command_windows=_install_command(token, portal_url, agent_cfg["agent_server_url"]),
        install_command_windows_org_only=_install_command_org_only(
            token, portal_url, agent_cfg["agent_server_url"]
        ),
        install_command_linux=_install_command_linux(
            token, portal_url, agent_cfg["agent_server_url"]
        ),
        install_offline_url=f"{portal_url}/download/offline-package.zip",
        install_url_warnings=_validate_install_urls(portal_url, agent_cfg["agent_server_url"]),
        expires_at=expires,
    )


@router.post("/{attempt_id}/reject", response_model=dict)
async def reject_attempt(
    attempt_id: uuid.UUID,
    body: EnrollAttemptDecision,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Reject → đánh dấu chặn. Máy không được sinh token từ attempt này."""
    attempt = await _get_attempt_in_scope(attempt_id, admin, db)
    if attempt.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Yêu cầu đã được xử lý")
    attempt.status = "rejected"
    attempt.decided_by = admin.id
    attempt.decided_at = datetime.now(UTC)
    attempt.note = f"Từ chối: {body.note or 'không rõ lý do'}" + (f"\n{attempt.note or ''}" if attempt.note else "")

    await append_audit(
        db, action="enroll_attempt.reject", actor=str(admin.id),
        target=str(attempt.id), ip=get_client_ip(request),
    )
    await db.commit()
    return {"ok": True, "status": attempt.status}
