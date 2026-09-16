"""Redis client dùng chung (lazy singleton).

`aioredis.from_url()` tạo một connection pool mới mỗi lần gọi — gọi per-request
(heartbeat 30s/máy, publish realtime, rescan flag) gây churn không cần thiết.
Module này trả về 1 client sống theo process.

Lưu ý: pub/sub SUBSCRIBE (ws.py) vẫn cần connection riêng — KHÔNG dùng helper
này cho subscriber.
"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import settings

_CLIENT: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _CLIENT
