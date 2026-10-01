"""Tests cho enroll attempts (máy xin vào bằng token cũ → hàng đợi duyệt)
và enforcement decline (máy decommissioned không tự online / không push inventory)."""
from __future__ import annotations

from datetime import UTC, datetime

FINGERPRINT = {
    "smbios_uuid": "4C4C4544-0042-3710-8031-B4C04F465032",
    "machine_guid": "b1f9a2c7-5d3e-4c8a-9f21-77e0d3a65b12",
    "mainboard_serial": "/K4YWX3/1CND8210X9H",
}


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _csr_pem() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "machine-attempt")]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


async def _enroll(client, token: str, fingerprint: dict, hostname: str = "PC-ATTEMPT"):
    return await client.post(
        "/api/enroll",
        json={"token": token, "csr_pem": _csr_pem(), "fingerprint": fingerprint, "hostname": hostname},
    )


async def test_used_token_enroll_records_attempt(client, seeded_env):
    """Enroll lần 2 bằng token ĐÃ DÙNG → 401 + attempt xuất hiện trong hàng đợi duyệt
    (trước đây 401 im lặng — admin không bao giờ thấy máy xin vào)."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])

    # Token 1: enroll thành công máy FINGERPRINT
    r = await client.post(
        "/api/tokens",
        json={"org_id": seeded_env["org_id"], "full_name": "Tester"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    tok1 = r.json()["token"]
    r = await _enroll(client, tok1, FINGERPRINT)
    assert r.status_code == 200, r.text

    # Token 2: chỉ dùng để có attempt "used" — enroll rồi chạy lại với chính nó
    r = await client.post(
        "/api/tokens",
        json={"org_id": seeded_env["org_id"], "full_name": "Tester 2"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    tok2 = r.json()["token"]
    # fp2 khác biệt hoàn toàn so với FINGERPRINT — tránh fuzzy-match (SequenceMatcher
    # ratio > 0.8 coi 2 fingerprint là cùng 1 máy thật).
    fp2 = {
        "smbios_uuid": "9F2D71B8-3A64-4E92-B05C-D81E6A7C43F0",
        "machine_guid": "e47c8b01-92ad-4f63-a8d5-2c6f1097be54",
        "mainboard_serial": "/P8TRQ7/2MNC5541L4K",
    }
    r = await _enroll(client, tok2, fp2, hostname="PC-USED-TOKEN")
    assert r.status_code == 200, r.text
    machine2_id = r.json()["machine_id"]

    # Chạy lại enroll với token 2 (đã used) → 401 + attempt
    r = await _enroll(client, tok2, fp2, hostname="PC-USED-TOKEN")
    assert r.status_code == 401, r.text
    assert "đã dùng" in r.json()["detail"].lower()

    # Attempt xuất hiện ở hàng đợi duyệt, kèm gợi ý máy khớp fingerprint
    r = await client.get(
        "/api/enroll/attempts?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    attempts = r.json()
    used_attempts = [a for a in attempts if a["token_status"] == "used"]
    assert len(used_attempts) == 1, f"Mong 1 attempt 'used', có: {attempts}"
    a = used_attempts[0]
    assert a["hostname"] == "PC-USED-TOKEN"
    assert a["matched_machine_id"] == machine2_id  # fingerprint khớp máy đã có
    assert a["org_name"] is not None

    # Dedupe: retry liên tiếp KHÔNG tạo thêm attempt
    await _enroll(client, tok2, fp2, hostname="PC-USED-TOKEN")
    r = await client.get(
        "/api/enroll/attempts?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    used_attempts = [a for a in r.json() if a["token_status"] == "used"]
    assert len(used_attempts) == 1


async def test_approve_attempt_issues_replacement_token(client, seeded_env):
    """Approve attempt → sinh token thay thế; enroll với token mới → ghép lại máy cũ."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])

    r = await client.post(
        "/api/tokens",
        json={"org_id": seeded_env["org_id"], "full_name": "Tester"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    tok = r.json()["token"]
    r = await _enroll(client, tok, FINGERPRINT, hostname="PC-REAPPROVE")
    machine_id = r.json()["machine_id"]

    # Lần 2 với chính token → attempt "used"
    r = await _enroll(client, tok, FINGERPRINT, hostname="PC-REAPPROVE")
    assert r.status_code == 401

    r = await client.get(
        "/api/enroll/attempts?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    attempt_id = r.json()[0]["id"]

    # Approve → token thay thế + install command
    r = await client.post(
        f"/api/enroll/attempts/{attempt_id}/approve",
        json={"note": "cấp lại cho phòng kế toán"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["attempt_id"] == attempt_id
    assert data["token"]
    assert data["install_command_linux"].startswith("curl")

    # Enroll bằng token thay thế → thành công, ghép về máy cũ (không tạo máy mới)
    r = await _enroll(client, data["token"], FINGERPRINT, hostname="PC-REAPPROVE")
    assert r.status_code == 200, r.text
    assert r.json()["machine_id"] == machine_id
    assert r.json()["is_new_machine"] is False

    # Attempt đã chuyển approved
    r = await client.get(
        "/api/enroll/attempts?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert all(a["id"] != attempt_id for a in r.json())


async def test_reject_attempt_blocks(client, seeded_env):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/tokens",
        json={"org_id": seeded_env["org_id"], "full_name": "Tester"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    tok = r.json()["token"]
    await _enroll(client, tok, FINGERPRINT)
    await _enroll(client, tok, FINGERPRINT)  # 401 → attempt

    r = await client.get(
        "/api/enroll/attempts?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    attempt_id = r.json()[0]["id"]

    r = await client.post(
        f"/api/enroll/attempts/{attempt_id}/reject",
        json={"note": "máy lạ"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        "/api/enroll/attempts?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert all(a["id"] != attempt_id for a in r.json())


async def test_declined_machine_stays_offline(client, seeded_env, session_factory):
    """Máy bị decline (decommissioned): heartbeat KHÔNG tự bật lại online,
    inventory bị từ chối 403."""
    from sqlalchemy import select

    from app.db.models import Machine

    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/tokens",
        json={"org_id": seeded_env["org_id"], "full_name": "Tester"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    tok = r.json()["token"]
    r = await _enroll(client, tok, FINGERPRINT, hostname="PC-DECLINED")
    machine_id = r.json()["machine_id"]

    # Admin decline máy (approve trước để ra khỏi pending, rồi reject)
    r = await client.post(
        f"/api/machines/{machine_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/machines/{machine_id}/reject",
        json={"note": "decline"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text

    # Heartbeat tiếp tục → 200 nhưng KHÔNG bật lại online
    r = await client.post(
        "/api/heartbeat",
        json={"logged_user": "x", "uptime_sec": 60},
        headers={"X-SSL-Client-CN": machine_id},
    )
    assert r.status_code == 200, r.text

    async with session_factory() as session:  # type: AsyncSession
        machine = (
            await session.execute(select(Machine).where(Machine.id == machine_id))
        ).scalar_one()
        assert machine.status == "decommissioned", (
            f"Máy bị decline không được tự online (status={machine.status})"
        )
        assert machine.last_seen_at is not None  # vẫn ghi nhận last_seen cho admin xem

    # Inventory → 403
    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json={
            "os_name": "Windows 11 Pro",
            "os_version": "10.0.22631",
            "os_build": "22631",
            "os_arch": "x86_64",
            "ram_gb": 16,
            "config_hash": f"declined-{datetime.now(UTC).timestamp()}",
        },
    )
    assert r.status_code == 403, r.text
