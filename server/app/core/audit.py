"""Audit log append-only + hash chain (mục 7.2 tài liệu gốc).

Mỗi dòng chứa prev_hash (hash dòng trước) + content_hash (SHA-256 nội dung dòng).
Chỉ INSERT qua service này; DB role tách biệt thu hồi UPDATE/DELETE ở prod.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

# Khóa advisory toàn cục cho chuỗi audit: serialize get_last_hash + insert để
# nhiều writer đồng thời không tạo nhánh rồi cùng trỏ về một prev_hash.
# Giá trị cố định 0x61756469746368 ("auditch") — không đổi giữa các phiên bản.
_AUDIT_LOCK_KEY = 0x61756469746368


class AuditValidationError(ValueError):
    """`details` của audit không JSON-serializable hoặc chứa số không hữu hạn."""


def _fmt_ts(ts: datetime) -> str:
    """Chuẩn hóa timestamp thành chuỗi ổn định cho mục đích hash.

    SQLite lưu datetime dưới dạng naive (mất tzinfo) → phải chuẩn hóa cả
    aware lẫn naive về cùng dạng UTC-naive-microsecond để hash khớp nhau
    giữa lúc ghi và lúc verify.
    """
    t = ts
    if t.tzinfo is not None:
        t = t.astimezone(UTC).replace(tzinfo=None)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _content_hash_v1(action: str, target: str | None, actor: str | None, ts: datetime) -> str:
    """Công thức hash legacy (hash_version=1) — giữ nguyên byte để hàng cũ verify được."""
    payload = json.dumps(
        {"action": action, "target": target, "actor": actor, "ts": _fmt_ts(ts)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _machine_ref(details: dict | None) -> str:
    return str((details or {}).get("machine_ref") or "")


def _content_hash_v2(
    action: str,
    target: str | None,
    actor: str | None,
    ts: datetime,
    request_id: str | None,
    details: dict | None,
) -> str:
    """Công thức hash v2 — ràng buộc request_id + machine_ref + details có cấu trúc.

    `machine_id` KHÔNG nằm trong hash (lookup mutable, route xoá máy được phép
    SET NULL). `machine_ref` bất biến được lấy từ `details` và hash-bound.

    `details` PHẢI là dạng canonical do `_canonicalize_details` trả về (đã round-trip
    qua `jsonb`). Hash thẳng dict Python thô sẽ lệch với giá trị đọc lại từ DB ở
    các biểu diễn số mà `jsonb` viết lại (`1e20`, `-0.0`).
    """
    payload = json.dumps(
        {
            "v": 2,
            "action": action,
            "target": target,
            "actor": actor,
            "ts": _fmt_ts(ts),
            "request_id": request_id,
            "machine_ref": _machine_ref(details),
            "details": details or {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _canonicalize_details(db: AsyncSession, details: dict | None) -> dict | None:
    """Chuẩn hóa `details` qua `jsonb` của PostgreSQL trước khi hash và ghi.

    `jsonb` viết lại biểu diễn số (`1e20` → `100000000000000000000`, `-0.0` → `0.0`)
    và sắp xếp key. Nếu hash thẳng dict Python thì hash lúc ghi sẽ khác hash lúc
    verify — `verify_chain` đọc lại `row.details` từ `jsonb` — và chuỗi đứt giả tạo
    dù hàng hoàn toàn nguyên vẹn.

    Round-trip qua `jsonb` đúng MỘT lần ở đây, rồi hash và ghi chính dạng canonical;
    lúc verify dùng nguyên `row.details` (đã canonical) nên khớp byte-for-byte.
    `details` phải JSON-serializable (không UUID/Decimal/datetime) và hữu hạn
    (không NaN/Infinity); nếu không, raise `AuditValidationError`.
    """
    if details is None:
        return None
    try:
        raw = json.dumps(details, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AuditValidationError(
            f"audit details must be JSON-serializable with finite numbers: {exc}"
        ) from exc
    canonical_text = (
        await db.execute(text("SELECT CAST(:d AS jsonb)::text"), {"d": raw})
    ).scalar_one()
    return json.loads(canonical_text)


async def get_last_hash(db: AsyncSession) -> str:
    row = (
        await db.execute(select(AuditLog.content_hash).order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none()
    return row or "0" * 64  # genesis hash


async def append_audit(
    db: AsyncSession,
    *,
    action: str,
    actor: str | None = None,
    target: str | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    machine_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Append 1 dòng audit log, tự nối hash chain.

    Lấy `pg_advisory_xact_lock` trong cùng transaction với insert để serialize
    `get_last_hash` + ghi; khóa tự nhả khi transaction kết thúc. Caller vẫn sở
    hữu transaction (route phải commit).
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY})
    ts = datetime.now(UTC)
    # Canonical hóa TRƯỚC khi hash để hash-time == write-time == verify-time
    # (tránh JSONB viết lại số làm đứt chuỗi giả tạo).
    canonical_details = await _canonicalize_details(db, details)
    prev = await get_last_hash(db)
    ch = _content_hash_v2(action, target, actor, ts, request_id, canonical_details)
    entry = AuditLog(
        actor=actor,
        action=action,
        target=target,
        ts=ts,
        ip=ip,
        prev_hash=prev,
        content_hash=ch,
        request_id=request_id,
        machine_id=machine_id,
        details=canonical_details,
        hash_version=2,
    )
    db.add(entry)
    await db.flush()
    return entry


async def verify_chain(db: AsyncSession) -> tuple[bool, int | None]:
    """Kiểm tra toàn bộ hash chain — dùng trong test & audit định kỳ.

    Trả về (ok, index dòng đầu tiên bị đứt) hoặc (True, None).
    """
    rows = (
        (await db.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
    )
    prev = "0" * 64
    for i, row in enumerate(rows):
        if row.hash_version == 1:
            ch = _content_hash_v1(row.action, row.target, row.actor, row.ts)
        elif row.hash_version == 2:
            ch = _content_hash_v2(
                row.action, row.target, row.actor, row.ts, row.request_id, row.details
            )
        else:
            return False, i
        if row.prev_hash != prev or row.content_hash != ch:
            return False, i
        prev = row.content_hash
    return True, None


async def anchor_hash(db: AsyncSession) -> str:
    """Hash toàn bộ chuỗi hiện tại — đầu vào cho bước ký anchor định kỳ (Phase 2)."""
    last = (
        await db.execute(select(AuditLog.content_hash).order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none()
    return last or "0" * 64
