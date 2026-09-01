"""Dịch vụ tag máy — nguồn duy nhất thao tác `machine_tags`.

Ràng buộc quan trọng:
- Mỗi máy có ĐÚNG 1 tag `kind='classification'` (partial unique index chặn ở DB,
  service này đảm bảo thay-tag phân loại = xóa tag cũ + thêm tag mới).
- Tag `kind='purpose'` là nhiều–nhiều tự do.
- Thống kê "cá nhân / công vụ / BMNN" CHỈ đọc tag classification — tag mục đích
  thêm bao nhiêu cũng không ảnh hưởng (xem các route stats).
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CLASSIFICATION_TAGS,
    DEFAULT_CLASSIFICATION,
    MachineTag,
    Tag,
    TagKind,
)

# 3 tag phân loại hệ thống — key cố định.
CLASSIFICATION_KEYS: tuple[str, ...] = ("personal", "official", "bmnn")

# Màu badge tailwind mặc định cho 3 loại máy (đồng bộ portal CLASSIFICATION_META).
_CLASSIFICATION_COLORS: dict[str, str] = {
    "personal": "bg-sky-50 text-sky-700 ring-sky-600/20",
    "official": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    "bmnn": "bg-amber-50 text-amber-700 ring-amber-600/20",
}


async def ensure_system_tags(db: AsyncSession, *, commit: bool = True) -> None:
    """Seed 3 tag phân loại hệ thống nếu chưa tồn tại.

    Gọi ở app startup (lifespan) — tự phục hồi cả khi DB tạo bằng
    `Base.metadata.create_all` (test/dev) chứ không chỉ qua migration.
    """
    for idx, (key, label) in enumerate(CLASSIFICATION_TAGS, start=1):
        exists = (
            await db.execute(select(Tag).where(Tag.key == key))
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                Tag(
                    key=key,
                    label=label,
                    kind=TagKind.CLASSIFICATION.value,
                    color=_CLASSIFICATION_COLORS.get(key),
                    sort_order=idx,
                    is_system=True,
                )
            )
    if commit:
        await db.commit()


async def get_tag_by_key(db: AsyncSession, key: str) -> Tag | None:
    return (
        await db.execute(select(Tag).where(Tag.key == key))
    ).scalar_one_or_none()


async def list_tags(db: AsyncSession) -> list[Tag]:
    return list(
        (
            await db.execute(
                select(Tag).order_by(Tag.kind.asc(), Tag.sort_order.asc(), Tag.label.asc())
            )
        ).scalars()
    )


async def get_machine_tags(db: AsyncSession, machine_id: uuid.UUID) -> list[Tag]:
    """Trả về toàn bộ Tag của 1 máy (classification + purpose)."""
    return list(
        (
            await db.execute(
                select(Tag)
                .join(MachineTag, MachineTag.tag_id == Tag.id)
                .where(MachineTag.machine_id == machine_id)
                .order_by(Tag.kind.asc(), Tag.sort_order.asc(), Tag.label.asc())
            )
        ).scalars()
    )


async def get_machine_tag_keys(db: AsyncSession, machine_id: uuid.UUID) -> dict:
    """{classification: key|None, purpose: [keys]} — tiện cho API detail."""
    tags = await get_machine_tags(db, machine_id)
    return {
        "classification": next(
            (t.key for t in tags if t.kind == TagKind.CLASSIFICATION.value), None
        ),
        "purpose": [t.key for t in tags if t.kind == TagKind.PURPOSE.value],
    }


async def ensure_classification(
    db: AsyncSession,
    machine_id: uuid.UUID,
    key: str = DEFAULT_CLASSIFICATION,
    actor: uuid.UUID | None = None,
) -> None:
    """Gán tag phân loại nếu máy CHƯA có (không đè). Dùng khi enroll/offline import."""
    if key not in CLASSIFICATION_KEYS:
        key = DEFAULT_CLASSIFICATION
    tag = await get_tag_by_key(db, key)
    if tag is None:
        return
    has = (
        await db.execute(
            select(MachineTag.machine_id).where(
                MachineTag.machine_id == machine_id,
                MachineTag.kind == TagKind.CLASSIFICATION.value,
            )
        )
    ).first()
    if has:
        return
    db.add(
        MachineTag(
            machine_id=machine_id,
            tag_id=tag.id,
            kind=TagKind.CLASSIFICATION.value,
            set_by=actor,
        )
    )


async def set_machine_classification(
    db: AsyncSession,
    machine_id: uuid.UUID,
    key: str,
    actor: uuid.UUID | None = None,
) -> bool:
    """ĐỔI tag phân loại của máy (xóa tag cũ + thêm mới). Trả False nếu key không hợp lệ."""
    if key not in CLASSIFICATION_KEYS:
        return False
    tag = await get_tag_by_key(db, key)
    if tag is None:
        return False
    await db.execute(
        delete(MachineTag).where(
            MachineTag.machine_id == machine_id,
            MachineTag.kind == TagKind.CLASSIFICATION.value,
        )
    )
    db.add(
        MachineTag(
            machine_id=machine_id,
            tag_id=tag.id,
            kind=TagKind.CLASSIFICATION.value,
            set_by=actor,
        )
    )
    return True


async def set_machine_purpose_tags(
    db: AsyncSession,
    machine_id: uuid.UUID,
    keys: list[str],
    actor: uuid.UUID | None = None,
) -> None:
    """Thay toàn bộ tag mục đích của máy (dedupe, bỏ key không tồn tại)."""
    valid: list[str] = []
    for key in dict.fromkeys(keys or []):  # dedupe, giữ thứ tự
        tag = await get_tag_by_key(db, key)
        if tag is not None and tag.kind == TagKind.PURPOSE.value:
            valid.append(key)
    await db.execute(
        delete(MachineTag).where(
            MachineTag.machine_id == machine_id,
            MachineTag.kind == TagKind.PURPOSE.value,
        )
    )
    for key in valid:
        tag = await get_tag_by_key(db, key)
        if tag is None:
            continue
        db.add(
            MachineTag(
                machine_id=machine_id,
                tag_id=tag.id,
                kind=TagKind.PURPOSE.value,
                set_by=actor,
            )
        )


async def apply_token_tags(
    db: AsyncSession,
    machine_id: uuid.UUID,
    token,
    actor: uuid.UUID | None = None,
) -> None:
    """Áp loại máy + tag mục đích đã chọn lúc sinh token cho máy vừa enroll.

    Gọi NGAY SAU khi tạo máy mới (trước commit). Máy cũ enroll lại KHÔNG bị đè
    (chỉ áp cho máy mới — chủ máy đã phân loại rồi).
    """
    classification = getattr(token, "classification", None) or DEFAULT_CLASSIFICATION
    await ensure_classification(db, machine_id, classification, actor=actor)
    purpose = list(getattr(token, "purpose_tags", None) or [])
    if purpose:
        await set_machine_purpose_tags(db, machine_id, purpose, actor=actor)


async def classification_tag_id(db: AsyncSession, key: str) -> uuid.UUID | None:
    tag = await get_tag_by_key(db, key)
    return tag.id if tag else None
