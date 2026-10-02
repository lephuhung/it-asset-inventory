"""Unit tests — chat capability (HS256) + completion token.

Capability là JWT ngắn hạn do backend ký, agent mang theo để xác thực các call
nội bộ (inventory query, audit intent). Đây là lớp *chữ ký + claim*; kiểm tra
turn còn active / chủ sở hữu hội thoại nằm ở route dependency (T10).
"""
from __future__ import annotations

import base64
import string
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.chat_capability import (
    ALGORITHM,
    AUD,
    ISS,
    CapabilityClaims,
    CapabilityError,
    hash_completion_token,
    new_completion_token,
    sign_capability,
    verify_capability,
)
from app.core.config import settings


def _mint(**overrides) -> str:
    """Ký một token hợp lệ rồi ghi đè claim — dùng để test từng claim độc lập."""
    now = datetime.now(UTC)
    payload = {
        "iss": ISS,
        "aud": AUD,
        "sub": str(uuid4()),
        "cid": str(uuid4()),
        "tid": str(uuid4()),
        "rid": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=300)).timestamp()),
    }
    payload.update(overrides)
    return jwt.encode(payload, settings.chat_context_secret, algorithm=ALGORITHM)


# ── Round-trip & TTL ──────────────────────────────────────────────


def test_round_trip_returns_all_identity_claims():
    actor, conv, turn, req = uuid4(), uuid4(), uuid4(), uuid4()
    tok = sign_capability(actor, conv, turn, req)
    claims = verify_capability(tok)

    assert isinstance(claims, CapabilityClaims)
    assert claims.actor_id == actor
    assert claims.conversation_id == conv
    assert claims.turn_id == turn
    assert claims.request_id == req
    assert claims.exp > claims.iat


def test_default_ttl_is_300_seconds():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    claims = verify_capability(tok)
    assert claims.exp - claims.iat == 300


def test_claims_are_strings_on_the_wire():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    raw = jwt.decode(tok, options={"verify_signature": False})
    assert raw["sub"] == str(raw["sub"])
    assert set(raw) == {"iss", "aud", "sub", "cid", "tid", "rid", "iat", "exp"}
    # machine_id mutable — KHÔNG bao giờ nằm trong capability.
    assert "machine_id" not in raw


def test_capability_does_not_include_machine_id():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    raw = jwt.decode(tok, options={"verify_signature": False})
    assert "machine_id" not in raw
    assert "machine_ref" not in raw


# ── Expiry & leeway ───────────────────────────────────────────────


def test_expired_rejected():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4(), ttl=-60)
    with pytest.raises(CapabilityError):
        verify_capability(tok)


def test_leeway_allows_recently_expired():
    # Hết hạn 10s trước — nằm trong skew cho phép 30s → vẫn chấp nhận.
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4(), ttl=-10)
    claims = verify_capability(tok)
    assert claims.turn_id


def test_far_expired_not_rescued_by_leeway():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4(), ttl=-120)
    with pytest.raises(CapabilityError):
        verify_capability(tok)


# ── Claim integrity ───────────────────────────────────────────────


def test_wrong_audience_rejected():
    tok = _mint(aud="some-other-audience")
    with pytest.raises(CapabilityError):
        verify_capability(tok)


def test_wrong_issuer_rejected():
    tok = _mint(iss="attacker")
    with pytest.raises(CapabilityError):
        verify_capability(tok)


def test_missing_required_claim_rejected():
    now = datetime.now(UTC)
    payload = {
        "iss": ISS,
        "aud": AUD,
        "sub": str(uuid4()),
        "cid": str(uuid4()),
        # thiếu "tid"
        "rid": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=300)).timestamp()),
    }
    tok = jwt.encode(payload, settings.chat_context_secret, algorithm=ALGORITHM)
    with pytest.raises(CapabilityError):
        verify_capability(tok)


def test_malformed_uuid_claim_rejected():
    tok = _mint(tid="not-a-uuid")
    with pytest.raises(CapabilityError):
        verify_capability(tok)


# ── Signature integrity ───────────────────────────────────────────


def test_tampered_signature_rejected():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    header, payload, sig = tok.split(".")
    # Lật 1 bit thực trong chữ ký (không đụng padding bit cuối base64url).
    raw = bytearray(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
    raw[0] ^= 0x01
    tampered_sig = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    with pytest.raises(CapabilityError):
        verify_capability(f"{header}.{payload}.{tampered_sig}")


def test_tampered_payload_rejected():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    header, payload, sig = tok.split(".")
    raw = bytearray(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    raw[0] ^= 0x01
    tampered_payload = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    with pytest.raises(CapabilityError):
        verify_capability(f"{header}.{tampered_payload}.{sig}")


def test_wrong_secret_rejected(monkeypatch):
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    monkeypatch.setattr(settings, "chat_context_secret", "x" * 40)
    with pytest.raises(CapabilityError):
        verify_capability(tok)


def test_alg_none_rejected():
    now = datetime.now(UTC)
    payload = {
        "iss": ISS,
        "aud": AUD,
        "sub": str(uuid4()),
        "cid": str(uuid4()),
        "tid": str(uuid4()),
        "rid": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=300)).timestamp()),
    }
    tok = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(CapabilityError):
        verify_capability(tok)


# ── Completion token ──────────────────────────────────────────────


def test_completion_token_hash_is_sha256_hex():
    h = hash_completion_token(new_completion_token())
    assert len(h) == 64
    assert set(h) <= set("0123456789abcdef")


def test_completion_token_hash_deterministic():
    tok = new_completion_token()
    assert hash_completion_token(tok) == hash_completion_token(tok)


def test_completion_token_distinct_hashes():
    a, b = new_completion_token(), new_completion_token()
    assert a != b
    assert hash_completion_token(a) != hash_completion_token(b)


def test_completion_token_is_url_safe():
    tok = new_completion_token()
    assert len(tok) >= 40
    assert set(tok) <= set(string.ascii_letters + string.digits + "-_")


def test_completion_token_hash_of_unicode_is_stable():
    # token sinh từ secrets luôn ASCII, nhưng hash phải ổn định với mọi input.
    assert hash_completion_token("a") == hash_completion_token("a")
    assert len(hash_completion_token("a")) == 64
