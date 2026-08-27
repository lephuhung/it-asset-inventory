"""Server Crypto Service — Quản lý cặp khóa RSA của Server và giải mã gói offline (Phase 3).

Mô hình mã hóa lai (Hybrid Encryption):
1. Agent tại máy cách ly:
   - Sinh ngẫu nhiên khóa đối xứng AES-256 (32 bytes) + IV (12 bytes).
   - Mã hóa nội dung inventory.json bằng AES-256-GCM.
   - Mã hóa khóa AES-256 bằng RSA Server Public Key (chuẩn OAEP SHA-256).
   - Đóng gói ZIP gồm: manifest.json, encrypted_payload.bin, encrypted_key.bin, iv.bin, tag.bin, signature.sig, public_key.pem.
2. Server tại Backend:
   - Dùng RSA Server Private Key giải mã ra khóa AES-256.
   - Dùng khóa AES-256 giải mã AES-256-GCM ra inventory.json.
   - Verify chữ ký số ECDSA của Agent trên inventory.json.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

logger = logging.getLogger("server_crypto")

_CACHED_PRIVATE_KEY: rsa.RSAPrivateKey | None = None
_CACHED_PUBLIC_KEY_PEM: str | None = None


def get_or_create_server_keys() -> tuple[rsa.RSAPrivateKey, str]:
    """Lấy hoặc tự động tạo cặp khóa RSA 2048-bit cho Server."""
    global _CACHED_PRIVATE_KEY, _CACHED_PUBLIC_KEY_PEM

    if _CACHED_PRIVATE_KEY is not None and _CACHED_PUBLIC_KEY_PEM is not None:
        return _CACHED_PRIVATE_KEY, _CACHED_PUBLIC_KEY_PEM

    priv_path = Path(settings.server_private_key_path).resolve()
    pub_path = Path(settings.server_public_key_path).resolve()

    if priv_path.exists() and pub_path.exists():
        try:
            priv_bytes = priv_path.read_bytes()
            pub_pem = pub_path.read_text(encoding="utf-8")
            private_key = serialization.load_pem_private_key(priv_bytes, password=None)
            if isinstance(private_key, rsa.RSAPrivateKey):
                _CACHED_PRIVATE_KEY = private_key
                _CACHED_PUBLIC_KEY_PEM = pub_pem
                return private_key, pub_pem
        except Exception as ex:
            logger.warning("Không đọc được khóa Server RSA từ disk: %s. Sẽ tạo lại cặp khóa mới.", ex)

    # Sinh cặp khóa RSA 2048-bit mới
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    try:
        priv_path.parent.mkdir(parents=True, exist_ok=True)
        priv_path.write_bytes(priv_bytes)
        pub_path.write_text(pub_pem, encoding="utf-8")
        logger.info("Đã khởi tạo và lưu cặp khóa Server RSA tại %s và %s", priv_path, pub_path)
    except Exception as ex:
        logger.error("Không thể ghi file khóa Server RSA ra disk: %s", ex)

    _CACHED_PRIVATE_KEY = private_key
    _CACHED_PUBLIC_KEY_PEM = pub_pem
    return private_key, pub_pem


def get_server_public_key_pem() -> str:
    """Trả về khóa công khai của Server dạng PEM."""
    _, pub_pem = get_or_create_server_keys()
    return pub_pem


def decrypt_offline_bundle(zip_bytes: bytes) -> dict:
    """Giải mã gói ZIP mã hóa từ máy cách ly.

    Trả về dict gồm:
    - payload: dict cấu hình inventory.json
    - signature_b64: chuỗi chữ ký số ECDSA base64
    - public_key_pem: khóa công khai ECDSA của máy trạm
    - manifest: dict metadata từ manifest.json
    """
    private_key, _ = get_or_create_server_keys()

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            file_names = set(zf.namelist())

            # Kiểm tra các file bắt buộc trong ZIP
            required_files = {"encrypted_key.bin", "encrypted_payload.bin", "iv.bin", "tag.bin", "signature.sig", "public_key.pem"}
            missing = required_files - file_names
            if missing:
                raise ValueError(f"Gói ZIP thiếu các tệp tin bắt buộc: {', '.join(missing)}")

            enc_key_bytes = zf.read("encrypted_key.bin")
            enc_payload_bytes = zf.read("encrypted_payload.bin")
            iv_bytes = zf.read("iv.bin")
            tag_bytes = zf.read("tag.bin")
            signature_raw = zf.read("signature.sig").decode("utf-8").strip()
            public_key_pem = zf.read("public_key.pem").decode("utf-8").strip()

            manifest_dict = {}
            if "manifest.json" in file_names:
                try:
                    manifest_dict = json.loads(zf.read("manifest.json").decode("utf-8"))
                except Exception:
                    pass

    except zipfile.BadZipFile as ex:
        raise ValueError(f"Tệp tin tải lên không phải là file ZIP hợp lệ: {ex}") from ex

    # 1. Giải mã RSA-OAEP lấy khóa đối xứng AES-256
    try:
        session_key = private_key.decrypt(
            enc_key_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    except Exception as ex:
        raise ValueError("Không thể giải mã khóa phiên AES (khóa Server không khớp hoặc file bị hỏng)") from ex

    # 2. Giải mã AES-256-GCM lấy nội dung inventory.json
    try:
        aesgcm = AESGCM(session_key)
        # Trong cryptography.hazmat, AESGCM.decrypt nhận data = ciphertext + tag
        data_to_decrypt = enc_payload_bytes + tag_bytes
        decrypted_bytes = aesgcm.decrypt(iv_bytes, data_to_decrypt, None)
        payload_json = json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as ex:
        raise ValueError("Giải mã AES-GCM thất bại (dữ liệu payload bị thay đổi hoặc tag không khớp)") from ex

    return {
        "payload": payload_json,
        "signature_b64": signature_raw,
        "public_key_pem": public_key_pem,
        "manifest": manifest_dict,
    }
