"""Routes quản trị Velociraptor (DFIR) — chỉ Super Admin.

Endpoints:
  GET    /api/admin/velociraptor/config            — đọc cấu hình (masked token)
  PUT    /api/admin/velociraptor/config            — cập nhật URL + token + allowlist
  POST   /api/admin/velociraptor/test             — test kết nối (không lưu DB)
  POST   /api/admin/velociraptor/sync             — trigger sync hostname thủ công
  GET    /api/admin/velociraptor/links            — list mapping machine ↔ client_id
  POST   /api/admin/velociraptor/hunt             — tạo hunt/collect (validate allowlist)
  GET    /api/admin/velociraptor/hunts            — list lịch sử hunt/collect
  GET    /api/admin/velociraptor/hunt/{hunt_id}   — lấy trạng thái hunt từ Velociraptor

Không expose token thật ra ngoài — luôn mask.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_super_admin
from app.core.audit import append_audit
from app.core.config import settings
from app.core.security import decrypt_aes_gcm, encrypt_aes_gcm
from app.db.models import (
    DfirAlert,
    DfirHunt,
    DfirSchedule,
    Machine,
    Organization,
    User,
    VelociraptorConfig,
    VelociraptorLink,
)
from app.db.session import get_db
from app.schemas import (
    DfirAlertOut,
    DfirHuntCreate,
    DfirHuntOut,
    DfirScheduleCreate,
    DfirScheduleOut,
    DfirScheduleUpdate,
    VelociraptorConfigOut,
    VelociraptorConfigUpdate,
    VelociraptorClientFlowOut,
    VelociraptorClientMetadataOut,
    VelociraptorLinkEnriched,
    VelociraptorLinkOut,
    VelociraptorTestConnectionOut,
    VelociraptorTop10CollectOut,
    VelociraptorTop10Out,
)
from app.services.velociraptor import (
    VelociraptorClient,
    VelociraptorError,
    inspect_client_cert,
    parse_client_config_yaml,
)

logger = logging.getLogger("api.velociraptor")

router = APIRouter(prefix="/api/admin/velociraptor", tags=["velociraptor"])


@router.post("/config/api-client/upload", response_model=VelociraptorConfigOut)
async def upload_api_client_config(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Nhận `velociraptor config api_client` YAML, validate rồi mã hoá trong DB."""
    if not file.filename or not file.filename.lower().endswith((".yaml", ".yml")):
        raise HTTPException(422, "Chỉ chấp nhận file YAML api_client")
    content = await file.read()
    if not content or len(content) > 256_000:
        raise HTTPException(422, "api_client YAML phải có kích thước từ 1 đến 256KB")
    try:
        yaml_content = content.decode("utf-8")
        parsed = parse_client_config_yaml(yaml_content)
        cert_info = inspect_client_cert(parsed["client_cert"])
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(422, f"api_client YAML không hợp lệ: {exc}") from exc
    cfg = await _ensure_config(db)
    cfg.client_config_encrypted = encrypt_aes_gcm(yaml_content)
    cfg.client_cert_info = cert_info
    cfg.updated_at = datetime.now(UTC)
    cfg.updated_by = admin.id
    await db.commit()
    await append_audit(db, action="velociraptor.api_client.upload", actor=str(admin.id), target="velociraptor_config:1")
    await db.commit()
    return _config_to_out(cfg)


# ── Helpers ─────────────────────────────────────────────────────


async def _get_config(db: AsyncSession) -> VelociraptorConfig | None:
    return (
        await db.execute(select(VelociraptorConfig).where(VelociraptorConfig.id == 1))
    ).scalar_one_or_none()


async def _ensure_config(db: AsyncSession) -> VelociraptorConfig:
    """�ảm bảo có row cấu hình (id=1) — tạo mặc định nếu chưa có."""
    cfg = await _get_config(db)
    if cfg is None:
        cfg = VelociraptorConfig(
            id=1,
            enabled=False,
            allowlist=list(settings.velociraptor_default_allowlist),
        )
        db.add(cfg)
        await db.flush()
    return cfg


def _config_to_out(cfg: VelociraptorConfig | None) -> VelociraptorConfigOut:
    """Convert DB row → response (mask credentials, chỉ trả boolean + cert metadata)."""
    if cfg is None:
        return VelociraptorConfigOut(
            enabled=False,
            server_url=settings.velociraptor_default_url or None,
            client_config_set=False,
            client_cert_info=None,
            basic_auth_set=False,
            api_token_set=False,
            allowlist=list(settings.velociraptor_default_allowlist),
            defaults_server_url=settings.velociraptor_default_url or None,
            defaults_allowlist=list(settings.velociraptor_default_allowlist),
        )
    # mTLS set?
    mtls_ok = False
    if cfg.client_config_encrypted:
        try:
            decrypt_aes_gcm(cfg.client_config_encrypted)
            mtls_ok = True
        except Exception:  # noqa: BLE001
            mtls_ok = False
    # HTTP Basic set?
    basic_ok = False
    if cfg.basic_auth_encrypted:
        try:
            decrypt_aes_gcm(cfg.basic_auth_encrypted)
            basic_ok = True
        except Exception:  # noqa: BLE001
            basic_ok = False
    # Legacy Bearer?
    token_ok = False
    if cfg.api_token_encrypted:
        try:
            decrypt_aes_gcm(cfg.api_token_encrypted)
            token_ok = True
        except Exception:  # noqa: BLE001
            token_ok = False
    return VelociraptorConfigOut(
        enabled=cfg.enabled,
        server_url=cfg.server_url,
        client_config_set=mtls_ok,
        client_cert_info=cfg.client_cert_info,
        basic_auth_set=basic_ok,
        api_token_set=token_ok,
        allowlist=list(cfg.allowlist or []),
        last_sync_at=cfg.last_sync_at,
        last_sync_error=cfg.last_sync_error,
        last_sync_linked=cfg.last_sync_linked,
        last_sync_total=cfg.last_sync_total,
        updated_at=cfg.updated_at,
        updated_by=cfg.updated_by,
        defaults_server_url=settings.velociraptor_default_url or None,
        defaults_allowlist=list(settings.velociraptor_default_allowlist),
    )


