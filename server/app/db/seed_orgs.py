"""Seed danh sách tổ chức cấp tỉnh (Hà Tĩnh) — Organizations dưới Root.

- `type=ubnd_xa`     : danh sách UBND cấp xã
- `type=so_ban_nganh`: danh sách Sở ban ngành / Văn phòng UBND tỉnh

Idempotent: chạy nhiều lần không tạo trùng (kiểm tra theo name + type).

- Gọi tự động trong lifespan (dev/test) cùng `seed_admin`.
- Chạy tay (mọi môi trường, kể cả prod khởi tạo):

    cd server && .venv/bin/python -m app.db.seed_orgs
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Organization, OrgType
from app.db.session import AsyncSessionLocal

# Tên tổ chức gốc — mọi đơn vị đều thuộc UBND tỉnh Hà Tĩnh
ROOT_ORG_NAME = "UBND tỉnh Hà Tĩnh"

# Danh sách UBND cấp xã — theo thứ tự yêu cầu khởi tạo
UBND_XA_NAMES: list[str] = [
    "UBND xã Thạch Lạc",
    "UBND xã Đồng Tiến",
    "UBND xã Thạch Khê",
    "UBND xã Cẩm Bình",
    "UBND xã Kỳ Xuân",
    "UBND xã Kỳ Anh",
    "UBND xã Kỳ Hoa",
    "UBND xã Kỳ Văn",
    "UBND xã Kỳ Khang",
    "UBND xã Kỳ Lạc",
    "UBND xã Kỳ Thượng",
    "UBND xã Cẩm Xuyên",
    "UBND xã Thiên Cầm",
    "UBND xã Cẩm Duệ",
    "UBND xã Cẩm Hưng",
    "UBND xã Cẩm Lạc",
    "UBND xã Cẩm Trung",
    "UBND xã Yên Hòa",
    "UBND xã Thạch Hà",
    "UBND xã Toàn Lưu",
    "UBND xã Việt Xuyên",
    "UBND xã Đông Kinh",
    "UBND xã Thạch Xuân",
    "UBND xã Lộc Hà",
    "UBND xã Hồng Lộc",
    "UBND xã Mai Phụ",
    "UBND xã Can Lộc",
    "UBND xã Tùng Lộc",
    "UBND xã Gia Hanh",
    "UBND xã Trường Lưu",
    "UBND xã Xuân Lộc",
    "UBND xã Đồng Lộc",
    "UBND xã Tiên Điền",
    "UBND xã Nghi Xuân",
    "UBND xã Cổ Đạm",
    "UBND xã Đan Hải",
    "UBND xã Đức Thọ",
    "UBND xã Đức Đồng",
    "UBND xã Đức Quang",
    "UBND xã Đức Thịnh",
    "UBND xã Đức Minh",
    "UBND xã Hương Sơn",
    "UBND xã Sơn Tây",
    "UBND xã Tứ Mỹ",
    "UBND xã Sơn Giang",
    "UBND xã Sơn Tiến",
    "UBND xã Sơn Hồng",
    "UBND xã Kim Hoa",
    "UBND xã Vũ Quang",
    "UBND xã Mai Hoa",
    "UBND xã Thượng Đức",
    "UBND xã Hương Khê",
    "UBND xã Hương Phố",
    "UBND xã Hương Đô",
    "UBND xã Hà Linh",
    "UBND xã Hương Bình",
    "UBND xã Phúc Trạch",
    "UBND xã Hương Xuân",
    "Phường Thành Sen",
    "Phường Trần Phú",
    "Phường Hà Huy Tập",
    "Phường Vũng Áng",
    "Phường Sông Trí",
    "Phường Hoành Sơn",
    "Phường Hải Ninh",
    "Phường Bắc Hồng Lĩnh",
    "Phường Nam Hồng Lĩnh",
    "UBND xã Sơn Kim 1",
    "UBND xã Sơn Kim 2",
]

# Danh sách Sở ban ngành / Văn phòng UBND tỉnh — theo thứ tự yêu cầu khởi tạo
SO_BAN_NGANH_NAMES: list[str] = [
    "Sở Khoa học và Công nghệ",
    "Sở Nội vụ",
    "Thanh tra tỉnh",
    "Sở Tài chính",
    "Sở Xây dựng",
    "Sở Nông nghiệp và Môi trường",
    "Sở Tư pháp",
    "Sở Ngoại vụ",
    "Sở Giáo dục và Đào tạo",
    "Sở Công thương",
    "Sở Văn hóa, Thể Thao và Du Lịch",
    "Sở Y tế",
    "Văn phòng UBND tỉnh",
]


async def get_or_create_root(db: AsyncSession) -> Organization:
    """Lấy (hoặc tạo) org gốc — “UBND tỉnh Hà Tĩnh”.

    - Ưu tiên tìm theo ``type=ROOT``; nếu DB cũ đang đặt tên "Root" thì
      đổi tên luôn thay vì tạo thêm root thứ hai.
    - Idempotent.
    """
    root = (
        await db.execute(select(Organization).where(Organization.type == OrgType.ROOT.value))
    ).scalars().first()
    if root is None:
        # Fallback: DB cũ chỉ có tên, chưa set đúng type
        root = (
            await db.execute(select(Organization).where(Organization.name == ROOT_ORG_NAME))
        ).scalar_one_or_none()
    if root is None:
        root = Organization(name=ROOT_ORG_NAME, type=OrgType.ROOT.value)
        db.add(root)
        await db.flush()
    elif root.name != ROOT_ORG_NAME:
        # Đổi tên root cũ (VD: "Root") thành tên chuẩn
        root.name = ROOT_ORG_NAME
        await db.flush()
    return root


async def _seed_orgs(
    db: AsyncSession, names: list[str], org_type: str, *, commit: bool = True
) -> tuple[int, int]:
    """Seed danh sách tổ chức cùng loại dưới Root. Idempotent.

    Returns:
        (created, skipped) — số tổ chức mới tạo và số đã tồn tại.
    """
    # Đảm bảo org gốc "UBND tỉnh Hà Tĩnh" (type=root)
    root = await get_or_create_root(db)

    org_rows = (
        await db.execute(
            select(Organization).where(
                Organization.type == org_type,
                Organization.parent_id == root.id,
            )
        )
    ).scalars().all()

    # Đổi tên các đơn vị cũ chưa có tiền tố chuẩn nếu có
    if org_type == OrgType.SO_BAN_NGANH.value:
        for o in org_rows:
            for n in names:
                if n.startswith("Sở ") and o.name == n[3:]:
                    o.name = n
    elif org_type == OrgType.UBND_XA.value:
        for o in org_rows:
            for n in names:
                if n.startswith("UBND xã ") and o.name == n[8:]:
                    o.name = n

    existing = {o.name for o in org_rows}

    created = 0
    skipped = 0
    for name in names:
        if name in existing:
            skipped += 1
            continue
        db.add(Organization(name=name, type=org_type, parent_id=root.id))
        created += 1

    if commit:
        await db.commit()
    return created, skipped


async def seed_ubnd_xa(db: AsyncSession, *, commit: bool = True) -> tuple[int, int]:
    """Seed danh sách UBND cấp xã dưới Root. Idempotent."""
    return await _seed_orgs(db, UBND_XA_NAMES, OrgType.UBND_XA.value, commit=commit)


async def seed_so_ban_nganh(db: AsyncSession, *, commit: bool = True) -> tuple[int, int]:
    """Seed danh sách Sở ban ngành / Văn phòng UBND tỉnh dưới Root. Idempotent."""
    return await _seed_orgs(db, SO_BAN_NGANH_NAMES, OrgType.SO_BAN_NGANH.value, commit=commit)


async def seed_all(db: AsyncSession, *, commit: bool = True) -> dict[str, tuple[int, int]]:
    """Seed toàn bộ tổ chức cấp tỉnh (UBND xã + Sở ban ngành). Idempotent."""
    result = {
        "ubnd_xa": await seed_ubnd_xa(db, commit=False),
        "so_ban_nganh": await seed_so_ban_nganh(db, commit=False),
    }
    if commit:
        await db.commit()
    return result


async def _main() -> None:
    async with AsyncSessionLocal() as db:
        result = await seed_all(db)
    for label, (created, skipped) in result.items():
        print(f"Seed {label}: tạo mới {created}, đã tồn tại {skipped}.")


if __name__ == "__main__":
    asyncio.run(_main())
