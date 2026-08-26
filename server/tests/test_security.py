"""Unit tests — security: JWT, AES-256-GCM, TOTP, bcrypt, token entropy."""
from __future__ import annotations

import jwt as pyjwt

from app.core import security


def test_access_token_roundtrip():
    token = security.create_access_token("user-1", "admin_global", "org-1")
    payload = security.decode_token(token, "access")
    assert payload["sub"] == "user-1"
    assert payload["role"] == "admin_global"
    assert payload["org_id"] == "org-1"


def test_refresh_token_rejected_as_access():
    refresh = security.create_refresh_token("user-1")
    try:
        security.decode_token(refresh, "access")
        assert False, "Phải từ chối refresh token khi dùng như access"
    except pyjwt.InvalidTokenError:
        pass


def test_password_hash_verify():
    h = security.hash_password("secret123")
    assert security.verify_password("secret123", h)
    assert not security.verify_password("wrong", h)


def test_aes_gcm_roundtrip_and_uniqueness():
    p1 = security.encrypt_aes_gcm("0987654321")
    p2 = security.encrypt_aes_gcm("0987654321")
    # IV ngẫu nhiên → 2 bản mã khác nhau
    assert p1 != p2
    assert security.decrypt_aes_gcm(p1) == "0987654321"
    assert security.decrypt_aes_gcm(p2) == "0987654321"


def test_totp_verify():
    secret = security.generate_totp_secret()
    code = security.totp_uri(secret, "a@b.c")
    assert "otpauth://" in code
    # không có thư viện clock thật — chỉ test cấu trúc; verify logic qua pyotp
    import pyotp

    totp = pyotp.TOTP(secret)
    assert security.verify_totp(secret, totp.now())
    assert not security.verify_totp(secret, "000000")


def test_enroll_token_entropy_and_hash():
    t1 = security.generate_enroll_token()
    t2 = security.generate_enroll_token()
    assert t1.startswith("t_") and len(t1) >= 22
    assert t1 != t2
    h = security.hash_token(t1)
    assert len(h) == 64
    assert h != security.hash_token(t2)


def test_backup_codes_unique():
    codes = security.generate_backup_codes(10)
    assert len(set(codes)) == 10
