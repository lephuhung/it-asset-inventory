"""External API cho investigation — Hermes Agent hoặc service khác.

Endpoints:
  GET  /api/external/llm-dfir/investigations/pending
       Hermes poll list job đang chờ. Auth: API key với scope `investigation:read`.
       Sau khi nhận job, mark polled.

  POST /api/external/llm-dfir/investigations/{id}/result
       Hermes submit kết quả. Auth: API key với scope `investigation:write`.
       Body: ExternalInvestigationResultIn. Idempotency: X-Idempotency-Key.

  GET  /api/external/llm-dfir/investigations/{id}
       Xem chi tiết 1 investigation. Auth: API key với scope `investigation:read`.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import ApiKey, DfirInvestigation, Machine
from app.schemas import (
    ExternalInvestigationAckOut,
    ExternalInvestigationPendingOut,
    ExternalInvestigationResultIn,
)

logger = logging.getLogger("llm.dfir.external")

router = APIRouter(prefix="/api/external/llm-dfir", tags=["external-llm-dfir"])


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _auth_api_key(
    db: AsyncSession, request: Request, *required_scopes: str
) -> tuple[ApiKey, str]:
    """Return (key, key_name) — name là string snapshot để tránh lazy load sau commit."""
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(401, "Missing Authorization Bearer")
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash, ApiKey.enabled == True  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if not key:
        raise HTTPException(401, "API key không hợp lệ")
    have = set(key.scope.split())
    if not have.issuperset(required_scopes):
        raise HTTPException(403, f"Thiếu scope: {set(required_scopes) - have}")
    # Snapshot tên key trước commit (sau commit các field bị expired)
    key_name = key.name
    key.last_used_at = datetime.now(UTC)
    await db.commit()
    return key, key_name


@router.get(
    "/investigations/pending",
    response_model=list[ExternalInvestigationPendingOut],
)
async def list_pending_investigations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, le=50),
):
    """Hermes poll: list các investigation đang chờ external xử lý.

    Auth: API key với scope `investigation:read` (cũng chấp nhận `investigation:write`).
    """
    key, key_name = await _auth_api_key(db, request, "investigation:read", "investigation:write")

    from app.services import dfir_investigation as inv_svc

    pending = await inv_svc.list_pending_for_external(db, limit=limit)
    out: list[ExternalInvestigationPendingOut] = []
    for inv in pending:
        # Lookup machine info
        machine = (
            await db.execute(select(Machine).where(Machine.id == inv.machine_id))
        ).scalar_one_or_none()
        hostname = machine.hostname if machine else None
        # Mark as polled
        await inv_svc.mark_external_polled(db, inv)
        # Build callback URL cho Hermes gọi POST result về
        # Hermes có thể đặt callback base URL qua header X-Callback-Base
        callback_base = request.headers.get("X-Callback-Base", str(request.base_url).rstrip("/"))
        callback_url = f"{callback_base}/api/external/llm-dfir/investigations/{inv.id}/result"
        out.append(
            ExternalInvestigationPendingOut(
                id=inv.id,
                machine_id=inv.machine_id,
                velociraptor_client_id=inv.velociraptor_client_id,
                machine_hostname=hostname,
                machine_fqdn=None,
                machine_os=None,
                artifacts=inv.artifacts or [],
                custom_instructions=inv.custom_instructions,
                created_at=inv.created_at,
                callback_url=callback_url,
            )
        )
    logger.info(
        "External pending poll by key=%s → %d investigations",
        key_name, len(out),
    )
    return out


@router.post(
    "/investigations/{inv_id}/result",
    response_model=ExternalInvestigationAckOut,
)
async def submit_investigation_result(
    inv_id: str,
    body: ExternalInvestigationResultIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Hermes gọi POST này để submit kết quả phân tích.

    Auth: API key với scope `investigation:write`.
    Idempotency: gửi kèm header `X-Idempotency-Key` để chống duplicate.
    """
    key, key_name = await _auth_api_key(db, request, "investigation:write")
    idem = request.headers.get("X-Idempotency-Key")

    from app.services import dfir_investigation as inv_svc

    inv_dict = await inv_svc.submit_external_result(
        db,
        investigation_id=str(inv_id),
        api_key_id=str(key.id),
        report_markdown=body.report_markdown,
        severity=body.severity or "info",
        findings_count=body.findings_count,
        findings=body.findings,
        iocs=body.iocs,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        estimated_cost_usd=body.estimated_cost_usd,
        error=body.error,
        external_job_id=body.external_job_id,
        raw_response=body.raw_response,
        idempotency_key=idem,
    )

    inv_status = inv_dict["status"]
    msg = (
        "Đã lưu kết quả" if inv_status == "completed"
        else "Đã ghi nhận lỗi từ external"
    )
    logger.info(
        "External result submitted: investigation=%s status=%s severity=%s api_key=%s",
        inv_dict["id"], inv_status, inv_dict["severity"], key_name,
    )
    return ExternalInvestigationAckOut(
        id=inv_dict["id"],
        status=inv_status,
        message=msg,
        notification_id=None,
    )


@router.get(
    "/investigations/{inv_id}",
    response_model=ExternalInvestigationPendingOut,
)
async def get_investigation(
    inv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Hermes xem chi tiết 1 investigation (VD để biết job nào pending)."""
    await _auth_api_key(db, request, "investigation:read", "investigation:write")
    inv = (
        await db.execute(
            select(DfirInvestigation).where(DfirInvestigation.id == _parse_inv_id_or_404(inv_id))
        )
    ).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Investigation không tồn tại")
    machine = (
        await db.execute(select(Machine).where(Machine.id == inv.machine_id))
    ).scalar_one_or_none()
    callback_base = request.headers.get("X-Callback-Base", str(request.base_url).rstrip("/"))
    return ExternalInvestigationPendingOut(
        id=inv.id,
        machine_id=inv.machine_id,
        velociraptor_client_id=inv.velociraptor_client_id,
        machine_hostname=machine.hostname if machine else None,
        machine_fqdn=None,
        machine_os=None,
        artifacts=inv.artifacts or [],
        custom_instructions=inv.custom_instructions,
        created_at=inv.created_at,
        callback_url=f"{callback_base}/api/external/llm-dfir/investigations/{inv.id}/result",
    )


def _parse_inv_id_or_404(inv_id: str):
    """Parse investigation ID hoặc 404 (tránh 422 cho invalid UUID)."""
    import uuid
    try:
        return uuid.UUID(inv_id)
    except (ValueError, TypeError):
        from fastapi import HTTPException
        raise HTTPException(404, f"Investigation ID không hợp lệ: {inv_id!r}")
