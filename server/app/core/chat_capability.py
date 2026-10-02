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


def _to_uuid(value: object, claim_name: str) -> uuid.UUID:
    """Parse claim thành UUID; mọi kiểu/giá trị sai → `CapabilityError` (không rò AttributeError)."""
    try:
        return uuid.UUID(value)  # type: ignore[arg-type]
    except (ValueError, AttributeError, TypeError) as exc:
        raise CapabilityError(f"[chat_authz] malformed capability claim {claim_name}") from exc


def _to_int(value: object, claim_name: str) -> int:
    """Parse claim số; giá trị không chuyển được sang int → `CapabilityError`.

    Bắt cả `OverflowError`: JSON cho phép số vượt dải float (vd `1e400` → `inf`),
    và `int(inf)` ném `OverflowError` — không được rò ra ngoài contract.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise CapabilityError(f"[chat_authz] malformed capability claim {claim_name}") from exc


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
    """Ký capability turn-scoped. `ttl` giây (âm = đã hết hạn, dùng cho test).

    Trần cứng `DEFAULT_TTL_SECONDS` (300s): TTL vượt trần bị từ chối ngay khi ký
    (không có capability sống lâu hơn spec cho phép).
    """
    if ttl > DEFAULT_TTL_SECONDS:
        raise CapabilityError(
            f"[chat_authz] capability ttl {ttl}s exceeds {DEFAULT_TTL_SECONDS}s maximum"
        )
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
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        # PyJWT chỉ bắt ValueError cho numeric claim; iat/exp kiểu sai có thể ném
        # TypeError/AttributeError ra ngoài, còn giá trị vượt dải float (vd `1e400`)
        # ném OverflowError ngay trong validator của PyJWT → chuẩn hoá hết về
        # CapabilityError để route không bao giờ thấy exception lạ.
        raise CapabilityError(f"[chat_authz] invalid capability: {exc}") from exc

    actor_id = _to_uuid(payload.get("sub"), "sub")
    conversation_id = _to_uuid(payload.get("cid"), "cid")
    turn_id = _to_uuid(payload.get("tid"), "tid")
    request_id = _to_uuid(payload.get("rid"), "rid")
    iat = _to_int(payload.get("iat"), "iat")
    exp = _to_int(payload.get("exp"), "exp")

    # Phòng thủ theo chiều sâu: token ký bởi bản cũ (không có trần) vẫn bị từ chối.
    if exp - iat > DEFAULT_TTL_SECONDS:
        raise CapabilityError(
            f"[chat_authz] capability lifetime exceeds {DEFAULT_TTL_SECONDS}s maximum"
        )

    return CapabilityClaims(
        actor_id=actor_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        request_id=request_id,
        iat=iat,
        exp=exp,
    )


def new_completion_token() -> str:
    """Sinh completion token ngẫu nhiên (URL-safe) cho một turn."""
    return secrets.token_urlsafe(32)


def hash_completion_token(token: str) -> str:
    """Hash để lưu DB (`chat_turns.completion_token_hash`) — không lưu token gốc."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
