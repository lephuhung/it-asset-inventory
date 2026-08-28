"""Test quản trị tài khoản (Super Admin): tạo user, cấp quyền, reset password."""
from __future__ import annotations

import uuid


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _create_org(session_factory, name="UBND Quận Test"):
    from sqlalchemy import select

    from app.db.models import Organization

    async with session_factory() as s:
        org = Organization(name=name, type="so_ban_nganh")
        s.add(org)
        await s.commit()
        return str(org.id)


async def test_users_requires_super_admin(client, seeded_env):
    # viewer/admin thường không được gọi
    r = await client.get("/api/users")
    assert r.status_code in (401, 403)


async def test_create_and_list_user(client, seeded_env, session_factory):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}
    org_id = await _create_org(session_factory)

    # Tạo user org_admin
    r = await client.post(
        "/api/users",
        headers=h,
        json={
            "email": "admin2@test.gov.vn",
            "full_name": "Admin Cơ quan 2",
            "role": "org_admin",
            "org_id": org_id,
            "password": "MatKhau@123",
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["email"] == "admin2@test.gov.vn"
    assert created["role"] == "org_admin"
    assert created["org_name"] == "UBND Quận Test"
    uid = created["id"]

    # List users — phải có
    r = await client.get("/api/users", headers=h)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()["items"]]
    assert "admin2@test.gov.vn" in emails

    # Trùng email → 409
    r = await client.post(
        "/api/users",
        headers=h,
        json={
            "email": "admin2@test.gov.vn",
            "full_name": "X",
            "role": "viewer",
            "org_id": org_id,
            "password": "MatKhau@123",
        },
    )
    assert r.status_code == 409


async def test_reset_password_and_login(client, seeded_env, session_factory):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}
    org_id = await _create_org(session_factory)

    r = await client.post(
        "/api/users",
        headers=h,
        json={
            "email": "user3@test.gov.vn",
            "full_name": "User Ba",
            "role": "viewer",
            "org_id": org_id,
            "password": "OldPass@123",
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    # Reset password
    r = await client.post(
        f"/api/users/{uid}/reset-password",
        headers=h,
        json={"new_password": "NewPass@456"},
    )
    assert r.status_code == 200, r.text

    # Login với mật khẩu mới
    r = await client.post("/api/auth/login", json={"email": "user3@test.gov.vn", "password": "NewPass@456"})
    assert r.status_code == 200, r.text

    # Mật khẩu cũ không dùng được
    r = await client.post("/api/auth/login", json={"email": "user3@test.gov.vn", "password": "OldPass@123"})
    assert r.status_code == 401


async def test_update_role_and_deactivate(client, seeded_env, session_factory):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}
    org_id = await _create_org(session_factory)

    r = await client.post(
        "/api/users",
        headers=h,
        json={"email": "u4@test.gov.vn", "full_name": "U4", "role": "viewer", "org_id": org_id, "password": "Pass@1234"},
    )
    uid = r.json()["id"]

    # Nâng vai trò
    r = await client.patch(f"/api/users/{uid}", headers=h, json={"role": "org_admin"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "org_admin"

    # Khoá tài khoản
    r = await client.patch(f"/api/users/{uid}", headers=h, json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # User bị khoá không login được
    r = await client.post("/api/auth/login", json={"email": "u4@test.gov.vn", "password": "Pass@1234"})
    assert r.status_code == 401


async def test_cannot_demote_self(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}
    me = (await client.get("/api/auth/me", headers=h)).json()
    r = await client.patch(f"/api/users/{me['id']}", headers=h, json={"role": "viewer"})
    assert r.status_code == 400
