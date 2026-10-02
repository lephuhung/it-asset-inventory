"""Capability `chat_context` + completion token (F3/R2, V3-3).

Capability là JWT compact **HS256** do backend ký (`CHAT_CONTEXT_SECRET`, backend-only);
agent chỉ mang token, không bao giờ giữ secret. Claim mang danh tính một lần dispatch:

- `iss="backend"`, `aud="chat-internal"`
- `sub` = actor_id (chủ hội thoại)
- `cid` = conversation_id, `tid` = turn_id, `rid` = request_id
- `iat`, `exp` (mặc định 300s, skew verify ≤ 30s)

`machine_id` là lookup mutable nên **không** nằm trong capability (chỉ `machine_ref`
bất biến được hash trong audit — xem `app/core/audit.py`).

Module này chỉ lo *chữ ký + claim*. Kiểm tra turn còn `pending|streaming` và
`conversation.created_by == actor_id` (revoke theo turn) nằm ở route dependency
`app/api/routes/chat_internal.py` (T10), vì cần DB.

`completion_token` là secret **riêng** cho finalization (V3-3): backend sinh token,
lưu `sha256(token)` vào `chat_turns.completion_token_hash`, và agent gửi lại token
gốc qua `X-Chat-Completion` khi gọi `/turns/{id}/complete` — không phụ thuộc `exp`
của capability.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

import jwt
from pydantic import BaseModel

from app.core.config import settings

ISS = "backend"
AUD = "chat-internal"
ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 300
LEEWAY_SECONDS = 30  # skew đồng hồ cho phép khi verify exp/iat

# Claim bắt buộc — thiếu bất kỳ claim nào là token không hợp lệ (fail-closed).
_REQUIRED_CLAIMS = ["iss", "aud", "sub", "cid", "tid", "rid", "iat", "exp"]


class CapabilityError(ValueError):
    """Capability không hợp lệ (chữ ký/claim/hết hạn). Route map sang `[chat_authz]`."""


class CapabilityClaims(BaseModel):
    """Danh tính đã verify từ capability. UUID đã parse, sẵn dùng cho ownership check."""

    actor_id: uuid.UUID
    conversation_id: uuid.UUID
    turn_id: uuid.UUID
    request_id: uuid.UUID
    iat: int
    exp: int


def sign_capability(
    actor_id: uuid.UUID | str,
    conversation_id: uuid.UUID | str,
    turn_id: uuid.UUID | str,
    request_id: uuid.UUID | str,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Ký capability turn-scoped. `ttl` giây (âm = đã hết hạn, dùng cho test)."""
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "iss": ISS,
        "aud": AUD,
        "sub": str(actor_id),
        "cid": str(conversation_id),
        "tid": str(turn_id),
        "rid": str(request_id),
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.chat_context_secret, algorithm=ALGORITHM)


def verify_capability(token: str) -> CapabilityClaims:
    """Verify chữ ký + `aud` + `iss` + `exp` (leeway 30s). Raise `CapabilityError`."""
    try:
        payload = jwt.decode(
            token,
            settings.chat_context_secret,
            algorithms=[ALGORITHM],
            audience=AUD,
            issuer=ISS,
            leeway=LEEWAY_SECONDS,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.InvalidTokenError as exc:
        raise CapabilityError(f"[chat_authz] invalid capability: {exc}") from exc

    try:
        return CapabilityClaims(
            actor_id=uuid.UUID(payload["sub"]),
            conversation_id=uuid.UUID(payload["cid"]),
            turn_id=uuid.UUID(payload["tid"]),
            request_id=uuid.UUID(payload["rid"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise CapabilityError("[chat_authz] malformed capability claims") from exc


def new_completion_token() -> str:
    """Sinh completion token ngẫu nhiên (URL-safe) cho một turn."""
    return secrets.token_urlsafe(32)


def hash_completion_token(token: str) -> str:
    """Hash để lưu DB (`chat_turns.completion_token_hash`) — không lưu token gốc."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