async def _build_velociraptor_client(
    db: AsyncSession,
) -> tuple[VelociraptorClient, VelociraptorConfig] | None:
    """Dựng VelociraptorClient từ cấu hình DB.

    Auth: mTLS (client_config_encrypted — Velociraptor-native, cần authenticator=Certs)
    hoặc HTTP Basic (username/password lưu encrypted trong `basic_auth_encrypted`).
    Các thao tác VQL dùng gRPC/mTLS tới ``api_connection_string`` trong YAML.
    """
    from app.core.security import encrypt_aes_gcm as _enc  # noqa: F401 — keep import
    cfg = await _get_config(db)
    if cfg is None or not cfg.enabled or not cfg.server_url:
        return None

    common_kwargs: dict[str, Any] = {
        "timeout": settings.velociraptor_api_timeout_seconds,
    }

    # 1. mTLS (Velociraptor-native) — cần authenticator.type: Certs phía server
    if cfg.client_config_encrypted:
        try:
            yaml_content = decrypt_aes_gcm(cfg.client_config_encrypted)
            parsed = parse_client_config_yaml(yaml_content)
        except Exception as e:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Không giải mã / parse client_config YAML: {e}",
            ) from e
        client = VelociraptorClient(
            cfg.server_url,
            client_cert_pem=parsed["client_cert"],
            client_key_pem=parsed["client_private_key"],
            ca_cert_pem=parsed["ca_cert"],
            api_connection_string=parsed["api_connection_string"],
            **common_kwargs,
        )
        return client, cfg

    # 2. HTTP Basic (Velociraptor default authenticator)
    if cfg.basic_auth_encrypted:
        try:
            creds_json = decrypt_aes_gcm(cfg.basic_auth_encrypted)
            import json as _json
            creds = _json.loads(creds_json)
            username = creds["username"]
            password = creds["password"]
        except Exception as e:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Không giải mã credentials: {e}",
            ) from e
        client = VelociraptorClient(
            cfg.server_url,
            username=username,
            password=password,
            **common_kwargs,
        )
        return client, cfg

    # 3. Legacy: API token (Bearer — đã bị thay thế bởi Basic)
    if cfg.api_token_encrypted:
        try:
            token = decrypt_aes_gcm(cfg.api_token_encrypted)
        except Exception as e:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Không giải mã API token: {e}",
            ) from e
        client = VelociraptorClient(
            cfg.server_url,
            api_token=token,
            **common_kwargs,
        )
        return client, cfg

    return None  # chưa cấu hình credentials


def _validate_artifact(artifact: str, allowlist: list[str]) -> None:
    """Raise 403 nếu artifact không nằm trong allowlist (chống lạm quyền)."""
    if artifact not in allowlist:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=(
                f"Artifact '{artifact}' không nằm trong allowlist. "
                "Cập nhật allowlist ở /dfir/settings (Super Admin) trư�c khi chạy."
            ),
        )


# ── Config endpoints ───────────────────────────────────────────


