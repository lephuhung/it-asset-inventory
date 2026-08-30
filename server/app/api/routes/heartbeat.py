"""Route heartbeat — agent gửi định kỳ (30s ± 8s jitter, cấu hình qua server), mTLS."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_machine_id
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.db.models import Heartbeat, Machine, MachineStatus
from app.db.session import get_db
from app.schemas import HeartbeatRequest, HeartbeatResponse
from app.services.agent_settings import compute_agent_config_hash, effective_agent_config

router = APIRouter(prefix="/api/heartbeat", tags=["heartbeat"])


@router.post("", response_model=HeartbeatResponse)
async def heartbeat(
    request: Request,
    body: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    machine_cn: str = Depends(get_client_machine_id),
):
    """Agent heartbeat — identity từ client cert (nginx forward header)."""
    try:
        machine_id = uuid.UUID(machine_cn)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="CN không hợp lệ")

    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Máy không tồn tại")

    now = datetime.now(UTC)
    was_online = machine.status == MachineStatus.ONLINE.value
    machine.last_seen_at = now
    machine.status = MachineStatus.ONLINE.value

    hb = Heartbeat(
        machine_id=machine.id,
        ts=now,
        ip=get_client_ip(request) or body.ip,
        logged_user=body.logged_user,
        uptime_sec=body.uptime_sec,
    )
    db.add(hb)

    # Lưu online status vào Redis với TTL (mục 5.2 tài liệu gốc).
    # Redis chưa khả dụng (dev) → fallback đọc trạng thái từ DB; không block heartbeat.
    logger = logging.getLogger("heartbeat")
    rescan_requested = False
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.set(
            f"machine:online:{machine.id}", "1", ex=settings.effective_online_ttl_seconds
        )
        # On-demand rescan (Phase 3, #23): flag do admin bấm trên portal
        if await r.get(f"machine:rescan:{machine.id}"):
            rescan_requested = True
            await r.delete(f"machine:rescan:{machine.id}")
        await r.aclose()
    except Exception:  # noqa: BLE001
        logger.debug("Redis chưa khả dụng — dựa vào DB cho online status")

    await db.commit()

    # Publish sự kiện realtime khi máy từ trạng thái khác sang ONLINE (tránh spam)
    if not was_online:
        from app.services.realtime import publish_machine_event

        await publish_machine_event(machine.id, MachineStatus.ONLINE.value, machine.hostname)

    agent_cfg = await effective_agent_config(db)
    return HeartbeatResponse(
        server_time=now,
        renew_after=now + timedelta(days=int(settings.client_cert_valid_days * 0.7)),
        heartbeat_interval_seconds=agent_cfg["heartbeat_interval_seconds"],
        heartbeat_jitter_seconds=agent_cfg["heartbeat_jitter_seconds"],
        server_url=agent_cfg["agent_server_url"],
        agent_server_url=agent_cfg["agent_server_url"],
        inventory_interval_hours=agent_cfg["inventory_interval_hours"],
        renew_before_percent=agent_cfg["renew_before_percent"],
        agent_config_hash=compute_agent_config_hash(agent_cfg),
        rescan_requested=rescan_requested,
    )
