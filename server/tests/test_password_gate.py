"""Test cổng bắt buộc đổi mật khẩu lần đầu + theo dõi kích hoạt tài khoản.

Hợp đồng quan sát được:
- Tài khoản seed / do admin tạo / vừa được reset mật khẩu → `must_change_password=True`.
- Login thành công ghi `last_login_at` và trả cờ `must_change_password`.
- User bị gắn cờ: mọi API trả 403 PASSWORD_CHANGE_REQUIRED, trừ me/change-password/logout.
- Đổi mật khẩu thành công → gỡ cờ, dùng API bình thường.
- GET /api/users expose `last_login_at` + `must_change_password` và lọc `activated`.
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User, UserRole

ORG_ADMIN_PASSWORD = "Hatinh@123"


async def _login_raw(client, email, password):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def _create_flagged_org_admin(client, session_factory, org_id, email="quanthi@hatinh.gov.vn"):
    """Tạo org_admin giống hệt seed: mật khẩu mặc định + cờ bắt đổi mật khẩu."""
    async with session_factory() as s:
        user = User(
            org_id=org_id,
            full_name="Quản trị viên UBND xã Quan Thị",
            email=email,
            role=UserRole.ORG_ADMIN.value,
            password_hash=hash_password(ORG_ADMIN_PASSWORD),
            is_active=True,
            must_change_password=True,
        )
        s.add(user)
        await s.commit()
        return str(user.id)


async def _get_user(session_factory, email) -> User:
    async with session_factory() as s:
        return (await s.execute(select(User).where(User.email == email))).scalar_one()


async def test_login_marks_activation_and_returns_flag(client, seeded_env, session_factory):
    """Tài khoản seed đăng nhập lần đầu → last_login_at được ghi + response báo phải đổi MK."""
    await _create_flagged_org_admin(client, session_factory, seeded_env["org_id"])

    r = await _login_raw(client, "quanthi@hatinh.gov.vn", ORG_ADMIN_PASSWORD)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["must_change_password"] is True
    assert data["access_token"]

    user = await _get_user(session_factory, "quanthi@hatinh.gov.vn")
    assert user.last_login_at is not None  # đã kích hoạt


async def test_flagged_user_blocked_until_password_changed(client, seeded_env, session_factory):
    """Bị cờ → mọi API 403 PASSWORD_CHANGE_REQUIRED; đổi MK xong → dùng bình thường."""
    await _create_flagged_org_admin(client, session_factory, seeded_env["org_id"])
    token = (await _login_raw(client, "quanthi@hatinh.gov.vn", ORG_ADMIN_PASSWORD)).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # API nghiệp vụ bị chặn
    r = await client.get("/api/machines", headers=h)
    assert r.status_code == 403
    assert r.json()["detail"] == "PASSWORD_CHANGE_REQUIRED"

    # /me vẫn mở để portal đọc trạng thái
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    assert r.json()["last_login_at"] is not None

    # Đổi mật khẩu bằng mật khẩu mặc định hiện tại
    r = await client.post(
        "/api/auth/change-password",
        headers=h,
        json={"current_password": ORG_ADMIN_PASSWORD, "new_password": "MatKhauMoi@2026"},
    )
    assert r.status_code == 200, r.text

    # Cờ đã gỡ → API nghiệp vụ mở lại
    r = await client.get("/api/machines", headers=h)
    assert r.status_code == 200, r.text

    # Login lại bằng mật khẩu mới → không còn bị báo đổi MK
    r = await _login_raw(client, "quanthi@hatinh.gov.vn", "MatKhauMoi@2026")
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is False


async def test_change_password_rejects_default_as_new(client, seeded_env, session_factory):
    """Không được 'đổi' sang chính mật khẩu mặc định (vòng lặp vô nghĩa)."""
    await _create_flagged_org_admin(client, session_factory, seeded_env["org_id"])
    token = (await _login_raw(client, "quanthi@hatinh.gov.vn", ORG_ADMIN_PASSWORD)).json()["access_token"]

    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": ORG_ADMIN_PASSWORD, "new_password": ORG_ADMIN_PASSWORD},
    )
    assert r.status_code == 400


async def test_admin_create_and_reset_force_password_change(client, seeded_env, session_factory):
    """User do Super Admin tạo / reset MK đều bị buộc đổi mật khẩu ở lần đăng nhập tới."""
    r = await _login_raw(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # Tạo user mới → phải có cờ
    r = await client.post(
        "/api/users",
        headers=h,
        json={
            "email": "newbie@test.gov.vn",
            "full_name": "User Mới",
            "role": "viewer",
            "org_id": seeded_env["org_id"],
            "password": "CapTam@123",
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["must_change_password"] is True

    # User mới login → bị chặn API
    r = await _login_raw(client, "newbie@test.gov.vn", "CapTam@123")
    assert r.json()["must_change_password"] is True
    tok_new = r.json()["access_token"]
    r = await client.get("/api/machines", headers={"Authorization": f"Bearer {tok_new}"})
    assert r.status_code == 403

    # User tự gỡ cờ
    r = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {tok_new}"},
        json={"current_password": "CapTam@123", "new_password": "TuDat@456"},
    )
    assert r.status_code == 200

    # Admin reset lại mật khẩu → cờ bật lại
    r = await client.post(
        f"/api/users/{uid}/reset-password",
        headers=h,
        json={"new_password": "ResetBoi@789"},
    )
    assert r.status_code == 200
    user = await _get_user(session_factory, "newbie@test.gov.vn")
    assert user.must_change_password is True


async def test_users_list_exposes_activation_and_filter(client, seeded_env, session_factory):
    """Super Admin thấy tài khoản nào đã kích hoạt; lọc activated=true/false."""
    await _create_flagged_org_admin(client, session_factory, seeded_env["org_id"])
    # Kích hoạt tài khoản bằng 1 lần login
    await _login_raw(client, "quanthi@hatinh.gov.vn", ORG_ADMIN_PASSWORD)

    token = (await _login_raw(client, seeded_env["email"], seeded_env["password"])).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/users", headers=h)
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()["items"]}
    org_admin = by_email["quanthi@hatinh.gov.vn"]
    assert org_admin["last_login_at"] is not None
    assert org_admin["must_change_password"] is True
    super_admin = by_email[seeded_env["email"]]
    assert super_admin["last_login_at"] is not None
    assert super_admin["must_change_password"] is False

    # activated=true → chỉ tài khoản đã đăng nhập
    r = await client.get("/api/users", headers=h, params={"activated": "true"})
    emails = {u["email"] for u in r.json()["items"]}
    assert "quanthi@hatinh.gov.vn" in emails

    # activated=false → chỉ tài khoản chưa đăng nhập (org admin vừa login không được xuất hiện)
    r = await client.get("/api/users", headers=h, params={"activated": "false"})
    emails = {u["email"] for u in r.json()["items"]}
    assert "quanthi@hatinh.gov.vn" not in emails


async def test_seed_org_admins_marks_must_change_password(client, seeded_env, session_factory):
    """Seed thật (seed_org_admins) → tài khoản tạo ra phải có cờ bắt đổi MK, chưa kích hoạt."""
    from app.db.seed_org_admins import seed_org_admins
    from app.db.seed_orgs import seed_all

    async with session_factory() as s:
        await seed_all(s, commit=False)
        result = await seed_org_admins(s, commit=True)
    assert result["created"] > 0

    async with session_factory() as s:
        seeded = (
            (await s.execute(select(User).where(User.role == UserRole.ORG_ADMIN.value))).scalars().all()
        )
    assert len(seeded) == result["created"]
    for u in seeded:
        assert u.must_change_password is True
        assert u.last_login_at is None  # chưa kích hoạt
