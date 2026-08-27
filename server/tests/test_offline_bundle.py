"""Test Offline Bundle (Phase 3 1-Click): Hybrid Encryption AES-GCM + RSA, digital signature ECDSA, ZIP upload."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from app.services.server_crypto import decrypt_offline_bundle, get_or_create_server_keys


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _create_mock_offline_bundle(
    payload: dict,
    agent_private_key: ec.EllipticCurvePrivateKey,
    server_public_key_pem: str,
    manifest: dict | None = None,
) -> bytes:
    """Tạo gói ZIP mã hóa theo đúng chuẩn C# OfflineBundleExporter."""
    # 1. Ký số ECDSA trên canonical JSON
    canonical_bytes = _canonical_json(payload)
    sig = agent_private_key.sign(hashlib.sha256(canonical_bytes).digest(), ec.ECDSA(hashes.SHA256()))
    sig_b64 = base64.b64encode(sig).decode("utf-8")

    agent_pub_pem = (
        agent_private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    # 2. Sinh AES-256 session key (32 bytes) + IV (12 bytes)
    session_key = os.urandom(32)
    iv = os.urandom(12)

    aesgcm = AESGCM(session_key)
    # encrypt trả về ciphertext + 16-byte tag nối ở cuối
    encrypted_data_with_tag = aesgcm.encrypt(iv, canonical_bytes, None)
    ciphertext = encrypted_data_with_tag[:-16]
    tag = encrypted_data_with_tag[-16:]

    # 3. Mã hóa session_key bằng Server RSA Public Key (OAEP SHA-256)
    server_pub = serialization.load_pem_public_key(server_public_key_pem.encode("utf-8"))
    assert isinstance(server_pub, rsa.RSAPublicKey)
    encrypted_key = server_pub.encrypt(
        session_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    # 4. Đóng gói ZIP
    zip_buf = io.BytesIO()
    manifest_data = manifest or {
        "machine_uuid": payload.get("machine_uuid", "mock-uuid"),
        "hostname": payload.get("hostname", "PC-OFFLINE"),
        "fingerprint": payload.get("fingerprint", {}),
        "exported_at": payload.get("exported_at", datetime.now(UTC).isoformat()),
    }

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest_data))
        zf.writestr("encrypted_payload.bin", ciphertext)
        zf.writestr("encrypted_key.bin", encrypted_key)
        zf.writestr("iv.bin", iv)
        zf.writestr("tag.bin", tag)
        zf.writestr("signature.sig", sig_b64)
        zf.writestr("public_key.pem", agent_pub_pem)

    return zip_buf.getvalue()


def test_decrypt_offline_bundle_unit():
    """Unit test kiểm tra giải mã và parse gói ZIP mã hóa."""
    _, server_pub_pem = get_or_create_server_keys()
    agent_key = ec.generate_private_key(ec.SECP256R1())

    test_payload = {
        "machine_uuid": "test-decrypt-uuid-001",
        "hostname": "PC-TEST-DECRYPT",
        "fingerprint": {"smbios_uuid": "SMBIOS-123"},
        "spec": {
            "os_name": "Windows 11 Pro 24H2",
            "cpu": {"model": "Intel Core i7-13700H"},
            "ram_gb": 32.0,
        },
        "exported_at": datetime.now(UTC).isoformat(),
    }

    zip_bytes = _create_mock_offline_bundle(test_payload, agent_key, server_pub_pem)
    result = decrypt_offline_bundle(zip_bytes)

    assert result["payload"] == test_payload
    assert result["signature_b64"] is not None
    assert "BEGIN PUBLIC KEY" in result["public_key_pem"]
    assert result["manifest"]["hostname"] == "PC-TEST-DECRYPT"


def test_decrypt_offline_bundle_invalid():
    """Giải mã gói ZIP hỏng hoặc sai khóa phải raise ValueError."""
    # 1. Byte rác không phải ZIP
    with pytest.raises(ValueError, match="không phải là file ZIP"):
        decrypt_offline_bundle(b"not a zip file")

    # 2. ZIP thiếu file
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("manifest.json", "{}")
    with pytest.raises(ValueError, match="thiếu các tệp tin bắt buộc"):
        decrypt_offline_bundle(zip_buf.getvalue())

    # 3. Mã hóa bằng RSA key khác không phải của server
    other_rsa = rsa.generate_private_key(65537, 2048)
    other_pub_pem = other_rsa.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    agent_key = ec.generate_private_key(ec.SECP256R1())

    zip_bytes = _create_mock_offline_bundle(
        {"machine_uuid": "x", "hostname": "x"}, agent_key, other_pub_pem
    )
    with pytest.raises(ValueError, match="Không thể giải mã khóa phiên AES"):
        decrypt_offline_bundle(zip_bytes)


async def test_offline_import_encrypted_zip_route(client, seeded_env):
    """Integration test upload file ZIP mã hóa qua POST /api/offline/import."""
    r = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Lấy server public key qua download route
    r_pub = await client.get("/download/server_public_key.pem")
    assert r_pub.status_code == 200
    server_pub_pem = r_pub.text

    agent_key = ec.generate_private_key(ec.SECP256R1())
    payload = {
        "machine_uuid": "offline-zip-machine-01",
        "hostname": "PC-AIRGAP-01",
        "org_id": seeded_env["org_id"],
        "fingerprint": {"smbios_uuid": "AIRGAP-UUID-001", "machine_guid": "GUID-001"},
        "spec": {
            "os_name": "Windows 11 Pro 23H2",
            "os_version": "10.0.22631",
            "os_build": "22631",
            "cpu": {"model": "Intel Core i7-12700"},
            "ram_gb": 16.0,
            "installed_software": [{"display_name": "Office 2021", "version": "16.0"}],
        },
        "exported_at": datetime.now(UTC).isoformat(),
    }

    zip_bytes = _create_mock_offline_bundle(payload, agent_key, server_pub_pem)

    # Gửi qua multipart/form-data
    files = {"file": ("INVENTORY_PC-AIRGAP-01.zip", zip_bytes, "application/zip")}
    r_import = await client.post("/api/offline/import", files=files, headers=headers)
    assert r_import.status_code == 200, r_import.text
    data = r_import.json()

    assert data["hostname"] == "PC-AIRGAP-01"
    assert data["verified"] is True
    assert data["decrypted"] is True
    assert data["is_new"] is True

    # Import lần 2 (cập nhật máy cũ)
    r_import2 = await client.post("/api/offline/import", files=files, headers=headers)
    assert r_import2.status_code == 200
    data2 = r_import2.json()
    assert data2["is_new"] is False


async def test_download_offline_package_route(client):
    """Test endpoint tải trọn gói offline package ZIP."""
    r = await client.get("/download/offline-package.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    # Verify nội dung package có server_public_key.pem và install-offline.cmd
    with zipfile.ZipFile(io.BytesIO(r.content), "r") as zf:
        names = zf.namelist()
        assert "server_public_key.pem" in names
        assert "install-offline.cmd" in names
        assert "install-offline.ps1" in names
        assert "offline_config.json" in names
