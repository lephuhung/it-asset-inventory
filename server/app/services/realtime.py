"""Realtime — Redis pub/sub cho sự kiện máy (WebSocket dashboard).

Kênh `machine:events` — payload JSON: {machine_id, status, hostname, ts}.
Heartbeat (online), offline detection (background), đăng ký mới (enroll) đều publish.
Portal kết nối `/api/ws` để nhận stream.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

CHANNEL = "machine:events"
logger = logging.getLogger("realtime")


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def publish_machine_event(
    machine_id: uuid.UUID, status: str, hostname: str | None = None, **extra: Any
) -> None:
    """Publish 1 sự kiện máy lên Redis pub/sub (không block nếu Redis lỗi)."""
    payload = {
        "machine_id": str(machine_id),
        "status": status,
        "hostname": hostname,
        "ts": datetime.now(UTC).isoformat(),
        **extra,
    }
    try:
        r = _redis()
        await r.publish(CHANNEL, json.dumps(payload, ensure_ascii=False))
        await r.aclose()
    except Exception:  # noqa: BLE001 — Redis down: realtime là non-critical, không làm lỗi API
        logger.debug("Redis chưa khả dụng — bỏ qua publish realtime")
