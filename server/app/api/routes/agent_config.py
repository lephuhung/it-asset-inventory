"""Route cấu hình agent — GET /api/agent/config.

Agent gọi sau khi enroll (đã có client cert → mTLS qua nginx).
Trả về cấu hình server đang áp dụng: tần suất heartbeat, jitter, online TTL,
chu kỳ inventory, thời điểm gia hạn cert. Agent đồng bộ cấu hình từ đây
(điều chỉnh tham số theo server — operator cấu hình 1 chỗ trên server).
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_machine_id
from app.db.session import get_db
from app.schemas import AgentConfigResponse
from app.services.agent_settings import effective_agent_config

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/config", response_model=AgentConfigResponse)
async def agent_config(
    db: AsyncSession = Depends(get_db),
    machine_cn: str = Depends(get_client_machine_id),
):
    """Cấu hình agent hiện hành — bắt buộc mTLS (X-SSL-Client-CN từ nginx).

    `machine_cn` chỉ để xác thực agent hợp lệ (server từ chối request không có cert).
    """
    agent_cfg = await effective_agent_config(db)
    return AgentConfigResponse(
        server_url=agent_cfg["agent_server_url"],
        heartbeat_interval_seconds=agent_cfg["heartbeat_interval_seconds"],
        heartbeat_jitter_seconds=agent_cfg["heartbeat_jitter_seconds"],
        online_ttl_seconds=agent_cfg["online_ttl_seconds"],
        inventory_interval_hours=agent_cfg["inventory_interval_hours"],
        renew_before_percent=agent_cfg["renew_before_percent"],
        server_time=datetime.now(UTC),
    )