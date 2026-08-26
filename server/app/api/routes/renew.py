"""Route renew — agent tự gia hạn client cert (mục 7.1 tài liệu gốc).

Agent chủ động gọi khi cert còn < ~70% vòng đời (server trả renew_after).
mTLS bắt buộc: identity từ X-SSL-Client-CN (nginx); cert cũ được thu hồi
qua serial từ X-SSL-Client-Serial trước khi ký cert mới.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_machine_id
from app.core.audit import append_audit
from app.core.config import settings
from app.db.models import Machine
from app.db.session import get_db
from app.services.ca import get_ca_service

router = APIRouter(prefix="/api/renew", tags=["agent"])


class RenewRequest(BaseModel):
    csr_pem: str = Field(..., description="CSR mới (PEM) — ECDSA P-256")


class RenewResponse(BaseModel):
    client_cert_pem: str
    ca_cert_pem: str | None = None
    cert_serial: str | None = None
    renew_after: datetime


@router.post("", response_model=RenewResponse)
async def renew_certificate(
    body: RenewRequest,
    db: AsyncSession = Depends(get_db),
    machine_cn: str = Depends(get_client_machine_id),
    x_ssl_client_serial: str | None = Header(default=None, alias="X-SSL-Client-Serial"),
):
    """Gia hạn cert: thu hồi cert cũ → ký CSR mới (cùng CN = machine_id)."""
    try:
        machine_id = uuid.UUID(machine_cn)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="CN không hợp lệ")

    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Máy không tồn tại")

    ca = get_ca_service()

    # Thu hồi cert cũ (serial từ nginx mTLS) — không chặn nếu CA local không hỗ trợ CRL
    if x_ssl_client_serial:
        try:
            await ca.revoke(x_ssl_client_serial)
        except Exception:  # noqa: BLE001
            pass

    # Ký CSR mới
    try:
        cert_pem = await ca.renew_cert(body.csr_pem, machine_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"CA ký cert thất bại: {exc}")

    await append_audit(
        db,
        action="cert.renew",
        actor=f"agent:{machine.id}",
        target=str(machine.id),
        ip=None,
        machine_id=machine.id,
    )
    await db.commit()

    now = datetime.now(UTC)
    return RenewResponse(
        client_cert_pem=cert_pem,
        ca_cert_pem=None,
        cert_serial=None,
        renew_after=now + timedelta(days=int(settings.client_cert_valid_days * 0.7)),
    )
