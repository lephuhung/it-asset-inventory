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
    ExternalInvestigationStatusIn,
)

logger = logging.getLogger("llm.dfir.external")

router = APIRouter(prefix="/api/external/llm-dfir", tags=["external-llm-dfir"])

_STATUS_PHASE_ORDER = {
    "dispatching": 0,
    "running": 1,
    "collecting": 2,
    "finalizing": 3,
    "completed": 4,
    "failed": 4,
}


@router.post("/investigations/{inv_id}/status")
async def update_investigation_status(
    inv_id: str, body: ExternalInvestigationStatusIn, request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Lưu heartbeat/progress của DeepAgent, không gửi notification."""
    await _auth_api_key(db, request, "investigation:write")
    inv = (
        await db.execute(
            select(DfirInvestigation)
            .where(DfirInvestigation.id == _parse_inv_id_or_404(inv_id))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Investigation không tồn tại")
    if not inv.external_orchestrator:
        return {"id": str(inv.id), "status": inv.status, "accepted": False}
    if inv.external_orchestrator == "deepagent" and not inv.external_job_id:
        raise HTTPException(409, "DeepAgent job chưa được bind")
    if inv.external_job_id and body.external_job_id != inv.external_job_id:
        raise HTTPException(409, "external_job_id không khớp với job đã dispatch")
    if inv.status in ("completed", "failed"):
        return {"id": str(inv.id), "status": inv.status, "accepted": False}
    previous = inv.hermes_response or {}
    previous_phase = previous.get("phase") if isinstance(previous, dict) else None
    previous_progress = (previous.get("progress_percent", -1) or -1) if isinstance(previous, dict) else -1
    previous_step = (previous.get("current_step", -1) or -1) if isinstance(previous, dict) else -1
    current_order = _STATUS_PHASE_ORDER.get(body.phase, 1)
    previous_order = _STATUS_PHASE_ORDER.get(previous_phase, -1)
    if body.progress_percent < previous_progress or (
        current_order, body.progress_percent, body.current_step or -1
    ) < (
        previous_order, previous_progress, previous_step
    ):
        return {"id": str(inv.id), "status": inv.status, "accepted": False}
    inv.external_job_id = body.external_job_id
    inv.hermes_status = body.phase
    inv.hermes_response = {
        "phase": body.phase, "progress_percent": body.progress_percent,
        "current_step": body.current_step, "total_steps": body.total_steps,
        "message": body.message, "updated_at": datetime.now(UTC).isoformat(),
    }
    await db.commit()
    return {"id": str(inv.id), "status": inv.status, "accepted": True}


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
    if len(required_scopes) > 1:
        authorized = bool(have.intersection(required_scopes))
    else:
        authorized = have.issuperset(required_scopes)
    if not authorized:
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
        # Rows đã được claim nguyên tử trong list_pending_for_external().
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
    parsed_inv_id = _parse_inv_id_or_404(inv_id)
    idem = request.headers.get("X-Idempotency-Key")
    idem = idem.strip() if idem else None
    if not idem:
        raise HTTPException(400, "Thiếu X-Idempotency-Key")
    if len(idem) > 255:
        raise HTTPException(400, "X-Idempotency-Key vượt quá 255 ký tự")

    from app.services import dfir_investigation as inv_svc

    try:
        inv_dict = await inv_svc.submit_external_result(
            db,
            investigation_id=str(parsed_inv_id),
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
    except inv_svc.ExternalInvestigationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except inv_svc.ExternalCallbackConflict as exc:
        raise HTTPException(409, str(exc)) from exc

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
