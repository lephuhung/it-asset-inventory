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

# Danh sách UBND cấp xã — theo thứ tự yêu cầu khởi tạo
UBND_XA_NAMES: list[str] = [
    "Thạch Lạc",
    "Đồng Tiến",
    "Thạch Khê",
    "Cẩm Bình",
    "Kỳ Xuân",
    "Kỳ Anh",
    "Kỳ Hoa",
    "Kỳ Văn",
    "Kỳ Khang",
    "Kỳ Lạc",
    "Kỳ Thượng",
    "Cẩm Xuyên",
    "Thiên Cầm",
    "Cẩm Duệ",
    "Cẩm Hưng",
    "Cẩm Lạc",
    "Cẩm Trung",
    "Yên Hòa",
    "Thạch Hà",
    "Toàn Lưu",
    "Việt Xuyên",
    "Đông Kinh",
    "Thạch Xuân",
    "Lộc Hà",
    "Hồng Lộc",
    "Mai Phụ",
    "Can Lộc",
    "Tùng Lộc",
    "Gia Hanh",
    "Trường Lưu",
    "Xuân Lộc",
    "Đồng Lộc",
    "Tiên Điền",
    "Nghi Xuân",
    "Cổ Đạm",
    "Đan Hải",
    "Đức Thọ",
    "Đức Đồng",
    "Đức Quang",
    "Đức Thịnh",
    "Đức Minh",
    "Hương Sơn",
    "Sơn Tây",
    "Tứ Mỹ",
    "Sơn Giang",
    "Sơn Tiến",
    "Sơn Hồng",
    "Kim Hoa",
    "Vũ Quang",
    "Mai Hoa",
    "Thượng Đức",
    "Hương Khê",
    "Hương Phố",
    "Hương Đô",
    "Hà Linh",
    "Hương Bình",
    "Phúc Trạch",
    "Hương Xuân",
    "Phường Thành Sen",
    "Phường Trần Phú",
    "Phường Hà Huy Tập",
    "Phường Vũng Áng",
    "Phường Sông Trí",
    "Phường Hoành Sơn",
    "Phường Hải Ninh",
    "Phường Bắc Hồng Lĩnh",
    "Phường Nam Hồng Lĩnh",
    "Sơn Kim 1",
    "Sơn Kim 2",
]

# Danh sách Sở ban ngành / Văn phòng UBND tỉnh — theo thứ tự yêu cầu khởi tạo
SO_BAN_NGANH_NAMES: list[str] = [
    "Khoa học và Công nghệ",
    "Nội vụ",
    "Thanh tra tỉnh",
    "Tài chính",
    "Xây dựng",
    "Nông nghiệp và Môi trường",
    "Tư pháp",
    "Ngoại vụ",
    "Giáo dục và Đào tạo",
    "Công thương",
    "Văn hóa, Thể Thao và Du Lịch",
    "Y tế",
    "Văn phòng UBND tỉnh",
]


async def _seed_orgs(
    db: AsyncSession, names: list[str], org_type: str
) -> tuple[int, int]:
    """Seed danh sách tổ chức cùng loại dưới Root. Idempotent.

    Returns:
        (created, skipped) — số tổ chức mới tạo và số đã tồn tại.
    """
    # Đảm bảo org gốc Root (type=root) — seed_admin cũng tạo nếu thiếu
    root = (await db.execute(select(Organization).where(Organization.name == "Root"))).scalar_one_or_none()
    if root is None:
        root = Organization(name="Root", type=OrgType.ROOT.value)
        db.add(root)
        await db.flush()

    existing = {
        o.name
        for o in (
            await db.execute(
                select(Organization).where(
                    Organization.type == org_type,
                    Organization.parent_id == root.id,
                )
            )
        ).scalars()
    }

    created = 0
    skipped = 0
    for name in names:
        if name in existing:
            skipped += 1
            continue
        db.add(Organization(name=name, type=org_type, parent_id=root.id))
        created += 1

    await db.commit()
    return created, skipped


async def seed_ubnd_xa(db: AsyncSession) -> tuple[int, int]:
    """Seed danh sách UBND cấp xã dưới Root. Idempotent."""
    return await _seed_orgs(db, UBND_XA_NAMES, OrgType.UBND_XA.value)


async def seed_so_ban_nganh(db: AsyncSession) -> tuple[int, int]:
    """Seed danh sách Sở ban ngành / Văn phòng UBND tỉnh dưới Root. Idempotent."""
    return await _seed_orgs(db, SO_BAN_NGANH_NAMES, OrgType.SO_BAN_NGANH.value)


async def seed_all(db: AsyncSession) -> dict[str, tuple[int, int]]:
    """Seed toàn bộ tổ chức cấp tỉnh (UBND xã + Sở ban ngành). Idempotent."""
    return {
        "ubnd_xa": await seed_ubnd_xa(db),
        "so_ban_nganh": await seed_so_ban_nganh(db),
    }


async def _main() -> None:
    async with AsyncSessionLocal() as db:
        result = await seed_all(db)
    for label, (created, skipped) in result.items():
        print(f"Seed {label}: tạo mới {created}, đã tồn tại {skipped}.")


if __name__ == "__main__":
    asyncio.run(_main())
