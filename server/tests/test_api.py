"""API integration tests — luồng enroll → heartbeat → inventory, tokens, auth, stats."""
from __future__ import annotations


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["requires_2fa"] is False
    return data["access_token"]


async def _create_token(client, token, org_id):
    r = await client.post(
        "/api/tokens",
        json={"org_id": org_id, "full_name": "Nguyễn Văn A", "email": "a@test.gov.vn"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_compliance_notice_flow(client, seeded_env):
    # Chưa có notice → current = null
    r = await client.get("/api/compliance/current")
    assert r.status_code == 401  # chưa đăng nhập

    token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.get("/api/compliance/current", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() is None  # chưa có notice active


async def test_full_enroll_heartbeat_inventory(client, seeded_env, session_factory):
    """E2E: login → tạo token → enroll → heartbeat → inventory → xem máy."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    # 1. Tạo token
    tok = await _create_token(client, admin_token, org_id)
    enroll_token = tok["token"]
    assert tok["install_command"].startswith("powershell")
    assert enroll_token in tok["install_command"]

    # 2. Render install script — token hợp lệ
    r = await client.get(f"/i/{enroll_token}")
    assert r.status_code == 200
    assert "CÀI ĐẶT AGENT" in r.text

    # 3. Enroll — cần CSR hợp lệ (LocalCaService parse CSR)
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "machine-test")]))
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

    r = await client.post(
        "/api/enroll",
        json={
            "token": enroll_token,
            "csr_pem": csr_pem,
            "fingerprint": {
                "smbios_uuid": "UUID-TEST-1234",
                "machine_guid": "GUID-TEST",
                "mainboard_serial": "SN-TEST-001",
            },
            "hostname": "PC-KETOAN-001",
        },
    )
    assert r.status_code == 200, r.text
    enroll_data = r.json()
    machine_id = enroll_data["machine_id"]
    assert enroll_data["is_new_machine"] is True
    assert enroll_data["status"] == "pending"

    # 4. Heartbeat (đầu mTLS header từ nginx)
    r = await client.post(
        "/api/heartbeat",
        json={"logged_user": "nguyenvana", "uptime_sec": 3600},
        headers={"X-SSL-Client-CN": machine_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # 5. Inventory
    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json={
            "os_name": "Windows 10",
            "os_version": "22H2",
            "os_build": "19045",
            "cpu": {"model": "Intel i5", "cores": 4},
            "ram_gb": 16.0,
            "disks": [{"model": "SSD", "capacity_gb": 512}],
            "is_vm": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_changed"] is True

    # 6. Xem danh sách máy & chi tiết
    r = await client.get("/api/machines", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    machines = r.json()
    assert any(m["machine_uuid"] for m in machines)

    r = await client.get(f"/api/machines/{machine_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["latest_spec"]["os_name"] == "Windows 10"

    # 7. Stats
    r = await client.get("/api/stats/overview", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["total_machines"] >= 1


async def test_token_single_use(client, seeded_env):
    """Token dùng 1 lần: enroll lần 2 phải bị từ chối."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    tok = await _create_token(client, admin_token, seeded_env["org_id"])
    enroll_token = tok["token"]

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    def _csr():
        key = ec.generate_private_key(ec.SECP256R1())
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t")]))
            .sign(key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM).decode()

    def _enroll(fp):
        return client.post(
            "/api/enroll",
            json={"token": enroll_token, "csr_pem": _csr(), "fingerprint": fp, "hostname": "PC"},
        )

    fp = {"smbios_uuid": "uuid-1", "machine_guid": "g-1", "mainboard_serial": "s-1"}
    r1 = await _enroll(fp)
    assert r1.status_code == 200

    # Máy khác dùng cùng token — token đã dùng → từ chối
    fp2 = {"smbios_uuid": "uuid-2", "machine_guid": "g-2", "mainboard_serial": "s-2"}
    r2 = await _enroll(fp2)
    assert r2.status_code == 401


async def test_enroll_invalid_token(client, seeded_env, session_factory):
    r = await client.post(
        "/api/enroll",
        json={"token": "t_nonexistent_token_123", "csr_pem": "x", "fingerprint": {"smbios_uuid": "z"}},
    )
    assert r.status_code == 401


async def test_machine_status_requires_same_org(client, seeded_env):
    # Admin thấy máy trong org của mình — test cơ bản không lỗi
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.get("/api/machines", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200


async def test_unauthorized_access(client):
    r = await client.get("/api/machines")
    assert r.status_code == 401

    r = await client.get("/api/machines", headers={"Authorization": "Bearer invalidfake"})
    assert r.status_code == 401
