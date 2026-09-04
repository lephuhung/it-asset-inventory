"""Route cấu hình agent cho portal — GET/PUT /api/agent-settings.

Admin xem cấu hình hiệu lực (agent đang nhận); Super Admin chỉnh override
(heartbeat, chu kỳ inventory, IP/Domain server đẩy dữ liệu). Agent tự đồng bộ
qua `/api/agent/config` + heartbeat.
"""
from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_super_admin
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.db.models import AgentConfigOverride, User
from app.db.session import get_db
from app.schemas import AgentSettingsOut, AgentSettingsUpdate
from app.services.agent_settings import LIMITS, effective_agent_config, get_override

router = APIRouter(prefix="/api/agent-settings", tags=["agent-settings"])


@router.get("", response_model=AgentSettingsOut)
async def get_agent_settings(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    """Cấu hình agent hiện hành — agent đang nhận các giá trị này."""
    cfg = await effective_agent_config(db)
    ov = await get_override(db)
    defaults = {
        "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
        "heartbeat_jitter_seconds": settings.heartbeat_jitter_seconds,
        "inventory_interval_hours": settings.inventory_interval_hours,
        "agent_server_url": settings.agent_server_url,
        "portal_url": settings.portal_url,
    }
    overridden = (
        {
            "heartbeat_interval_seconds": ov.heartbeat_interval_seconds is not None,
            "heartbeat_jitter_seconds": ov.heartbeat_jitter_seconds is not None,
            "inventory_interval_hours": ov.inventory_interval_hours is not None,
            "agent_server_url": ov.agent_server_url is not None,
            "portal_url": ov.portal_url is not None,
        }
        if ov is not None
        else {}
    )
    return AgentSettingsOut(
        heartbeat_interval_seconds=cfg["heartbeat_interval_seconds"],
        heartbeat_jitter_seconds=cfg["heartbeat_jitter_seconds"],
        online_ttl_seconds=cfg["online_ttl_seconds"],
        inventory_interval_hours=cfg["inventory_interval_hours"],
        renew_before_percent=cfg["renew_before_percent"],
        agent_server_url=cfg["agent_server_url"],
        portal_url=cfg["portal_url"],
        defaults=defaults,
        overridden=overridden,
        updated_at=ov.updated_at if ov is not None else None,
        updated_by=ov.updated_by if ov is not None else None,
    )


@router.put("", response_model=AgentSettingsOut)
async def update_agent_settings(
    body: AgentSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    """Lưu override cấu hình agent (Super Admin). Ghi audit log."""
    # Kiểm tra giới hạn hợp lý (schema đã chặn range, đây là chốt cuối)
    for field, (lo, hi) in LIMITS.items():
        v = getattr(body, field)
        if v is not None and not (lo <= v <= hi):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} phải trong [{lo}, {hi}]",
            )
    url = body.agent_server_url
    if url is not None and not url.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="URL không được rỗng")
    portal_url = body.portal_url
    if portal_url is not None and not portal_url.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Portal URL không được rỗng")

    ov = await get_override(db)
    if ov is None:
        ov = AgentConfigOverride(id=1)
        db.add(ov)
    changes: dict[str, object] = {}
    for field in ("heartbeat_interval_seconds", "heartbeat_jitter_seconds", "inventory_interval_hours"):
        v = getattr(body, field)
        if v is not None:
            # Trùng mặc định env → xóa override (tránh "Đổi" ảo trên portal)
            setattr(ov, field, None if v == getattr(settings, field) else v)
            changes[field] = v
    if url is not None:
        ov.agent_server_url = url.strip()
        changes["agent_server_url"] = url.strip()
    if portal_url is not None:
        ov.portal_url = portal_url.strip()
        changes["portal_url"] = portal_url.strip()
    from datetime import UTC, datetime

    ov.updated_at = datetime.now(UTC)
    ov.updated_by = admin.id

    await append_audit(db, action="agent_config.update", actor=str(admin.id), target=str(ov.id), ip=get_client_ip(request))
    await db.commit()

    cfg = await effective_agent_config(db)
    defaults = {
        "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
        "heartbeat_jitter_seconds": settings.heartbeat_jitter_seconds,
        "inventory_interval_hours": settings.inventory_interval_hours,
        "agent_server_url": settings.agent_server_url,
        "portal_url": settings.portal_url,
    }
    return AgentSettingsOut(
        heartbeat_interval_seconds=cfg["heartbeat_interval_seconds"],
        heartbeat_jitter_seconds=cfg["heartbeat_jitter_seconds"],
        online_ttl_seconds=cfg["online_ttl_seconds"],
        inventory_interval_hours=cfg["inventory_interval_hours"],
        renew_before_percent=cfg["renew_before_percent"],
        agent_server_url=cfg["agent_server_url"],
        portal_url=cfg["portal_url"],
        defaults=defaults,
        overridden={
            "heartbeat_interval_seconds": ov.heartbeat_interval_seconds is not None,
            "heartbeat_jitter_seconds": ov.heartbeat_jitter_seconds is not None,
            "inventory_interval_hours": ov.inventory_interval_hours is not None,
            "agent_server_url": ov.agent_server_url is not None,
            "portal_url": ov.portal_url is not None,
        },
        updated_at=ov.updated_at,
        updated_by=ov.updated_by,
    )
