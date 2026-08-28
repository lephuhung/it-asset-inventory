"""Test endpoint đổi mật khẩu của chính mình (POST /api/auth/change-password).

Yêu cầu mật khẩu hiện tại (chống chiếm đoạt phiên), ghi audit log, không được
giống mật khẩu cũ.
"""
from __future__ import annotations


async def _login(client, email: str, password: str) -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_change_password_success(client, seeded_env):
    """Đổi mật khẩu với current đúng → 200, có thể login bằng mật khẩu mới."""
    email = seeded_env["email"]
    old_pass = seeded_env["password"]
    new_pass = "NewSecure!Pass123"

    tok = await _login(client, email, old_pass)
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {tok}"},
        json={"current_password": old_pass, "new_password": new_pass},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # Đăng nhập lại bằng mật khẩu mới
    r2 = await client.post("/api/auth/login", json={"email": email, "password": new_pass})
    assert r2.status_code == 200, r2.text

    # Reset về mật khẩu cũ để test khác không bị ảnh hưởng
    new_tok = r2.json()["access_token"]
    r3 = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {new_tok}"},
        json={"current_password": new_pass, "new_password": old_pass},
    )
    assert r3.status_code == 200, r3.text


async def test_change_password_wrong_current(client, seeded_env):
    """current_password sai → 401 (chống brute-force mật khẩu)."""
    tok = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {tok}"},
        json={"current_password": "wrong-password-xyz", "new_password": "NewSecure!Pass456"},
    )
    assert r.status_code == 401, r.text
    assert "không đúng" in r.json()["detail"].lower()


async def test_change_password_same_as_current(client, seeded_env):
    """new_password giống current → 400 (yêu cầu khác để tránh no-op)."""
    tok = await _login(client, seeded_env["email"], seeded_env["password"])
    pwd = seeded_env["password"]
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {tok}"},
        json={"current_password": pwd, "new_password": pwd},
    )
    assert r.status_code == 400, r.text


async def test_change_password_too_short(client, seeded_env):
    """new_password < 8 ký tự → 422 (schema validation)."""
    tok = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {tok}"},
        json={"current_password": seeded_env["password"], "new_password": "short"},
    )
    assert r.status_code == 422, r.text


async def test_change_password_requires_auth(client):
    """Không có Bearer token → 401."""
    r = await client.post(
        "/api/auth/change-password",
        json={"current_password": "x", "new_password": "NewSecure!Pass789"},
    )
    assert r.status_code == 401, r.text


async def test_change_password_writes_audit(client, seeded_env):
    """Đổi mật khẩu ghi audit log với action='auth.change_password'."""
    from sqlalchemy import select

    from app.db.models import AuditLog

    tok = await _login(client, seeded_env["email"], seeded_env["password"])
    old_pass = seeded_env["password"]
    new_pass = "AuditTest!Pass321"
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {tok}"},
        json={"current_password": old_pass, "new_password": new_pass},
    )
    assert r.status_code == 200

    # Kiểm tra audit log
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AuditLog).where(AuditLog.action == "auth.change_password").order_by(AuditLog.id.desc())
        )).scalars().all()
        assert len(rows) >= 1, "Không tìm thấy audit log 'auth.change_password'"
        latest = rows[0]
        assert latest.target == latest.actor, "Audit log target phải = actor (self)"

    # Reset
    new_tok = (await client.post("/api/auth/login", json={"email": seeded_env["email"], "password": new_pass})).json()[
        "access_token"
    ]
    await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {new_tok}"},
        json={"current_password": new_pass, "new_password": old_pass},
    )