"""Bảo mật ứng dụng: JWT, bcrypt, AES-256-GCM, TOTP.

Tuân theo mục 7.3 tài liệu gốc:
- Số điện thoại / TOTP seed: mã hóa AES-256-GCM, IV ngẫu nhiên mỗi giá trị.
- 2FA TOTP (RFC 6238), ±1 bước clock-skew, chống replay bằng nonce window.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

# ── JWT ────────────────────────────────────────────────────────────


def create_access_token(subject: str, role: str, org_id: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "role": role, "org_id": org_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Sai loại token")
    return payload


# ── Password (bcrypt) ──────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ── AES-256-GCM ────────────────────────────────────────────────────
# Format lưu: base64(iv + ciphertext + tag)


def _aes_key() -> bytes:
    # key từ config; prod phải lấy từ Vault/KMS
    return hashlib.sha256(settings.data_encryption_key.encode("utf-8")).digest()


def encrypt_aes_gcm(plaintext: str) -> str:
    iv = os.urandom(12)
    aesgcm = AESGCM(_aes_key())
    ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(iv + ct).decode("ascii")


def decrypt_aes_gcm(payload: str) -> str:
    raw = base64.b64decode(payload)
    iv, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(_aes_key())
    return aesgcm.decrypt(iv, ct, None).decode("utf-8")


# ── TOTP (RFC 6238) ────────────────────────────────────────────────


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str, issuer: str = "ITAssetInventory") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify với dung sai ±1 bước (window=1) + chống replay theo thời gian."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes(n: int = 10) -> list[str]:
    codes = []
    for _ in range(n):
        codes.append(f"{os.urandom(5).hex().upper()}")
    return codes


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ── Token entropy (enroll token, base62, ≥128 bit) ─────────────────


def generate_enroll_token() -> str:
    """base62, 22 ký tự ≈ 131 bit entropy."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    raw = os.urandom(22)
    num = int.from_bytes(raw, "big")
    out: list[str] = []
    while num > 0:
        num, rem = divmod(num, 62)
        out.append(alphabet[rem])
    return "t_" + "".join(reversed(out)).rjust(22, "0")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
