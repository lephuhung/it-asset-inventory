"""Chế độ máy cách ly — import file ký số từ USB (tính năng #12, Phase 3).

Agent ở mạng không ra internet ghi inventory ra file JSON ký ECDSA (private key
client cert); cán bộ copy USB → import vào đây. Server verify chữ ký (SHA-256 +
ECDSA) trước khi ghi dữ liệu — file sửa đổi sẽ bị từ chối.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, visible_org_ids
from app.core.audit import append_audit
from app.db.models import Machine, MachineSpec, User
from app.db.session import get_db
from app.schemas import OfflineImportRequest, OfflineImportResponse
from app.services.fingerprint import compute_weighted_id, is_same_machine
from app.services.inventory_normalize import derive_os_fields
from app.services.inventory_sync import upsert_current_and_software

logger = logging.getLogger("offline_import")
router = APIRouter(prefix="/api/offline", tags=["offline"])


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _verify_signature(payload: dict, signature_b64: str, public_key_pem: str) -> bool:
    try:
        pub = serialization.load_pem_public_key(public_key_pem.encode())
        if not isinstance(pub, ec.EllipticCurvePublicKey):
            return False
        digest = hashlib.sha256(_canonical_json(payload)).digest()
        pub.verify(base64.b64decode(signature_b64), digest, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _spec_from_payload(spec: dict | None) -> dict:
    if not spec:
        return {}
    keys = [
        "os_name", "os_version", "os_build", "os_arch", "os_installed_at", "activation_status",
        "cpu", "ram_gb", "disks", "gpu", "network", "logged_user", "security", "config_hash",
        "mainboard", "bios", "installed_software",
    ]
    return {k: spec[k] for k in keys if k in spec and spec[k] is not None}


@router.post("/import", response_model=OfflineImportResponse)
async def import_offline(
    body: OfflineImportRequest,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Import 1 file máy cách ly (payload ký số)."""
    if not _verify_signature(body.payload, body.signature_b64, body.public_key_pem):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chữ ký không hợp lệ — file có thể đã bị sửa đổi; không import",
        )

    payload = body.payload
    machine_uuid = str(payload.get("machine_uuid") or "").strip()
    hostname = payload.get("hostname")
    fp_dict = payload.get("fingerprint") or {}
    if not machine_uuid and not fp_dict:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Thiếu machine_uuid/fingerprint")

    visible = await visible_org_ids(db, admin)
    org_id = payload.get("org_id")
    try:
        org_uuid = uuid.UUID(str(org_id)) if org_id else None
    except ValueError:
        org_uuid = None
    if org_uuid is None or str(org_uuid) not in visible:
        org_uuid = admin.org_id  # mặc định org của admin khi không được chỉ định

    weighted = compute_weighted_id(fp_dict)
    machine = None
    if machine_uuid:
        machine = (
            await db.execute(
                select(Machine).where(Machine.org_id == org_uuid, Machine.machine_uuid == machine_uuid)
            )
        ).scalar_one_or_none()
    if machine is None and fp_dict:
        weighted = compute_weighted_id(fp_dict)
        machine = (
            await db.execute(
                select(Machine).where(Machine.org_id == org_uuid, Machine.machine_uuid == weighted)
            )
        ).scalar_one_or_none()
        if machine is None:
            candidates = (await db.execute(select(Machine).where(Machine.org_id == org_uuid))).scalars().all()
            for m in candidates:
                if is_same_machine(fp_dict, m.fingerprint or {}):
                    machine = m
                    break

    now = datetime.now(UTC)
    exported_dt = now
    raw_exported = payload.get("exported_at")
    if raw_exported:
        try:
            exported_dt = datetime.fromisoformat(str(raw_exported))
        except ValueError:
            exported_dt = now

    is_new = machine is None
    if is_new:
        machine = Machine(
            org_id=org_uuid,
            machine_uuid=weighted,
            hostname=hostname,
            fingerprint=fp_dict,
            status="offline",  # máy cách ly không online qua mạng
            enrolled_at=now,
            last_seen_at=exported_dt,
        )
        db.add(machine)
        await db.flush()
    else:
        machine.last_seen_at = exported_dt
        machine.hostname = hostname or machine.hostname

    spec_data = _spec_from_payload(payload.get("spec") or {})
    if spec_data:
        # Chuẩn hóa OS phía server (agent/offline file không cần đổi)
        product, release, family = derive_os_fields(
            spec_data.get("os_name"), spec_data.get("os_version"), spec_data.get("os_build")
        )
        db.add(
            MachineSpec(
                machine_id=machine.id,
                os_product=product,
                os_release=release,
                os_family=family,
                **spec_data,
                collected_at=exported_dt,
            )
        )
        # Đồng bộ bảng "hiện tại" cùng transaction
        await upsert_current_and_software(
            db,
            machine.id,
            os_name=spec_data.get("os_name"),
            os_version=spec_data.get("os_version"),
            os_build=spec_data.get("os_build"),
            os_arch=spec_data.get("os_arch"),
            os_installed_at=spec_data.get("os_installed_at"),
            activation_status=spec_data.get("activation_status"),
            cpu=spec_data.get("cpu"),
            ram_gb=spec_data.get("ram_gb"),
            disks=spec_data.get("disks"),
            gpu=spec_data.get("gpu"),
            mainboard=spec_data.get("mainboard"),
            bios=spec_data.get("bios"),
            network=spec_data.get("network"),
            logged_user=spec_data.get("logged_user"),
            security=spec_data.get("security"),
            installed_software=spec_data.get("installed_software"),
            collected_at=exported_dt,
            config_hash=spec_data.get("config_hash"),
        )

    await append_audit(
        db,
        action="offline.import",
        actor=str(admin.id),
        target=str(machine.id),
        ip=request.client.host if request.client else None,
        machine_id=machine.id,
    )
    await db.commit()
    logger.info("Offline import %s → %s (new=%s)", machine.id, hostname, is_new)
    return OfflineImportResponse(machine_id=machine.id, hostname=hostname, is_new=is_new, verified=True)