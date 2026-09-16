"""Refresh token rotation / revocation / reuse detection + TOTP replay."""
from __future__ import annotations

from sqlalchemy import select

from app.db.models import RefreshToken, User


async def _login(client, email, password, totp_code=None):
    body = {"email": email, "password": password}
    if totp_code:
        body["totp_code"] = totp_code
    r = await client.post("/api/auth/login", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _refresh(client, refresh_token):
    return await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})


async def test_refresh_rotates_token_and_keeps_family(client, session_factory, seeded_env):
    tokens = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await _refresh(client, tokens["refresh_token"])
    assert r.status_code == 200, r.text
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != tokens["refresh_token"]

    async with session_factory() as s:
        rows = (await s.execute(select(RefreshToken))).scalars().all()
        assert len(rows) == 2
        by_hash_old = next(rw for rw in rows if rw.revoked_at is not None)
        by_hash_new = next(rw for rw in rows if rw.revoked_at is None)
        # Rotation: cùng family, token cũ trỏ sang token mới
        assert by_hash_old.family_id == by_hash_new.family_id
        assert by_hash_old.replaced_by == by_hash_new.id


async def test_refresh_reuse_revokes_whole_family(client, session_factory, seeded_env):
    tokens = await _login(client, seeded_env["email"], seeded_env["password"])
    r1 = await _refresh(client, tokens["refresh_token"])
    assert r1.status_code == 200

    # Replay token cũ → reuse detected → toàn bộ family bị thu hồi
    r_replay = await _refresh(client, tokens["refresh_token"])
    assert r_replay.status_code == 401

    # Token mới (hợp lệ về mặt chữ ký) cũng chết theo family
    r2 = await _refresh(client, r1.json()["refresh_token"])
    assert r2.status_code == 401

    async with session_factory() as s:
        rows = (await s.execute(select(RefreshToken))).scalars().all()
        assert all(rw.revoked_at is not None for rw in rows)


async def test_logout_revokes_refresh_token(client, seeded_env):
    tokens = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=_auth(tokens["access_token"]),
    )
    assert r.status_code == 200, r.text
    assert (await _refresh(client, tokens["refresh_token"])).status_code == 401


async def test_change_password_revokes_refresh_sessions(client, seeded_env):
    tokens = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/auth/change-password",
        json={"current_password": seeded_env["password"], "new_password": "NewPass!456"},
        headers=_auth(tokens["access_token"]),
    )
    assert r.status_code == 200, r.text
    assert (await _refresh(client, tokens["refresh_token"])).status_code == 401

    # Đăng nhập lại bằng mật khẩu mới vẫn hoạt động
    tokens2 = await _login(client, seeded_env["email"], "NewPass!456")
    assert tokens2["access_token"]


async def _seed_2fa(session_factory, user_id: str, secret: str = "JBSWY3DPEHPK3PXP", backup=None):
    from app.core.security import encrypt_aes_gcm

    async with session_factory() as s:
        user = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
        user.is_2fa_enabled = True
        user.totp_secret_encrypted = encrypt_aes_gcm(secret)
        user.backup_codes = backup
        await s.commit()


async def test_totp_code_cannot_be_replayed(client, session_factory, seeded_env):
    import pyotp

    secret = "JBSWY3DPEHPK3PXP"
    await _seed_2fa(session_factory, seeded_env["admin_id"], secret)
    code = pyotp.TOTP(secret).now()

    first = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"], "totp_code": code},
    )
    assert first.status_code == 200, first.text
    assert first.json()["access_token"]

    # Cùng mã, lần thứ 2 → counter đã dùng → từ chối
    second = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"], "totp_code": code},
    )
    assert second.status_code == 401


async def test_backup_code_consumed_once(client, session_factory, seeded_env):
    from app.core.security import hash_password

    await _seed_2fa(
        session_factory, seeded_env["admin_id"], backup=[hash_password("BACKUP1234")]
    )

    first = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"], "totp_code": "BACKUP1234"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["access_token"]

    # Backup code dùng lại → đã bị gỡ khỏi danh sách → 401
    second = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"], "totp_code": "BACKUP1234"},
    )
    assert second.status_code == 401
