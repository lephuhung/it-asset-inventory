"""Audit log append-only + hash chain (mục 7.2 tài liệu gốc).

Mỗi dòng chứa prev_hash (hash dòng trước) + content_hash (SHA-256 nội dung dòng).
Chỉ INSERT qua service này; DB role tách biệt thu hồi UPDATE/DELETE ở prod.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


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


def _content_hash(action: str, target: str | None, actor: str | None, ts: datetime) -> str:
    payload = json.dumps(
        {"action": action, "target": target, "actor": actor, "ts": _fmt_ts(ts)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
) -> AuditLog:
    """Append 1 dòng audit log, tự nối hash chain."""
    ts = datetime.now(UTC)
    prev = await get_last_hash(db)
    ch = _content_hash(action, target, actor, ts)
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
        ch = _content_hash(row.action, row.target, row.actor, row.ts)
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
