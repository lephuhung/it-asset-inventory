"""Mã hóa số điện thoại và dữ liệu nhạy cảm (AES-256-GCM).

Wrapper trên app.core.security, thêm mask helper.
"""
from __future__ import annotations

from app.core.security import decrypt_aes_gcm, encrypt_aes_gcm


def mask_phone(phone_encrypted: str | None) -> str | None:
    """Mask số điện thoại: 0983•••123 (trừ khi có quyền xem đầy đủ)."""
    if not phone_encrypted:
        return None
    try:
        plain = decrypt_aes_gcm(phone_encrypted)
    except Exception:  # noqa: BLE001 — data hỏng/khóa sai → che thay vì lỗi endpoint
        return "••• (giải mã lỗi)"
    if len(plain) < 8:
        return plain[:3] + "•••" + plain[-3:] if len(plain) >= 6 else "•••"
    return plain[:4] + "•••" + plain[-3:]


def encrypt_phone(plain: str) -> str:
    return encrypt_aes_gcm(plain)