"""Chế độ máy cách ly — import file ký số từ USB (tính năng #12, Phase 3).

Hỗ trợ 2 định dạng:
1. Gói ZIP mã hóa 1-Click (multipart/form-data):
   - Agent đóng gói: inventory.json + signature.sig + public_key.pem + manifest.json
   - Mã hóa lai AES-256-GCM + RSA Server Public Key.
   - Backend giải mã bằng Server Private Key → verify chữ ký ECDSA → cập nhật hệ thống.
2. File JSON phẳng truyền thống (application/json):
   - Nhận OfflineImportRequest {payload, signature_b64, public_key_pem}.
   - Phục vụ tương thích ngược cho automation scripts.
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
from app.services.server_crypto import decrypt_offline_bundle

logger = logging.getLogger("offline_import")
router = APIRouter(prefix="/api/offline", tags=["offline"])


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_signature(payload: dict, signature_b64: str, public_key_pem: str) -> bool:
    try:
        pub = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
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
    # Lưu ý: `is_vm` KHÔNG nằm trong danh sách này — MachineSpec không có cột
    # is_vm (chỉ Machine + MachineCurrent có). is_vm được đọc trực tiếp từ
    # inner_spec ở dưới và truyền riêng vào upsert_current_and_software + set
    # trên Machine.
    keys = [
        "os_name", "os_version", "os_build", "os_arch", "os_installed_at", "activation_status",
        "cpu", "ram_gb", "disks", "gpu", "network", "logged_user", "security", "config_hash",
        "mainboard", "bios", "installed_software",
        # Phase 3: cột mới trên MachineSpec + MachineCurrent + Machine
        "public_ip",
    ]
    return {k: spec[k] for k in keys if k in spec and spec[k] is not None}


@router.post("/import", response_model=OfflineImportResponse)
async def import_offline(
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Import file máy cách ly (hỗ trợ cả gói ZIP mã hóa lẫn payload JSON ký số)."""
    content_type = request.headers.get("content-type", "").lower()
    is_decrypted = False

    if "multipart/form-data" in content_type:
        form = await request.form()
        file_item = form.get("file")
        if file_item is None or not hasattr(file_item, "read"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Thiếu file upload trong form data")

        zip_bytes = await file_item.read()
        try:
            bundle = decrypt_offline_bundle(zip_bytes)
        except ValueError as ex:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(ex))

        payload = bundle["payload"]
        signature_b64 = bundle["signature_b64"]
        public_key_pem = bundle["public_key_pem"]
        manifest = bundle.get("manifest") or {}

        # Merge metadata từ manifest nếu payload chưa có
        for field in ("machine_uuid", "hostname", "fingerprint", "org_id", "exported_at"):
            if field not in payload and field in manifest:
                payload[field] = manifest[field]

        form_org_id = form.get("org_id")
        if form_org_id:
            payload["org_id"] = str(form_org_id)

        is_decrypted = True
    else:
        try:
            json_data = await request.json()
            body = OfflineImportRequest(**json_data)
        except Exception as ex:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Dữ liệu JSON không hợp lệ: {ex}")
        payload = body.payload
        signature_b64 = body.signature_b64
        public_key_pem = body.public_key_pem
        is_decrypted = False

    # Xác thực chữ ký số ECDSA
    # Lưu ý: Nếu payload có dạng {spec: ...} hoặc phẳng (spec trực tiếp trong payload)
    # Ta verify trên đúng object payload được ký.
    if not _verify_signature(payload, signature_b64, public_key_pem):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chữ ký không hợp lệ — file có thể đã bị sửa đổi; không import",
        )

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
            id=uuid.uuid4(),
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
        # Máy BMNN — gán tag phân loại ngay tại nguồn (nếu máy cũ chưa có tag thì cũng set).
        from app.services.tags import ensure_classification

        await ensure_classification(db, machine.id, "bmnn")
    else:
        machine.last_seen_at = exported_dt
        machine.hostname = hostname or machine.hostname
        # Máy import offline (dù đã tồn tại) → đảm bảo phân loại BMNN.
        from app.services.tags import ensure_classification

        await ensure_classification(db, machine.id, "bmnn")

    # Nếu payload có bọc trong key "spec" thì lấy từ spec, nếu không thì lấy trực tiếp từ payload
    inner_spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else payload
    spec_data = _spec_from_payload(inner_spec)

    # is_vm không nằm trong spec_data (vì MachineSpec không có cột này).
    # Đọc trực tiếp từ inner_spec để set Machine + truyền vào upsert_current_and_software.
    raw_is_vm = inner_spec.get("is_vm")
    if raw_is_vm is not None:
        machine.is_vm = bool(raw_is_vm)

    # Cập nhật public_ip machine-level từ spec_data (đồng bộ với online path —
    # inventory.py cũng set machine.public_ip từ heartbeat).
    if "public_ip" in spec_data:
        machine.public_ip = spec_data["public_ip"]

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
            is_vm=raw_is_vm,
            security=spec_data.get("security"),
            installed_software=spec_data.get("installed_software"),
            public_ip=spec_data.get("public_ip"),
            collected_at=exported_dt,
            config_hash=spec_data.get("config_hash"),
        )

    await append_audit(
        db,
        action="offline.import_zip" if is_decrypted else "offline.import",
        actor=str(admin.id),
        target=str(machine.id),
        ip=request.client.host if request.client else None,
        machine_id=machine.id,
    )
    await db.commit()

    installed_apps = spec_data.get("installed_software") or []
    logger.info("Offline import %s → %s (new=%s, decrypted=%s)", machine.id, hostname, is_new, is_decrypted)

    # Lookup user hiện đang gán cho máy (nếu có) — để frontend hiển thị
    # và cho admin biết cần gán hoặc đổi user hay không.
    assigned_user = (
        await db.execute(select(User).where(User.id == machine.assigned_user_id))
    ).scalar_one_or_none() if machine.assigned_user_id else None

    return OfflineImportResponse(
        machine_id=machine.id,
        hostname=hostname,
        is_new=is_new,
        verified=True,
        decrypted=is_decrypted,
        apps_count=len(installed_apps) if installed_apps else None,
        collected_at=exported_dt,
        assigned_user_id=machine.assigned_user_id,
        assigned_user_name=assigned_user.full_name if assigned_user else None,
        assigned_user_email=assigned_user.email if assigned_user else None,
        org_id=machine.org_id,
    )