@router.get("/config", response_model=VelociraptorConfigOut)
async def get_velociraptor_config(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    """Cấu hình Velociraptor Server hiệu lực (mask token)."""
    cfg = await _get_config(db)
    return _config_to_out(cfg)


@router.put("/config", response_model=VelociraptorConfigOut)
async def update_velociraptor_config(
    body: VelociraptorConfigUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Cập nhật cấu hình Velociraptor Server. Token plaintext được mã hoá AES-256-GCM."""
    cfg = await _ensure_config(db)
    changes: dict[str, Any] = {}

    if body.enabled is not None:
        cfg.enabled = body.enabled
        changes["enabled"] = body.enabled
    if body.server_url is not None:
        url = body.server_url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="server_url phải bắt đầu bằng http:// hoặc https://",
            )
        cfg.server_url = url or None
        changes["server_url"] = cfg.server_url
    if body.client_config is not None:
        # null/empty string = xoá; non-empty = parse + mã hoá
        if body.client_config.strip() == "":
            cfg.client_config_encrypted = None
            cfg.client_cert_info = None
            changes["client_config"] = "cleared"
        else:
            try:
                parsed = parse_client_config_yaml(body.client_config)
            except ValueError as e:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"client_config YAML không hợp lệ: {e}",
                ) from e
            try:
                cert_info = inspect_client_cert(parsed["client_cert"])
            except ValueError as e:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"client_cert trong YAML không phải PEM hợp lệ: {e}",
                ) from e
            cfg.client_config_encrypted = encrypt_aes_gcm(body.client_config)
            cfg.client_cert_info = cert_info
            changes["client_config"] = "set"
            changes["client_cert_info"] = cert_info["subject"]
    # HTTP Basic — username + password (Velociraptor default authenticator)
    if body.username is not None or body.password is not None:
        username_in = (body.username or "").strip()
        password_in = (body.password or "").strip()
        if password_in == "" and username_in == "":
            cfg.basic_auth_encrypted = None
            changes["basic_auth"] = "cleared"
        elif password_in == "" and username_in:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="username + password phải đi cùng nhau (hoặc cả 2 rỗng để xoá).",
            )
        else:
            import json as _json
            creds = _json.dumps({"username": username_in, "password": password_in})
            cfg.basic_auth_encrypted = encrypt_aes_gcm(creds)
            changes["basic_auth"] = "set"
            changes["basic_auth_user"] = username_in
    # Legacy: Bearer API token
    if body.api_token is not None:
        if body.api_token.strip() == "":
            cfg.api_token_encrypted = None
            changes["api_token"] = "cleared"
        else:
            cfg.api_token_encrypted = encrypt_aes_gcm(body.api_token.strip())
            changes["api_token"] = "set"
    if body.allowlist is not None:
        # Cho phép cập nhật allowlist; service tự loại bỏ duplicate + strip whitespace
        clean = sorted({a.strip() for a in body.allowlist if a and a.strip()})
        cfg.allowlist = clean
        changes["allowlist"] = clean

    cfg.updated_at = datetime.now(UTC)
    cfg.updated_by = admin.id
    await append_audit(
        db,
        action="velociraptor.config.update",
        actor=str(admin.id),
        target="1",
    )
    await db.commit()
    logger.info("Velociraptor config updated by %s: %s", admin.email, list(changes.keys()))
    return _config_to_out(cfg)


@router.post("/test", response_model=VelociraptorTestConnectionOut)
async def test_velociraptor_connection(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    """Test kết nối gRPC/mTLS tới Velociraptor Server đã lưu trong DB."""
    built = await _build_velociraptor_client(db)
    if built is None:
        cfg = await _get_config(db)
        if cfg is None or not cfg.enabled:
            error = "Velociraptor chưa được bật"
        elif not cfg.server_url:
            error = "Chưa nhập Velociraptor Server URL"
        else:
            error = "Chưa tải api_client.yaml cho kết nối gRPC/mTLS"
        return VelociraptorTestConnectionOut(
            ok=False,
            error=error,
        )
    client, cfg = built
    async with client as velo:
        result = await velo.test_connection()
    return VelociraptorTestConnectionOut(
        ok=result.get("ok", False),
        error=result.get("error"),
        client_count_sampled=result.get("client_count_sampled"),
        server_url=cfg.server_url,
    )


@router.post("/sync")
async def trigger_velociraptor_sync(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Trigger sync hostname ↔ client_id ngay lập tức (admin không muốn đợi 5 phút).

    Background sync đã TẮT — endpoint này là cách DUY NHẤT để populate veloLink
    table ngoài việc mỗi page machine tự query on-demand.
    """
    from app.services.velociraptor_sync import sync_velociraptor_links

    result = await sync_velociraptor_links()
    await append_audit(
        db,
        action="velociraptor.sync.manual",
        actor=str(admin.id),
        target=str(result)[:200],
    )
    await db.commit()
    return result


@router.get("/lookup")
async def lookup_velociraptor_client(
    hostname: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """On-demand lookup hostname ↔ Velociraptor client_id (không qua DB cache).

    Gọi Velociraptor Server SearchClients API với `query={hostname}` và trả về
    client_id đầu tiên match (nếu có). Dùng cho trang máy khi admin mở —
    không cần background sync trước.

    Response: {"matched": bool, "client_id": str|None, "hostname": str,
               "os_info": dict|None, "raw_count": int}
    """
    from app.services.velociraptor import VelociraptorClient, VelociraptorError

    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Velociraptor chưa cấu hình",
        )
    client, _ = built
    try:
        vql = "SELECT client_id, os_info FROM clients() WHERE os_info.hostname =~ Hostname LIMIT 50"
        async with client as velo:
            items = await velo._vql_query(vql, env={"Hostname": hostname})
    except VelociraptorError as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Velociraptor API lỗi: {e}",
        ) from e

    if not items:
        return {
            "matched": False,
            "client_id": None,
            "hostname": hostname,
            "os_info": None,
            "raw_count": 0,
        }

    # Exact hostname match (Velociraptor normalize lowercase)
    target = hostname.strip().lower()
    matched = None
    for c in items:
        os_info = c.get("os_info") or {}
        h = (os_info.get("hostname") or "").strip().lower()
        # Exact match OR match trước dấu chấm (FQDN)
        if h == target or h.split(".", 1)[0] == target:
            matched = c
            break

    if matched is None:
        # Fallback: lấy client đầu tiên có hostname chứa target (substring)
        for c in items:
            os_info = c.get("os_info") or {}
            h = (os_info.get("hostname") or "").strip().lower()
            if target in h:
                matched = c
                break

    if matched is None:
        return {
            "matched": False,
            "client_id": None,
            "hostname": hostname,
            "os_info": None,
            "raw_count": len(items),
        }

    return {
        "matched": True,
        "client_id": matched["client_id"],
        "hostname": matched.get("os_info", {}).get("hostname"),
        "os_info": matched.get("os_info"),
        "raw_count": len(items),
    }


@router.get("/status")
async def velociraptor_status(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Trạng thái Velociraptor Server (reachable + client count).

    Dùng để hiển thị badge realtime trên portal. Không cache — mỗi call
    ping Velociraptor Server.
    """
    from app.services.velociraptor import VelociraptorClient, VelociraptorError

    built = await _build_velociraptor_client(db)
    if built is None:
        return {"reachable": False, "reason": "Velociraptor chưa cấu hình", "client_count": 0}

    client, cfg = built
    try:
        async with client as velo:
            items = await velo._vql_query("SELECT client_id FROM clients() LIMIT 1")
            return {
                "reachable": True,
                "server_url": cfg.server_url,
                "client_count_sampled": len(items),
                "checked_at": datetime.now(UTC).isoformat(),
            }
    except VelociraptorError as e:
        return {
            "reachable": False,
            "reason": str(e),
            "server_url": cfg.server_url,
            "checked_at": datetime.now(UTC).isoformat(),
        }


@router.post("/alerts/scan")
async def scan_velociraptor_alerts_now(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Manual trigger alert scan (on-demand).

    Background scan đã TẮT — endpoint này là cách DUY NHẤT để detect
    artifact sensitive (vd Windows.Persistence.*) xuất hiện trên Velociraptor.
    Admin trigger sau khi chạy hunt/collect xong.
    """
    from app.services.monitor import _scan_sensitive_flows

    await _scan_sensitive_flows()
    # Trả về danh sách alerts mới nhất
    from sqlalchemy import select as sa_select, desc
    from app.db.models import DfirAlert

    alerts = (
        await db.execute(
            sa_select(DfirAlert).order_by(desc(DfirAlert.created_at)).limit(20)
        )
    ).scalars().all()
    await append_audit(
        db,
        action="velociraptor.alerts.scan",
        actor=str(admin.id),
    )
    await db.commit()
    return {
        "scanned": True,
        "alerts_count": len(alerts),
        "latest_alerts": [
            {
                "id": str(a.id),
                "artifact_pattern": a.artifact_pattern,
                "severity": a.severity,
                "flow_id": a.flow_id,
                "message": a.message,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts[:5]
        ],
    }


# ── Links endpoints ────────────────────────────────────────────


@router.get("/links", response_model=list[VelociraptorLinkEnriched])
async def list_velociraptor_links(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """List mapping machine ↔ Velociraptor client_id (kèm thông tin máy)."""
    rows = (
        await db.execute(
            select(
                VelociraptorLink,
                Machine.hostname,
                Machine.status,
                Machine.last_seen_at,
                Organization.name,
            )
            .join(Machine, Machine.id == VelociraptorLink.machine_id)
            .join(Organization, Organization.id == Machine.org_id)
            .order_by(VelociraptorLink.synced_at.desc())
        )
    ).all()
    out: list[VelociraptorLinkEnriched] = []
    for link, m_hostname, m_status, m_last_seen, org_name in rows:
        # model_validate() cần dict hoặc model instance — convert SQLAlchemy
        # ORM object thành dict via model_dump (Pydantic v2) thay vì model_validate.
        base = VelociraptorLinkOut.model_validate(link).model_dump()
        base.update(
            machine_hostname=m_hostname,
            machine_status=m_status,
            machine_org_name=org_name,
            machine_last_seen_at=m_last_seen,
        )
        # Filter fields không có trong schema enriched (vd id trùng)
        out.append(VelociraptorLinkEnriched(**base))
    return out


# ── Per-client data endpoints (cho portal machine detail page) ───────


@router.get("/clients/{client_id}/flows", response_model=list[VelociraptorClientFlowOut])
async def list_client_flows(
    client_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """List flows (hunts/collections/interrogations) cho 1 Velociraptor client.

    Pull live data từ Velociraptor Server — không cache (Velociraptor đã làm điều đó).
    """
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chưa cấu hình Velociraptor",
        )
    client, _ = built
    async with client as velo:
        try:
            flows = await velo.list_client_flows(client_id, limit=limit)
        except VelociraptorError as e:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=f"Velociraptor API lỗi: {e}",
            ) from e
    return [VelociraptorClientFlowOut(**f) for f in flows]


@router.get("/clients/{client_id}/metadata", response_model=VelociraptorClientMetadataOut)
async def get_client_metadata(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Lấy metadata hiện tại của 1 Velociraptor client (hostname, OS, last seen, IP).

    Pull live từ Velociraptor Server. VelociraptorConfig (DB) chỉ có metadata lúc
    sync gần nhất (5 phút/lần) — endpoint này trả realtime.
    """
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chưa cấu hình Velociraptor",
        )
    client, _ = built
    async with client as velo:
        try:
            meta = await velo.get_client_metadata(client_id)
        except VelociraptorError as e:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=f"Velociraptor API lỗi: {e}",
            ) from e
    return VelociraptorClientMetadataOut(**meta)


@router.get("/clients/{client_id}/top10", response_model=VelociraptorTop10Out)
async def get_client_top10_events(
    client_id: str,
    top_n: int = 10,
    rows: int = 100,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Top N sự kiện / log gần nhất cho từng artifact DFIR trên 1 client.

    Chuyển thể từ script "Velociraptor Top 10 DFIR Events Extractor":
      - Windows.Forensics.Prefetch — Top N binary thực thi gần nhất
      - Windows.Network.Netstat      — Top N kết nối / cổng đang mở
      - Windows.System.Pslist        — Top N tiến trình hệ thống
      - flows                        — Top N hoạt động điều tra gần nhất

    `top_n` = số sự kiện hiển thị mỗi artifact (mặc định 10; Admin có thể
    chọn 20/50/100 khi điều tra). `rows` = số dòng tối đa đọc từ Velociraptor
    (luôn >= top_n).

    Read-only: tái sử dụng flow FINISHED gần nhất đã chạy artifact (không
    collect mới). Artifact chưa có dữ liệu → source="missing" — gọi
    ``POST /clients/{client_id}/top10/collect`` trước, rồi poll lại endpoint này.
    """
    from app.services.velociraptor_top10 import extract_top10

    top_n = max(1, min(top_n, 200))
    rows = max(top_n, min(rows, 1000))
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chưa cấu hình Velociraptor",
        )
    client, _ = built
    async with client as velo:
        try:
            data = await extract_top10(
                velo, client_id, collect_missing=False, top_n=top_n, rows=rows
            )
        except VelociraptorError as e:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=f"Velociraptor API lỗi: {e}",
            ) from e
    return data


@router.post(
    "/clients/{client_id}/top10/collect",
    response_model=VelociraptorTop10CollectOut,
)
async def collect_client_top10_events(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Kick-off collect các artifact Top10 chưa có dữ liệu (không chờ xong).

    Chỉ collect artifact trong allowlist — artifact ngoài allowlist trả về
    status="not_allowed" (không chạy, không 403 toàn bộ request) để admin
    vẫn nhận được dữ liệu các artifact được phép. Portal poll
    ``GET /clients/{client_id}/top10`` tới khi flow FINISHED rồi đọc Top N.
    """
    from app.services.velociraptor_top10 import collect_missing_top10

    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chưa cấu hình Velociraptor",
        )
    client, cfg = built
    allowlist = list(cfg.allowlist or [])
    async with client as velo:
        try:
            data = await collect_missing_top10(velo, client_id, allowlist)
        except VelociraptorError as e:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=f"Velociraptor API lỗi: {e}",
            ) from e
    return data


# ── Hunt / Collect endpoints ───────────────────────────────────


@router.post("/hunt", response_model=DfirHuntOut, status_code=status.HTTP_201_CREATED)
async def create_velociraptor_hunt(
    body: DfirHuntCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """Tạo hunt (nhiều client) hoặc collect artifact (1 client).

    - scope=all: hunt trên TẤT CẢ client đã có link Velociraptor (kể cả client
      cũ ngoài inventory — vì Velociraptor trả về list clients). Cảnh báo nếu
      fleet lớn.
    - scope=single: collect artifact trên 1 client (yêu cầu machine_id).

    Artifact phải nằm trong `allowlist` (403 nếu không). Kết quả lưu trên
    Velociraptor Server → portal deep-link sang GUI.
    """
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Velociraptor chưa cấu hình (enabled=False hoặc thiếu URL/token)",
        )
    client, cfg = built

    allowlist = list(cfg.allowlist or [])
    _validate_artifact(body.artifact, allowlist)

    if body.scope == "single":
        if body.machine_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="scope=single yêu cầu machine_id",
            )
        machine = (
            await db.execute(select(Machine).where(Machine.id == body.machine_id))
        ).scalar_one_or_none()
        if machine is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy máy")
        link = (
            await db.execute(
                select(VelociraptorLink).where(VelociraptorLink.machine_id == body.machine_id)
            )
        ).scalar_one_or_none()
        if link is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Máy này chưa được link với Velociraptor — chờ background sync (≤5 phút)",
            )
    elif body.scope == "multi":
        if not body.machine_ids or len(body.machine_ids) == 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="scope=multi yêu cầu machine_ids (ít nhất 1)",
            )
        # Lấy VelociraptorLink cho từng machine_id
        links = (
            await db.execute(
                select(VelociraptorLink).where(VelociraptorLink.machine_id.in_(body.machine_ids))
            )
        ).scalars().all()
        if not links:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Không có máy nào trong danh sách đã link Velociraptor",
            )
        missing = set(body.machine_ids) - {l.machine_id for l in links}
        if missing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"{len(missing)} máy chưa link Velociraptor (chờ sync ≤5p)",
            )
        link = None  # signal multi scope

    # Build audit log trước (khôi phục sau nếu Velociraptor lỗi)
    notes = body.notes or ""
    await append_audit(
        db,
        action="dfir.hunt.create",
        actor=str(admin.id),
        target=body.artifact,
    )

    dfir = DfirHunt(
        hunt_id=None,
        artifact=body.artifact,
        scope=body.scope,
        machine_id=body.machine_id,
        requested_by=admin.id,
        status="pending",
        velociraptor_url=None,
        notes=notes,
    )
    db.add(dfir)

    client_count: int | None = None
    try:
        async with client as velo:
            if body.scope == "single":
                flow_id = await velo.collect_artifact(
                    link.client_id, [body.artifact]
                )
                client_count = 1
                dfir.hunt_id = flow_id or None
                from urllib.parse import quote
                dfir.velociraptor_url = (
                    f"{cfg.server_url.rstrip('/')}/#/host/{quote(link.client_id)}"
                )
            elif body.scope == "multi":
                # Run collect_artifact cho từng client (parallel qua asyncio.gather)
                import asyncio as _asyncio

                tasks = [
                    velo.collect_artifact(l.client_id, [body.artifact])
                    for l in links
                ]
                flow_ids = await _asyncio.gather(*tasks, return_exceptions=True)
                # Count successful (không phải exception)
                successful = [fid for fid in flow_ids if isinstance(fid, str) and fid]
                client_count = len(successful)
                # Lưu hunt_id là flow_id đầu tiên (để deep-link)
                if successful:
                    dfir.hunt_id = successful[0]
                    from urllib.parse import quote

                    dfir.velociraptor_url = (
                        f"{cfg.server_url.rstrip('/')}/#/host/{quote(links[0].client_id)}"
                    )
            else:
                # Hunt trên toàn bộ client Velociraptor trả về (không giới hạn theo
                # inventory — Velociraptor là nguồn gốc). Admin muốn giới hạn theo
                # inventory có thể chạy scope=single lặp lại, hoặc filter query.
                # scope=all: collect_artifact per client (parallel) — không dùng
                # Velociraptor hunt (cần artifact definition + org config phức tạp).
                clients = await velo.get_all_clients()
                client_ids = [c.get("client_id") for c in clients if c.get("client_id")]
                client_count = len(client_ids)
                if client_count == 0:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail="Velociraptor không trả về client nào — kiểm tra agent đã enroll chưa",
                    )
                # Run collect_artifact trên từng client (parallel)
                tasks = [velo.collect_artifact(cid, [body.artifact]) for cid in client_ids]
                flow_ids = await asyncio.gather(*tasks, return_exceptions=True)
                successful = [fid for fid in flow_ids if isinstance(fid, str) and fid]
                client_count = len(successful)
                if successful:
                    dfir.hunt_id = successful[0]  # flow_id đầu tiên
                    from urllib.parse import quote

                    dfir.velociraptor_url = (
                        f"{cfg.server_url.rstrip('/')}/#/host/{quote(client_ids[0])}"
                    )

        dfir.status = "completed"
        await db.commit()
        await db.refresh(dfir)
        logger.info(
            "DFIR %s: artifact=%s, scope=%s, clients=%d, by=%s",
            dfir.hunt_id or dfir.id,
            body.artifact,
            body.scope,
            client_count or 0,
            admin.email,
        )
        return DfirHuntOut(
            id=dfir.id,
            hunt_id=dfir.hunt_id,
            artifact=dfir.artifact,
            scope=dfir.scope,
            machine_id=dfir.machine_id,
            requested_by=dfir.requested_by,
            status=dfir.status,
            velociraptor_url=dfir.velociraptor_url,
            notes=dfir.notes,
            error=dfir.error,
            created_at=dfir.created_at,
            client_count=client_count,
        )
    except VelociraptorError as e:
        dfir.status = "error"
        dfir.error = str(e)
        await db.commit()
        await db.refresh(dfir)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Velociraptor API lỗi: {e}",
        ) from e
    except HTTPException:
        # Đã raise — set error message cho DfirHunt log
        dfir.status = "error"
        await db.commit()
        raise


@router.get("/hunts", response_model=list[DfirHuntOut])
async def list_velociraptor_hunts(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Lịch sử hunt/collect đã chạy (audit log)."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = (
        await db.execute(
            select(DfirHunt).order_by(DfirHunt.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return [
        DfirHuntOut(
            id=h.id,
            hunt_id=h.hunt_id,
            artifact=h.artifact,
            scope=h.scope,
            machine_id=h.machine_id,
            requested_by=h.requested_by,
            status=h.status,
            velociraptor_url=h.velociraptor_url,
            notes=h.notes,
            error=h.error,
            created_at=h.created_at,
            client_count=None,
        )
        for h in rows
    ]


@router.get("/hunt/{hunt_id}")
async def get_velociraptor_hunt_status(
    hunt_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Lấy trạng thái hunt/flow từ Velociraptor Server (live).

    Trả thêm thông tin từ DB (ai request, khi nào) để admin thấy context.
    """
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Velociraptor chưa cấu hình",
        )
    client, cfg = built

    # Tìm trong DB trước (để biết audit context)
    db_record = (
        await db.execute(select(DfirHunt).where(DfirHunt.hunt_id == hunt_id))
    ).scalar_one_or_none()

    try:
        async with client as velo:
            try:
                status_data = await velo.get_hunt_status(hunt_id)
            except VelociraptorError:
                # Có thể là flow_id (collect_artifact), không phải hunt → thử /Hunt/{id} metadata
                status_data = await velo.get_hunt(hunt_id)
    except VelociraptorError as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Velociraptor API lỗi: {e}",
        ) from e

    return {
        "hunt_id": hunt_id,
        "velociraptor_status": status_data,
        "db_record": (
            {
                "id": str(db_record.id),
                "artifact": db_record.artifact,
                "scope": db_record.scope,
                "machine_id": str(db_record.machine_id) if db_record.machine_id else None,
                "requested_by": str(db_record.requested_by),
                "status": db_record.status,
                "created_at": db_record.created_at.isoformat(),
                "notes": db_record.notes,
                "error": db_record.error,
            }
            if db_record
            else None
        ),
        "velociraptor_url": (
            f"{cfg.server_url.rstrip('/')}/#/hunts/{uuid.UUID(hunt_id)}"
            if db_record and db_record.scope == "all"
            else f"{cfg.server_url.rstrip('/')}/#/collected/{hunt_id}"
        ),
    }


# ── Schedule endpoints ────────────────────────────────────────


@router.get("/schedules", response_model=list[DfirScheduleOut])
async def list_dfir_schedules(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """List scheduled hunts (cron-like, interval-based)."""
    from sqlalchemy import select as sa_select
    from app.db.models import DfirSchedule

    schedules = (
        await db.execute(
            sa_select(DfirSchedule).order_by(DfirSchedule.created_at.desc())
        )
    ).scalars().all()
    return [DfirScheduleOut.model_validate(s) for s in schedules]


@router.post("/schedules", response_model=DfirScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_dfir_schedule(
    body: DfirScheduleCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Tạo scheduled hunt (chạy artifact định kỳ trên Velociraptor) — Super Admin only."""
    # Validate allowlist — nếu Velociraptor chưa cấu hình allowlist, reject.
    # (Schedule có thể tạo trước khi set credentials — sẽ fail khi chạy với allowlist check.)
    cfg_row = (await db.execute(select(VelociraptorConfig).where(VelociraptorConfig.id == 1))).scalar_one_or_none()
    if cfg_row is None or not cfg_row.allowlist:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Velociraptor chưa cấu hình (cần set allowlist trước)",
        )
    allowlist = list(cfg_row.allowlist or [])
    _validate_artifact(body.artifact, allowlist)

    # Validate scope=multi + machine_ids
    if body.scope == "multi" and (not body.machine_ids or len(body.machine_ids) == 0):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scope=multi yêu cầu machine_ids (ít nhất 1)",
        )

    from datetime import datetime as dt, timedelta as td

    next_run = dt.now(UTC) + td(seconds=body.interval_seconds)
    schedule = DfirSchedule(
        name=body.name,
        artifact=body.artifact,
        scope=body.scope,
        machine_ids=[str(m) for m in body.machine_ids] if body.machine_ids else None,
        interval_seconds=body.interval_seconds,
        enabled=True,
        next_run_at=next_run,
        requested_by=admin.id,
    )
    db.add(schedule)
    await append_audit(
        db,
        action="dfir.schedule.create",
        actor=str(admin.id),
        target=body.artifact,
    )
    await db.commit()
    await db.refresh(schedule)
    logger.info(
        "DFIR schedule %s tạo b�i %s: artifact=%s, interval=%ds",
        schedule.id, admin.email, schedule.artifact, schedule.interval_seconds,
    )
    return DfirScheduleOut.model_validate(schedule)


@router.patch("/schedules/{schedule_id}", response_model=DfirScheduleOut)
async def update_dfir_schedule(
    schedule_id: uuid.UUID,
    body: DfirScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Update schedule (name, interval, enabled)."""
    from sqlalchemy import select as sa_select

    schedule = (
        await db.execute(
            sa_select(DfirSchedule).where(DfirSchedule.id == schedule_id)
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy schedule")

    if body.name is not None:
        schedule.name = body.name
    if body.interval_seconds is not None:
        schedule.interval_seconds = body.interval_seconds
    if body.enabled is not None:
        schedule.enabled = body.enabled

    await append_audit(
        db,
        action="dfir.schedule.update",
        actor=str(admin.id),
        target=str(schedule_id),
    )
    await db.commit()
    await db.refresh(schedule)
    return DfirScheduleOut.model_validate(schedule)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dfir_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Xoá schedule."""
    from sqlalchemy import select as sa_select

    schedule = (
        await db.execute(
            sa_select(DfirSchedule).where(DfirSchedule.id == schedule_id)
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy schedule")
    await db.delete(schedule)
    await append_audit(
        db,
        action="dfir.schedule.delete",
        actor=str(admin.id),
        target=str(schedule_id),
    )
    await db.commit()


@router.post("/schedules/{schedule_id}/run-now", response_model=DfirHuntOut, status_code=status.HTTP_201_CREATED)
async def run_dfir_schedule_now(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Trigger chạy schedule ngay lập tức (không đợi next_run_at)."""
    from sqlalchemy import select as sa_select

    schedule = (
        await db.execute(
            sa_select(DfirSchedule).where(DfirSchedule.id == schedule_id)
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy schedule")

    # Reuse existing create_velociraptor_hunt logic — POST tới Velociraptor Server
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Velociraptor chưa cấu hình")
    client, cfg = built

    from datetime import datetime as dt

    dfir = DfirHunt(
        artifact=schedule.artifact,
        scope=schedule.scope,
        machine_id=None,
        requested_by=admin.id,
        status="pending",
        notes=f"Trigger từ schedule '{schedule.name}' (manual run-now)",
    )
    db.add(dfir)
    client_count: int | None = None
    try:
        async with client as velo:
            if schedule.scope == "multi":
                machine_ids = schedule.machine_ids or []
                links = (
                    await db.execute(
                        sa_select(VelociraptorLink).where(
                            VelociraptorLink.machine_id.in_([uuid.UUID(m) for m in machine_ids])
                        )
                    )
                ).scalars().all()
                tasks = [
                    velo.collect_artifact(l.client_id, [schedule.artifact])
                    for l in links
                ]
                flow_ids = await asyncio.gather(*tasks, return_exceptions=True)
                successful = [fid for fid in flow_ids if isinstance(fid, str) and fid]
                client_count = len(successful)
                if successful:
                    dfir.hunt_id = successful[0]
                    dfir.velociraptor_url = (
                        f"{cfg.server_url.rstrip('/')}/#/host/{links[0].client_id}"
                    )
            else:
                clients = await velo.get_all_clients()
                client_ids = [c.get("client_id") for c in clients if c.get("client_id")]
                client_count = len(client_ids)
                if client_count == 0:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail="Velociraptor không có client nào",
                    )
                # Run collect_artifact per client (parallel)
                tasks = [velo.collect_artifact(cid, [schedule.artifact]) for cid in client_ids]
                flow_ids = await asyncio.gather(*tasks, return_exceptions=True)
                successful = [fid for fid in flow_ids if isinstance(fid, str) and fid]
                client_count = len(successful)
                if successful:
                    dfir.hunt_id = successful[0]
                    dfir.velociraptor_url = (
                        f"{cfg.server_url.rstrip('/')}/#/host/{client_ids[0]}"
                    )

        dfir.status = "completed"
        # Update schedule timestamps
        from datetime import timedelta
        schedule.last_run_at = dt.now(UTC)
        schedule.last_status = "completed"
        schedule.next_run_at = schedule.last_run_at + timedelta(seconds=schedule.interval_seconds)
        await db.commit()
        await db.refresh(dfir)
        return DfirHuntOut(
            id=dfir.id, hunt_id=dfir.hunt_id, artifact=dfir.artifact,
            scope=dfir.scope, machine_id=dfir.machine_id,
            requested_by=dfir.requested_by, status=dfir.status,
            velociraptor_url=dfir.velociraptor_url, notes=dfir.notes,
            error=dfir.error, created_at=dfir.created_at,
            client_count=client_count,
        )
    except Exception as e:
        dfir.status = "error"
        dfir.error = str(e)
        schedule.last_status = "error"
        schedule.last_error = str(e)
        await db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Schedule run-now lỗi: {e}",
        ) from e


# ── Alert endpoints ────────────────────────────────────────


@router.get("/alerts", response_model=list[DfirAlertOut])
async def list_dfir_alerts(
    limit: int = 50,
    offset: int = 0,
    resolved: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """List DFIR alerts (artifact sensitive patterns xuất hiện).

    - Default: chưa resolve, mới nhất trước
    - resolved=true: chỉ alerts đã resolve
    - resolved=false: chỉ alerts chưa resolve (default nếu None)
    """
    from sqlalchemy import select as sa_select
    from app.db.models import DfirAlert

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = sa_select(DfirAlert).order_by(DfirAlert.created_at.desc()).limit(limit).offset(offset)
    if resolved is not None:
        stmt = stmt.where(DfirAlert.resolved == resolved)
    alerts = (await db.execute(stmt)).scalars().all()
    return [DfirAlertOut.model_validate(a) for a in alerts]


@router.patch("/alerts/{alert_id}/resolve", response_model=DfirAlertOut)
async def resolve_dfir_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """Đánh dấu alert đã xử lý."""
    from sqlalchemy import select as sa_select
    from app.db.models import DfirAlert

    alert = (
        await db.execute(
            sa_select(DfirAlert).where(DfirAlert.id == alert_id)
        )
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy alert")
    alert.resolved = True
    await append_audit(
        db,
        action="dfir.alert.resolve",
        actor=str(admin.id),
        target=str(alert_id),
    )
    await db.commit()
    await db.refresh(alert)
    return DfirAlertOut.model_validate(alert)
