"""Cấu hình agent hiệu lực = env mặc định + override từ DB (portal đặt).

Mọi nơi trả cấu hình cho agent (`/api/agent/config`, heartbeat, enroll) đều đi qua
`effective_agent_config()` để agent luôn nhận nhất quán một nguồn.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AgentConfigOverride

# Giới hạn hợp lý khi Super Admin chỉnh từ portal
LIMITS = {
    "heartbeat_interval_seconds": (5, 3600),
    "heartbeat_jitter_seconds": (0, 600),
    "inventory_interval_hours": (1, 168),
}


async def get_override(db: AsyncSession) -> AgentConfigOverride | None:
    """Dòng override duy nhất (id=1) — None nếu chưa từng chỉnh."""
    return (
        await db.execute(select(AgentConfigOverride).where(AgentConfigOverride.id == 1))
    ).scalar_one_or_none()


async def effective_agent_config(db: AsyncSession) -> dict:
    """Payload cấu hình agent áp dụng thực tế (override DB đè lên env mặc định)."""
    cfg = settings.agent_config_payload()
    ov = await get_override(db)
    if ov is None:
        payload = dict(cfg)
    else:
        hb = ov.heartbeat_interval_seconds if ov.heartbeat_interval_seconds is not None else cfg["heartbeat_interval_seconds"]
        jit = ov.heartbeat_jitter_seconds if ov.heartbeat_jitter_seconds is not None else cfg["heartbeat_jitter_seconds"]
        payload = {
            "heartbeat_interval_seconds": hb,
            "heartbeat_jitter_seconds": jit,
            # TTL online luôn theo công thức 2 × (chu kỳ + jitter) trên giá trị hiệu lực
            "online_ttl_seconds": 2 * (hb + jit),
            "inventory_interval_hours": ov.inventory_interval_hours
            if ov.inventory_interval_hours is not None
            else cfg["inventory_interval_hours"],
            "renew_before_percent": cfg["renew_before_percent"],
        }
    payload["agent_server_url"] = (
        ov.agent_server_url if ov is not None and ov.agent_server_url else settings.agent_server_url
    )
    return payload
