"""Tự phục vụ hồ sơ và 2FA trong modal tài khoản."""
from __future__ import annotations


async def _login(client, email: str, password: str) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_update_my_profile_changes_only_own_name(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])

    response = await client.patch(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Quản trị viên mới"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Quản trị viên mới"


async def test_disable_my_2fa_requires_current_password(client, seeded_env, session_factory):
    from sqlalchemy import select

    from app.core.security import encrypt_aes_gcm
    from app.db.models import User

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.id == seeded_env["admin_id"]))).scalar_one()
        user.is_2fa_enabled = True
        user.totp_secret_encrypted = encrypt_aes_gcm("JBSWY3DPEHPK3PXP")
        user.backup_codes = ["hash"]
        await db.commit()

    token = await _login(client, seeded_env["email"], seeded_env["password"])
    response = await client.post(
        "/api/auth/totp/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": seeded_env["password"]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.id == seeded_env["admin_id"]))).scalar_one()
        assert user.is_2fa_enabled is False
        assert user.totp_secret_encrypted is None
        assert user.backup_codes is None


async def test_disable_my_2fa_rejects_wrong_password(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])

    response = await client.post(
        "/api/auth/totp/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "not-my-password"},
    )

    assert response.status_code == 401, response.text
