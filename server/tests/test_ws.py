"""Test WebSocket realtime + Redis pub/sub machine events.

Yêu cầu: Redis chạy trên REDIS_URL (mặc định 127.0.0.1:6381).
WebSocket test dùng Starlette TestClient (hỗ trợ websocket_connect) qua fixture `ws_client`.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.core.security import create_access_token


async def test_publish_machine_event_reaches_subscriber():
    """Publish sự kiện → subscriber trên kênh machine:events nhận được."""
    import json

    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe("machine:events")
    await pubsub.get_message(timeout=1)  # bỏ qua message subscribe-ack

    from app.services.realtime import publish_machine_event

    mid = uuid.uuid4()
    await publish_machine_event(mid, "online", hostname="PC-TEST")

    msg = await pubsub.get_message(timeout=2)
    assert msg is not None and msg["type"] == "message"
    data = json.loads(msg["data"])
    assert data["machine_id"] == str(mid)
    assert data["status"] == "online"

    await pubsub.unsubscribe("machine:events")
    await pubsub.aclose()
    await r.aclose()


def test_websocket_requires_valid_token(ws_client):
    """Token sai → kết nối bị đóng (WebSocketDisconnect)."""
    from starlette.websockets import WebSocketDisconnect

    try:
        with ws_client.websocket_connect("/api/ws?token=badtoken") as ws:
            ws.receive_json()
        raise AssertionError("Kết nối với token sai phải bị đóng")
    except WebSocketDisconnect:
        pass  # đúng — bị đóng


def test_websocket_hello_and_event(ws_client):
    """Token hợp lệ → nhận hello + tin realtime khi publish."""
    import json

    import redis as sync_redis

    user_id = str(uuid.uuid4())
    token = create_access_token(user_id, "admin_global", str(uuid.uuid4()))
    mid = uuid.uuid4()

    with ws_client.websocket_connect(f"/api/ws?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["user_id"] == user_id

        # Publish bằng sync redis (tránh tạo asyncio loop mới trong TestClient)
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.publish(
            "machine:events",
            json.dumps(
                {
                    "machine_id": str(mid),
                    "status": "offline",
                    "hostname": "PC-01",
                    "ts": "2026-01-01T00:00:00",
                }
            ),
        )
        r.close()

        event = ws.receive_json()
        assert event["type"] == "machine_event"
        assert event["machine_id"] == str(mid)
        assert event["status"] == "offline"
