"""WebSocket realtime — `/api/ws?token=...`.

Multi-channel pub/sub:
  - `machine:events`  (cũ) — sự kiện máy online/offline/lost
  - `notification:user:{user_id}` — notification cá nhân
  - `notification:broadcast` — broadcast tới tất cả (optional, admin gửi)

Client connect → server tự subscribe `machine:events` + `notification:user:{user_id}`.
Client có thể gửi:
  - {type: "ping"} → {type: "pong"}
  - {type: "subscribe", "channels": ["extra:channel"]}
  - {type: "unsubscribe", "channels": [...]}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.security import decode_token

logger = logging.getLogger("ws")
router = APIRouter(tags=["ws"])


async def _authenticate(token: str) -> dict:
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
    await ws.send_json({"type": "hello", "user_id": user_id})

    # Subscribe trước khi listen — tránh miss message
    red = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = red.pubsub(ignore_subscribe_messages=True)
    channels = {"machine:events", f"notification:user:{user_id}"}
    for ch in channels:
        await pubsub.subscribe(ch)
    await ws.send_json({"type": "subscribed", "channels": sorted(channels)})

    stop_event = asyncio.Event()
    send_lock = asyncio.Lock()

    async def reader_task() -> None:
        """Đọc message từ client (ping, subscribe, ...)."""
        try:
            while not stop_event.is_set():
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                if mtype == "ping":
                    async with send_lock:
                        await ws.send_json({"type": "pong"})
                elif mtype == "subscribe":
                    new_chs = msg.get("channels") or []
                    for ch in new_chs:
                        if ch not in channels and isinstance(ch, str) and ch.startswith(("machine:", "notification:", "user:")):
                            await pubsub.subscribe(ch)
                            channels.add(ch)
                elif mtype == "unsubscribe":
                    rm_chs = msg.get("channels") or []
                    for ch in rm_chs:
                        if ch in channels and ch not in {"machine:events", f"notification:user:{user_id}"}:
                            await pubsub.unsubscribe(ch)
                            channels.discard(ch)
        except WebSocketDisconnect:
            stop_event.set()
        except Exception as e:  # noqa: BLE001
            logger.debug("WS reader error: %s", e)
            stop_event.set()

    reader = asyncio.create_task(reader_task())

    try:
        async for message in pubsub.listen():
            if stop_event.is_set():
                break
            if message["type"] != "message":
                continue
            try:
                data: Any = json.loads(message["data"])
                # Forward raw payload — client tự phân tích `type`
                async with send_lock:
                    await ws.send_json(data)
            except Exception as e:  # noqa: BLE001
                logger.debug("WS forward error: %s", e)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("WS error: %s", e)
    finally:
        stop_event.set()
        reader.cancel()
        try:
            await reader
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await red.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
