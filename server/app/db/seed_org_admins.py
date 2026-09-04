"""Seed tài khoản quản trị viên cho từng đơn vị (Org Admin) — Hà Tĩnh.

Mỗi đơn vị (UBND cấp xã, Sở ban ngành) có đúng 1 tài khoản quản trị:
- Role: `org_admin`
- Tên đăng nhập: Tạo theo tên đơn vị (không dấu, viết liền thường; Sở ban ngành dùng viết tắt chuẩn)
- Email: `<tên_đăng_nhập>@hatinh.gov.vn`
- Mật khẩu mặc định: `Hatinh@123`

Idempotent: chạy nhiều lần không tạo trùng lặp.
Chạy dòng lệnh:
    cd server && python -m app.db.seed_org_admins [--list] [--reset-passwords]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
import unicodedata
from typing import Any

# Đảm bảo in tiếng Việt trên console Windows không bị lỗi UnicodeEncodeError cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import Organization, OrgType, User, UserRole
from app.db.seed_orgs import SO_BAN_NGANH_NAMES, UBND_XA_NAMES, get_or_create_root
from app.db.session import AsyncSessionLocal

DEFAULT_PASSWORD = "Hatinh@123"
DEFAULT_DOMAIN = "hatinh.gov.vn"

# Viết tắt chuẩn cơ quan hành chính cấp tỉnh
SO_BAN_NGANH_MAP: dict[str, str] = {
    # Tên chuẩn có tiền tố Sở
    "Sở Khoa học và Công nghệ": "skhcn",
    "Sở Nội vụ": "snv",
    "Thanh tra tỉnh": "thanhtratinh",
    "Sở Tài chính": "stc",
    "Sở Xây dựng": "sxd",
    "Sở Nông nghiệp và Môi trường": "snnmt",
    "Sở Tư pháp": "stp",
    "Sở Ngoại vụ": "sngv",
    "Sở Giáo dục và Đào tạo": "sgddt",
    "Sở Công thương": "sct",
    "Sở Văn hóa, Thể Thao và Du Lịch": "svhttdl",
    "Sở Y tế": "syt",
    "Văn phòng UBND tỉnh": "vpubnd",
    # Tên không có tiền tố Sở (tương thích dữ liệu cũ hoặc đầu vào linh hoạt)
    "Khoa học và Công nghệ": "skhcn",
    "Nội vụ": "snv",
    "Tài chính": "stc",
    "Xây dựng": "sxd",
    "Nông nghiệp và Môi trường": "snnmt",
    "Tư pháp": "stp",
    "Ngoại vụ": "sngv",
    "Giáo dục và Đào tạo": "sgddt",
    "Công thương": "sct",
    "Văn hóa, Thể Thao và Du Lịch": "svhttdl",
    "Y tế": "syt",
}

# Bảng alias: cho phép người dùng gõ tên thay thế khi đăng nhập
USERNAME_ALIASES: dict[str, str] = {
    # Alias cho Sở ban ngành
    "khoahoccongnghe": "skhcn",
    "khoahocvacongnghe": "skhcn",
    "sokhcn": "skhcn",
    "noivu": "snv",
    "sonoivu": "snv",
    "thanhtra": "thanhtratinh",
    "taichinh": "stc",
    "sotaichinh": "stc",
    "xaydung": "sxd",
    "soxaydung": "sxd",
    "nongnghiepmoitruong": "snnmt",
    "nongnghiepvamoitruong": "snnmt",
    "sonnmt": "snnmt",
    "tuphap": "stp",
    "sotuphap": "stp",
    "ngoaivu": "sngv",
    "songoaivu": "sngv",
    "giaoducdaotao": "sgddt",
    "giaoducvadaotao": "sgddt",
    "sogddt": "sgddt",
    "congthuong": "sct",
    "socongthuong": "sct",
    "vanhoathethaodulich": "svhttdl",
    "vanhoathethaovadulich": "svhttdl",
    "sovhttdl": "svhttdl",
    "yte": "syt",
    "soyte": "syt",
    "vanphongubnd": "vpubnd",
    "vanphongubndtinh": "vpubnd",
    # Alias cho phường (gõ bỏ chữ phuong)
    "thanhsen": "phuongthanhsen",
    "tranphu": "phuongtranphu",
    "hahuytap": "phuonghahuytap",
    "vungang": "phuongvungang",
    "songtri": "phuongsongtri",
    "hoanhson": "phuonghoanhson",
    "haininh": "phuonghaininh",
    "bachonglinh": "phuongbachonglinh",
    "namhonglinh": "phuongnamhonglinh",
}


def remove_vietnamese_accents(input_str: str) -> str:
    """Chuyển chuỗi tiếng Việt có dấu sang không dấu."""
    s = input_str.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def org_name_to_username(name: str) -> str:
    """Tạo username chuẩn từ tên đơn vị."""
    if name in SO_BAN_NGANH_MAP:
        return SO_BAN_NGANH_MAP[name]
    clean_name = name.strip()
    lower_name = clean_name.lower()
    # Loại bỏ tiền tố "UBND xã " / "ubnd xa " để lấy slug ngắn gọn (vd "UBND xã Thạch Lạc" -> "thachlac")
    if lower_name.startswith("ubnd xã "):
        clean_name = clean_name[8:]
    elif lower_name.startswith("ubnd xa "):
        clean_name = clean_name[8:]
    elif lower_name.startswith("ubnd "):
        clean_name = clean_name[5:]

    clean = remove_vietnamese_accents(clean_name).lower()
    clean = re.sub(r"[^a-z0-9]+", "", clean)
    return clean


def resolve_login_username(login_input: str) -> str:
    """Chuẩn hóa tên đăng nhập nhập vào (xử lý alias và domain)."""
    raw = login_input.strip().lower()
    if "@" in raw:
        raw = raw.split("@")[0]
    clean = remove_vietnamese_accents(raw)
    clean = re.sub(r"[^a-z0-9]+", "", clean)
    # Hỗ trợ trường hợp người dùng gõ có tiền tố 'ubndxa'
    if clean.startswith("ubndxa") and len(clean) > 6:
        clean = clean[6:]
    return USERNAME_ALIASES.get(clean, clean)


def get_all_unit_admin_specs(domain: str = DEFAULT_DOMAIN) -> list[dict[str, str]]:
    """Trả về danh sách 82 đơn vị và thông tin tài khoản dự kiến."""
    specs: list[dict[str, str]] = []
    stt = 1
    for name in UBND_XA_NAMES:
        uname = org_name_to_username(name)
        specs.append({
            "stt": str(stt),
            "org_name": name,
            "org_type": OrgType.UBND_XA.value,
            "org_type_label": "UBND cấp xã",
            "username": uname,
            "email": f"{uname}@{domain}",
            "full_name": f"Quản trị viên {name}",
            "role": UserRole.ORG_ADMIN.value,
            "default_password": DEFAULT_PASSWORD,
        })
        stt += 1

    for name in SO_BAN_NGANH_NAMES:
        uname = org_name_to_username(name)
        specs.append({
            "stt": str(stt),
            "org_name": name,
            "org_type": OrgType.SO_BAN_NGANH.value,
            "org_type_label": "Sở ban ngành",
            "username": uname,
            "email": f"{uname}@{domain}",
            "full_name": f"Quản trị viên {name}",
            "role": UserRole.ORG_ADMIN.value,
            "default_password": DEFAULT_PASSWORD,
        })
        stt += 1
    return specs


async def seed_org_admins(
    db: AsyncSession,
    *,
    commit: bool = True,
    default_password: str = DEFAULT_PASSWORD,
    domain: str = DEFAULT_DOMAIN,
    reset_password: bool = False,
) -> dict[str, int]:
    """Seed tài khoản quản trị viên cho các đơn vị (UBND xã, Sở ban ngành).

    Idempotent:
    - Nếu đơn vị đã có tài khoản quản trị (hoặc email đã tồn tại), bỏ qua không tạo trùng.
    - Nếu `reset_password=True`, cập nhật mật khẩu về `default_password`.

    Returns:
        {"created": int, "skipped": int, "updated": int, "total": int}
    """
    root = await get_or_create_root(db)

    # Lấy danh sách các đơn vị thuộc root (loại ubnd_xa và so_ban_nganh)
    orgs = (
        await db.execute(
            select(Organization).where(
                Organization.parent_id == root.id,
                Organization.type.in_([OrgType.UBND_XA.value, OrgType.SO_BAN_NGANH.value]),
            )
        )
    ).scalars().all()

    org_map = {o.name: o for o in orgs}

    created = 0
    skipped = 0
    updated = 0
    pwd_hash = hash_password(default_password)

    for spec in get_all_unit_admin_specs(domain=domain):
        org_name = spec["org_name"]
        org = org_map.get(org_name)
        if not org:
            # Nếu org chưa được seed thì tìm theo tên
            org = (
                await db.execute(select(Organization).where(Organization.name == org_name))
            ).scalar_one_or_none()
            if not org:
                # Tự động tạo org nếu chưa có
                org = Organization(
                    name=org_name,
                    type=spec["org_type"],
                    parent_id=root.id,
                )
                db.add(org)
                await db.flush()
                org_map[org_name] = org

        email = spec["email"]
        existing_user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if existing_user is None:
            # Kiểm tra xem org này đã có user role org_admin nào chưa
            existing_admin = (
                await db.execute(
                    select(User).where(
                        User.org_id == org.id,
                        User.role.in_([UserRole.ORG_ADMIN.value, UserRole.ADMIN_ORG.value]),
                    )
                )
            ).scalars().first()

            if existing_admin is not None:
                # Đã có admin với email khác
                if reset_password:
                    existing_admin.password_hash = pwd_hash
                    existing_admin.must_change_password = True
                    updated += 1
                else:
                    skipped += 1
                continue

            # Tạo user quản trị mới — mật khẩu mặc định → bắt buộc đổi ở lần đăng nhập đầu
            user = User(
                org_id=org.id,
                full_name=spec["full_name"],
                email=email,
                role=UserRole.ORG_ADMIN.value,
                password_hash=pwd_hash,
                is_active=True,
                must_change_password=True,
            )
            db.add(user)
            created += 1
        else:
            if reset_password:
                existing_user.password_hash = pwd_hash
                existing_user.is_active = True
                existing_user.must_change_password = True
                updated += 1
            else:
                skipped += 1

    if commit:
        await db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "updated": updated,
        "total": len(org_map),
    }


def print_admin_table(specs: list[dict[str, str]]) -> None:
    """In bảng danh sách tài khoản dạng bảng đẹp."""
    sep = "+" + "-" * 6 + "+" + "-" * 32 + "+" + "-" * 15 + "+" + "-" * 20 + "+" + "-" * 34 + "+" + "-" * 14 + "+"
    header = f"| {'STT':<4} | {'Tên đơn vị':<30} | {'Loại':<13} | {'Tên đăng nhập':<18} | {'Email':<32} | {'Mật khẩu':<12} |"
    print(sep)
    print(header)
    print(sep)
    for s in specs:
        row = (
            f"| {s['stt']:<4} | {s['org_name']:<30} | {s['org_type_label']:<13} "
            f"| {s['username']:<18} | {s['email']:<32} | {s['default_password']:<12} |"
        )
        print(row)
    print(sep)
    print(f"Tổng số đơn vị: {len(specs)} tài khoản quản trị.")


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed tài khoản quản trị viên cho các đơn vị (Hà Tĩnh)")
    parser.add_argument("--list", action="store_true", help="Chỉ hiển thị danh sách tài khoản dự kiến, không ghi DB")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử không ghi vào DB (thường dùng kết hợp --export-csv)")
    parser.add_argument("--reset-passwords", action="store_true", help="Cập nhật lại mật khẩu về Hatinh@123 cho tài khoản đã tồn tại")
    parser.add_argument("--export-csv", type=str, default="", help="Xuất danh sách ra file CSV")
    parser.add_argument("--domain", type=str, default=DEFAULT_DOMAIN, help=f"Domain email (mặc định: {DEFAULT_DOMAIN})")
    args = parser.parse_args()

    specs = get_all_unit_admin_specs(domain=args.domain)

    if args.export_csv:
        with open(args.export_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["stt", "org_name", "org_type_label", "username", "email", "default_password", "role"])
            writer.writeheader()
            for s in specs:
                writer.writerow({
                    "stt": s["stt"],
                    "org_name": s["org_name"],
                    "org_type_label": s["org_type_label"],
                    "username": s["username"],
                    "email": s["email"],
                    "default_password": s["default_password"],
                    "role": s["role"],
                })
        print(f"Đã xuất {len(specs)} tài khoản ra file: {args.export_csv}")

    if args.list:
        print_admin_table(specs)
        return

    if args.dry_run:
        print("Chế độ dry-run: đã xử lý xong mà không kết nối database.")
        return

    # Thực hiện seed vào database
    print("Đang khởi tạo các đơn vị và seed tài khoản quản trị...")
    from app.db.seed_orgs import seed_all

    async with AsyncSessionLocal() as db:
        # Đảm bảo danh sách org đã được seed
        await seed_all(db, commit=False)
        result = await seed_org_admins(
            db,
            commit=True,
            default_password=DEFAULT_PASSWORD,
            domain=args.domain,
            reset_password=args.reset_passwords,
        )

    print(
        f"Hoàn thành seed tài khoản đơn vị:\n"
        f"  - Tạo mới:   {result['created']}\n"
        f"  - Đã tồn tại: {result['skipped']}\n"
        f"  - Cập nhật:  {result['updated']}\n"
        f"  - Tổng đơn vị: {result['total']}"
    )


if __name__ == "__main__":
    asyncio.run(_main())
