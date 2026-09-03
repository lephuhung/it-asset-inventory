"""Tests: seed tài khoản quản trị đơn vị (Org Admin)."""
from __future__ import annotations

from sqlalchemy import select

from app.core.security import verify_password
from app.db.models import Organization, OrgType, User, UserRole
from app.db.seed_org_admins import (
    DEFAULT_PASSWORD,
    SO_BAN_NGANH_MAP,
    USERNAME_ALIASES,
    get_all_unit_admin_specs,
    org_name_to_username,
    resolve_login_username,
    seed_org_admins,
)
from app.db.seed_orgs import SO_BAN_NGANH_NAMES, UBND_XA_NAMES, seed_all


def test_all_82_unit_usernames_unique():
    """Tất cả 82 đơn vị phải có tên đăng nhập duy nhất (0 va chạm)."""
    specs = get_all_unit_admin_specs()
    assert len(specs) == 82
    usernames = [s["username"] for s in specs]
    emails = [s["email"] for s in specs]
    assert len(set(usernames)) == 82, f"Va chạm username: {len(usernames) - len(set(usernames))}"
    assert len(set(emails)) == 82


def test_org_name_to_username():
    """Kiểm tra quy tắc chuyển đổi tên đơn vị thành username."""
    # UBND cấp xã có tiền tố "UBND xã "
    assert org_name_to_username("UBND xã Thạch Lạc") == "thachlac"
    assert org_name_to_username("UBND xã Đồng Tiến") == "dongtien"
    assert org_name_to_username("UBND xã Cẩm Xuyên") == "camxuyen"
    assert org_name_to_username("UBND xã Sơn Kim 1") == "sonkim1"
    # Tương thích nếu không có tiền tố
    assert org_name_to_username("Thạch Lạc") == "thachlac"

    # Phường
    assert org_name_to_username("Phường Thành Sen") == "phuongthanhsen"
    assert org_name_to_username("Phường Trần Phú") == "phuongtranphu"

    # Sở ban ngành
    assert org_name_to_username("Sở Khoa học và Công nghệ") == "skhcn"
    assert org_name_to_username("Khoa học và Công nghệ") == "skhcn"
    assert org_name_to_username("Sở Nội vụ") == "snv"
    assert org_name_to_username("Sở Tài chính") == "stc"
    assert org_name_to_username("Sở Xây dựng") == "sxd"
    assert org_name_to_username("Văn phòng UBND tỉnh") == "vpubnd"


def test_resolve_login_username_aliases():
    """Kiểm tra chuẩn hóa tên đăng nhập và alias."""
    # Email đầy đủ -> lấy phần trước @ và resolve
    assert resolve_login_username("thachlac@hatinh.gov.vn") == "thachlac"
    assert resolve_login_username("SKHCN@hatinh.gov.vn") == "skhcn"
    assert resolve_login_username("ubndxathachlac") == "thachlac"

    # Gõ không dấu / có dấu
    assert resolve_login_username("Thạch Lạc") == "thachlac"

    # Alias phường
    assert resolve_login_username("thanhsen") == "phuongthanhsen"
    assert resolve_login_username("tranphu") == "phuongtranphu"

    # Alias sở ban ngành
    assert resolve_login_username("khoahoccongnghe") == "skhcn"
    assert resolve_login_username("noivu") == "snv"
    assert resolve_login_username("sokhcn") == "skhcn"
    assert resolve_login_username("taichinh") == "stc"
    assert resolve_login_username("vanphongubnd") == "vpubnd"


async def test_seed_org_admins_creates_accounts(db):
    """Seed tạo đủ 82 tài khoản org_admin tương ứng với 82 đơn vị."""
    await seed_all(db, commit=False)
    res = await seed_org_admins(db, commit=True)
    assert res["created"] == 82
    assert res["skipped"] == 0

    # Kiểm tra một user cụ thể
    user = (
        await db.execute(select(User).where(User.email == "thachlac@hatinh.gov.vn"))
    ).scalar_one_or_none()
    assert user is not None
    assert user.full_name == "Quản trị viên UBND xã Thạch Lạc"
    assert verify_password(DEFAULT_PASSWORD, user.password_hash)

    # Kiểm tra user sở
    skhcn_user = (
        await db.execute(select(User).where(User.email == "skhcn@hatinh.gov.vn"))
    ).scalar_one_or_none()
    assert skhcn_user is not None
    assert skhcn_user.role == UserRole.ORG_ADMIN.value
    assert skhcn_user.full_name == "Quản trị viên Sở Khoa học và Công nghệ"
    assert verify_password(DEFAULT_PASSWORD, skhcn_user.password_hash)


async def test_seed_org_admins_is_idempotent(db):
    """Chạy seed nhiều lần không sinh trùng tài khoản."""
    await seed_all(db, commit=False)
    res1 = await seed_org_admins(db, commit=True)
    assert res1["created"] == 82

    res2 = await seed_org_admins(db, commit=True)
    assert res2["created"] == 0
    assert res2["skipped"] == 82
