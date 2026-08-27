"""Cấu hình agent hiệu lực = env mặc định + override từ DB (portal đặt).

Mọi nơi trả cấu hình cho agent (`/api/agent/config`, heartbeat, enroll) đều đi qua
`effective_agent_config()` để agent luôn nhận nhất quán một nguồn.
"""
from __future__ import annotations

import hashlib
import json

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
    payload["portal_url"] = (
        ov.portal_url if ov is not None and ov.portal_url else settings.portal_url
    )
    return payload


def compute_agent_config_hash(cfg: dict) -> str:
    """SHA-256 hex của canonical JSON (sort_keys, ensure_ascii=False) của cấu hình agent.

    Agent dùng hash này để so sánh với hash cũ trong heartbeat response — nếu khác
    thì agent gọi lại GET /api/agent/config để lấy cấu hình mới nhất thay vì chờ
    tới chu kỳ ConfigSync 6h. Tránh được tình trạng admin đổi cấu hình trên portal
    mà agent phải đợi tối đa 6h mới nhận được.

    ⚠️ Phải khớp với cách C# `AgentConfig.ComputeConfigHash()` serialize (exclude
    agent_server_url? — KHÔNG: agent hash dựa trên endpoint, interval, jitter, inv,
    renew. Trường `agent_server_url` cũng có trong hash vì nó nằm trong
    `ComputeConfigHash` của agent — xem agent/src/OrgInventoryAgent/AgentConfig.cs).
    """
    payload = {
        "endpoints": [cfg.get("agent_server_url")],
        "heartbeat_interval_seconds": cfg["heartbeat_interval_seconds"],
        "heartbeat_jitter_seconds": cfg["heartbeat_jitter_seconds"],
        "inventory_interval_hours": cfg["inventory_interval_hours"],
        "renew_before_percent": cfg["renew_before_percent"],
    }
    # Lọc None để khớp với C# (DefaultIgnoreCondition.WhenWritingNull bỏ field null)
    payload = {k: v for k, v in payload.items() if v is not None}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
