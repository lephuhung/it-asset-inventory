"""WebSocket realtime dashboard — `/api/ws`.

Auth bằng JWT qua query param `?token=...` (WebSocket browser khó set header).
Subscribe Redis pub/sub `machine:events` → forward JSON sự kiện cho client.
Mỗi kết nối 1 subscriber riêng; đóng kết nối khi client ngắt (disconnect).
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.security import decode_token

router = APIRouter(tags=["ws"])


async def _authenticate(token: str) -> dict:
    """Xác thực JWT, trả payload. Ném exception nếu không hợp lệ."""
    return decode_token(token, "access")


@router.websocket("/api/ws")
async def websocket_status(ws: WebSocket, token: str = Query(...)):
    try:
        payload = await _authenticate(token)
        user_id = payload.get("sub")
    except Exception:  # noqa: BLE001
        await ws.close(code=4401, reason="Token không hợp lệ")
        return

    await ws.accept()

    # Subscriber riêng cho kênh machine:events — subscribe TRƯỚC rồi mới báo hello,
    # tránh mất message do pub/sub chỉ giao cho subscriber đã đăng ký tại thời điểm publish.
    red = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = red.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe("machine:events")

    try:
        await ws.send_json({"type": "hello", "user_id": user_id})

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data: Any = json.loads(message["data"])
                    await ws.send_json({"type": "machine_event", **data})
        finally:
            await pubsub.unsubscribe("machine:events")
            await pubsub.aclose()
            await red.aclose()
    except WebSocketDisconnect:
        pass  # client ngắt — dọn dẹp đã chạy trong finally
    except Exception:  # noqa: BLE001
        try:
            await ws.close(code=1011, reason="Lỗi nội bộ")
        except Exception:  # noqa: BLE001, S110 — socket đã đóng vẫn tốt: bỏ qua im lặng
            pass
