"""Route offline enroll — admin proxy enrollment cho máy cách ly (Phase 3).

Luồng: máy cách ly sinh CSR + fingerprint → ghi file JSON trên USB. Admin copy file
lên máy có mạng → POST /api/offline/enroll → nhận client cert đã ký → copy về máy
cách ly cài vào Windows Cert Store.

So với /api/enroll (agent gọi trực tiếp):
  - Auth: require_admin() (admin proxy thay cho agent, KHÔNG cần mTLS).
  - Audit: action `offline.enroll` (thay vì `enroll.success`).
  - Rate-limit: theo admin user thay vì IP.
  - Không yêu cầu agent có mạng tới server.

Quy trình đầy đủ & định dạng file USB: xem `docs/OFFLINE_AGENT_SPEC.md`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.routes.enroll import perform_enroll
from app.core.audit import append_audit
from app.core.config import settings
from app.db.models import MachineStatus, TokenStatus, User
from app.db.session import get_db
from app.schemas import OfflineEnrollRequest, OfflineEnrollResponse
from app.services.agent_settings import effective_agent_config
from app.services.ca import get_ca_service

router = APIRouter(prefix="/api/offline", tags=["offline"])


@router.post("/enroll", response_model=OfflineEnrollResponse)
async def offline_enroll(
    request: Request,
    body: OfflineEnrollRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """Admin proxy enroll cho máy cách ly.

    Body là JSON được sinh bởi `OrgInventoryAgent.exe --enroll-offline ...` rồi
    copy qua USB tới máy admin có mạng. Response là JSON chứa client cert đã được
    CA ký — admin lưu ra file, copy USB ngược về máy cách ly để cài cert.
    """
    fp_dict = body.fingerprint.model_dump(exclude_none=True)
    ip = request.client.host if request.client else None

    # Tái sử dụng toàn bộ logic enroll online (validate token, fuzzy-match,
    # tạo/cập nhật Machine, ghi FingerprintDrift nếu cần). Audit actor là admin
    # đang proxy, không phải agent — phân biệt rõ trong audit log.
    machine, is_new, token_row = await perform_enroll(
        db,
        body.token,
        body.hostname,
        fp_dict,
        audit_actor=f"admin:{admin.id}",
        audit_ip=ip,
    )

    # step-ca ký CSR
    ca = get_ca_service()
    cert_pem = await ca.sign_csr(body.csr_pem, machine.id)

    now = datetime.now(UTC)
    token_row.status = TokenStatus.USED.value
    token_row.used_at = now
    token_row.used_by = machine.id

    await append_audit(
        db,
        action="offline.enroll",
        actor=f"admin:{admin.id}",
        target=str(machine.id),
        ip=ip,
        machine_id=machine.id,
        # `note` không có trong Audit append — ghi qua action label đủ tra được.
    )
    await db.commit()

    renew_after = now + timedelta(days=int(settings.client_cert_valid_days * 0.7))
    agent_cfg = await effective_agent_config(db)
    return OfflineEnrollResponse(
        machine_id=machine.id,
        client_cert_pem=cert_pem,
        ca_cert_pem=None,
        renew_after=renew_after,
        is_new_machine=is_new,
        status=MachineStatus(machine.status),
        agent_server_url=agent_cfg["agent_server_url"],
        heartbeat_interval_seconds=agent_cfg["heartbeat_interval_seconds"],
        heartbeat_jitter_seconds=agent_cfg["heartbeat_jitter_seconds"],
        inventory_interval_hours=agent_cfg["inventory_interval_hours"],
    )
