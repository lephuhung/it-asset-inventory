"""Test gán người dùng cho máy (sau khi upload ZIP cách ly)."""
from __future__ import annotations

import uuid
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _enroll_machine_offline(client, admin_token, org_id) -> str:
    """Tạo 1 máy qua flow offline — trả machine_id."""
    from app.api.routes.enroll import perform_enroll  # noqa
    # Tạo token
    r = await client.post(
        "/api/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"org_id": str(org_id), "ttl_hours": 72},
    )
    assert r.status_code == 200, r.text
    enroll_token = r.json()["token"]

    # Enroll qua API (giả lập agent online)
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "machine-assign-test")]))
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()
    r = await client.post(
        "/api/enroll",
        json={
            "token": enroll_token,
            "csr_pem": csr_pem,
            "fingerprint": {"smbios_uuid": "UUID-ASSIGN-TEST", "machine_guid": "G-ASSIGN", "mainboard_serial": "SN-ASSIGN"},
            "hostname": "PC-ASSIGN-TEST",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["machine_id"]


async def test_assign_user_with_existing(client, seeded_env):
    """Gán 1 user có sẵn cho máy — happy path."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    # Tạo 1 user trong cùng org
    user_resp = await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "user-existing@test.gov.vn",
            "full_name": "Nguyễn Văn A",
            "role": "viewer",
            "org_id": seeded_env["org_id"],
            "password": "temp-password-123",
        },
    )
    assert user_resp.status_code == 201, user_resp.text
    user_id = user_resp.json()["id"]

    # Gán user cho máy
    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "existing", "user_id": user_id},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["machine_id"] == machine_id
    assert data["assigned_user_id"] == user_id
    assert data["assigned_user_name"] == "Nguyễn Văn A"
    assert data["was_created"] is False
    assert data["phone_masked"] is None  # user mới không có phone

    # Verify máy đã liên kết
    r = await client.get(
        f"/api/machines/{machine_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["assigned_user_name"] == "Nguyễn Văn A"


async def test_assign_user_with_new(client, seeded_env):
    """Tạo user mới + gán cho máy — flow chuẩn sau khi upload ZIP."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "mode": "new",
            "full_name": "Trần Thị B",
            "email": "tranb2@test.gov.vn",
            "phone": "0987654321",
            "department": "Phòng Kế toán",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["was_created"] is True
    assert data["assigned_user_name"] == "Trần Thị B"
    assert data["phone_masked"] == "0987•••321"


async def test_assign_user_duplicate_email(client, seeded_env):
    """Email trùng → 409."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    # Tạo user A
    r = await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "dup@test.gov.vn",
            "full_name": "User A",
            "role": "viewer",
            "org_id": seeded_env["org_id"],
            "password": "temp-password-123",
        },
    )
    assert r.status_code == 201

    # Cố tạo user B với cùng email qua mode=new
    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "new", "full_name": "User B", "email": "dup@test.gov.vn"},
    )
    assert r.status_code == 409, r.text
    assert "đã thuộc về user khác" in r.json()["detail"]


async def test_assign_user_requires_admin(client, seeded_env):
    """Viewer không được gán user (chỉ admin)."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    # Tạo viewer user
    r = await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "viewer-assign@test.gov.vn",
            "full_name": "Viewer Test",
            "role": "viewer",
            "org_id": seeded_env["org_id"],
            "password": "temp-password-123",
        },
    )
    assert r.status_code == 201
    viewer_token_resp = await client.post(
        "/api/auth/login", json={"email": "viewer-assign@test.gov.vn", "password": "temp-password-123"}
    )
    viewer_token = viewer_token_resp.json()["access_token"]

    # Viewer không gán được
    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"mode": "new", "full_name": "X", "email": "x@x.com"},
    )
    assert r.status_code == 403


async def test_assign_user_existing_requires_user_id(client, seeded_env):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "existing"},
    )
    assert r.status_code == 400, r.text
    assert "user_id" in r.json()["detail"]


async def test_assign_user_new_requires_full_name_and_email(client, seeded_env):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "new", "full_name": "Test"},
    )
    assert r.status_code == 400, r.text
    assert "email" in r.json()["detail"]


async def test_assign_user_replaces_old_user(client, seeded_env):
    """Gán user mới sẽ thayế user cũ."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    # Tạo 2 user
    u1 = (await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "u1@test.gov.vn", "full_name": "User 1", "role": "viewer", "org_id": seeded_env["org_id"], "password": "temp-password-123"},
    )).json()
    u2 = (await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "u2@test.gov.vn", "full_name": "User 2", "role": "viewer", "org_id": seeded_env["org_id"], "password": "temp-password-123"},
    )).json()

    # Gán u1
    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "existing", "user_id": u1["id"]},
    )
    assert r.status_code == 200

    # Gán u2 (đè lên)
    r = await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "existing", "user_id": u2["id"]},
    )
    assert r.status_code == 200
    assert r.json()["assigned_user_name"] == "User 2"


async def test_unassign_user(client, seeded_env):
    """Gỡ user khỏi máy."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    u = (await client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "unassign@test.gov.vn", "full_name": "Unassign Test", "role": "viewer", "org_id": seeded_env["org_id"], "password": "temp-password-123"},
    )).json()

    await client.post(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "existing", "user_id": u["id"]},
    )

    # Unassign
    r = await client.delete(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text

    # Verify máy không còn user
    r = await client.get(
        f"/api/machines/{machine_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["assigned_user_name"] is None


async def test_unassign_user_when_none_assigned(client, seeded_env):
    """Gỡ user khi máy chưa gán → 404."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine_offline(client, admin_token, seeded_env["org_id"])

    r = await client.delete(
        f"/api/machines/{machine_id}/assign-user",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404
