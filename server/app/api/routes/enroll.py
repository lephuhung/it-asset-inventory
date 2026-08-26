"""Route enroll — agent đăng ký máy (token + fingerprint + CSR)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.config import settings
from app.core.security import hash_token
from app.db.models import EnrollToken, Machine, MachineStatus, OrgAssignRule, TokenStatus, User
from app.db.session import get_db
from app.schemas import EnrollRequest, EnrollResponse
from app.services.ca import get_ca_service
from app.services.fingerprint import compute_weighted_id, is_same_machine

router = APIRouter(prefix="/api/enroll", tags=["enroll"])
limiter = Limiter(key_func=get_remote_address)


@router.post("", response_model=EnrollResponse)
@limiter.limit(settings.rate_limit_enroll)
async def enroll(
    request: Request,
    body: EnrollRequest,
    db: AsyncSession = Depends(get_db),
):
    """Agent enroll: token + fingerprint → fuzzy-match → step-ca ký CSR → machine_id + cert.

    Enroll xảy ra TRƯỚC khi agent có client cert → dùng token auth (không phải mTLS).
    Sau enroll, heartbeat/inventory mới dùng mTLS (header từ nginx).
    """
    ip = request.client.host if request.client else None

    # 1. Kiểm tra token
    token_hash = hash_token(body.token)
    token_row = (
        await db.execute(select(EnrollToken).where(EnrollToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if token_row is None:
        await append_audit(db, action="enroll.invalid_token", target=body.token[:16] + "…", ip=ip)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token không tồn tại")

    now = datetime.now(UTC)
    if token_row.status == TokenStatus.REVOKED.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token đã bị thu hồi")
    if token_row.status == TokenStatus.USED.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token đã dùng")
    if token_row.expires_at.replace(tzinfo=UTC) < now:
        token_row.status = TokenStatus.EXPIRED.value
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token hết hạn")

    # 2. Xác định org đích: org của token, trừ khi có org-assign rule khớp hostname/IP (tính năng #13)
    from app.api.routes.org_rules import find_assign_org_id

    rules = (await db.execute(select(OrgAssignRule))).scalars().all()
    target_org_id = find_assign_org_id(rules, body.hostname, ip) or token_row.org_id

    # 3. Fuzzy-match fingerprint: máy cũ hay máy mới?
    fp_dict = body.fingerprint.model_dump(exclude_none=True)
    weighted = compute_weighted_id(fp_dict)
    existing = (
        await db.execute(
            select(Machine).where(
                Machine.org_id == target_org_id, Machine.machine_uuid == weighted
            )
        )
    ).scalar_one_or_none()

    is_new = existing is None
    if existing is None:
        # Tìm máy tương đồng trong cùng org (fuzzy — ghost win, thay mainboard)
        candidates = (
            (await db.execute(select(Machine).where(Machine.org_id == target_org_id)))
            .scalars()
            .all()
        )
        for m in candidates:
            if is_same_machine(fp_dict, m.fingerprint or {}):
                existing = m
                is_new = False
                break

    # 4. Tạo mới hoặc cập nhật máy
    if existing is None:
        machine = Machine(
            org_id=target_org_id,
            machine_uuid=weighted,
            hostname=body.hostname,
            fingerprint=fp_dict,
            status=MachineStatus.PENDING.value,  # chờ approve (Phase 3) — tạm online ngay
            enrolled_at=now,
            last_seen_at=now,
        )
        if token_row.email:
            user = (
                await db.execute(select(User).where(User.email == token_row.email))
            ).scalar_one_or_none()
            if user:
                machine.assigned_user_id = user.id
        db.add(machine)
        await db.flush()
    else:
        # Máy đã tồn tại — nếu fingerprint (weighted id) khác với máy cũ → fingerprint drift
        existing.hostname = body.hostname or existing.hostname
        existing.last_seen_at = now
        existing.status = MachineStatus.ONLINE.value
        machine = existing

        if existing.machine_uuid != weighted:
            from app.db.models import FingerprintDrift

            already = (
                await db.execute(
                    select(FingerprintDrift).where(
                        FingerprintDrift.machine_id == machine.id,
                        FingerprintDrift.status == "pending",
                    )
                )
            ).scalar_one_or_none()
            if already is None:
                reason = "os_reinstall"
                if existing.fingerprint and is_same_machine(fp_dict, existing.fingerprint or {}):
                    reason = "other"
                db.add(
                    FingerprintDrift(
                        machine_id=machine.id,
                        old_fingerprint=existing.fingerprint or {},
                        new_fingerprint=fp_dict,
                        reason=reason,
                    )
                )
                await append_audit(
                    db,
                    action="fingerprint.drift_detected",
                    actor=f"agent:{machine.id}",
                    target=str(machine.id),
                    machine_id=machine.id,
                )

    # 4. step-ca ký CSR
    ca = get_ca_service()
    cert_pem = await ca.sign_csr(body.csr_pem, machine.id)

    # 5. Đánh dấu token đã dùng
    token_row.status = TokenStatus.USED.value
    token_row.used_at = now
    token_row.used_by = machine.id

    await append_audit(
        db,
        action="enroll.success" if is_new else "enroll.reassigned",
        actor=f"agent:{machine.id}",
        target=str(machine.id),
        ip=ip,
        machine_id=machine.id,
    )
    await db.commit()

    renew_after = now + timedelta(days=int(settings.client_cert_valid_days * 0.7))
    agent_cfg = settings.agent_config_payload()
    return EnrollResponse(
        machine_id=machine.id,
        client_cert_pem=cert_pem,
        ca_cert_pem=None,  # prod: trả CA cert nếu cần
        renew_after=renew_after,
        is_new_machine=is_new,
        status=MachineStatus(machine.status),
        agent_server_url=settings.agent_server_url,
        heartbeat_interval_seconds=agent_cfg["heartbeat_interval_seconds"],
        heartbeat_jitter_seconds=agent_cfg["heartbeat_jitter_seconds"],
        inventory_interval_hours=agent_cfg["inventory_interval_hours"],
    )
