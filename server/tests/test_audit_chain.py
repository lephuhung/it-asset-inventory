"""Unit tests — audit hash chain versioning + serialized appends (Task 1).

Bổ sung cho test_audit.py: xác nhận hàng legacy v1 vẫn verify được, hàng mới
dùng hash_version=2 có ràng buộc `details`/`machine_ref`, và append đồng thời
vẫn giữ chuỗi tuyến tính nhờ advisory lock.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.audit import (
    _content_hash_v1,
    append_audit,
    verify_chain,
)
from app.db.models import AuditLog


@pytest_asyncio.fixture
async def clean_db(db):
    await db.execute(delete(AuditLog))
    await db.commit()
    return db


async def test_v1_row_still_verifies(clean_db):
    """Hàng lịch sử (hash_version=1) dùng công thức v1 phải verify được."""
    ts = datetime.now(UTC)
    row = AuditLog(
        action="legacy.action",
        target="t",
        actor="a",
        ts=ts,
        prev_hash="0" * 64,
        content_hash=_content_hash_v1("legacy.action", "t", "a", ts),
        hash_version=1,
    )
    clean_db.add(row)
    await clean_db.commit()

    ok, bad_idx = await verify_chain(clean_db)
    assert ok is True
    assert bad_idx is None


async def test_v2_hashes_details_and_machine_ref(clean_db):
    """Hàng mới (v2) hash cả details + machine_ref; verify phải khớp."""
    await append_audit(
        clean_db,
        action="chat.query.inventory",
        actor="u",
        target="mc",
        details={"tool": "inventory_search", "machine_ref": "WS-01"},
    )
    await clean_db.commit()

    ok, bad_idx = await verify_chain(clean_db)
    assert ok is True
    assert bad_idx is None

    row = (await clean_db.execute(select(AuditLog))).scalar_one()
    assert row.hash_version == 2
    assert row.details == {"tool": "inventory_search", "machine_ref": "WS-01"}


async def test_v2_detects_details_tampering(clean_db):
    """Sửa details của hàng v2 phải làm đứt chuỗi (details nằm trong hash)."""
    await append_audit(
        clean_db,
        action="chat.query.inventory",
        actor="u",
        target="mc",
        details={"machine_ref": "WS-01"},
    )
    await clean_db.commit()

    row = (await clean_db.execute(select(AuditLog))).scalar_one()
    row.details = {"machine_ref": "WS-99"}
    await clean_db.commit()

    ok, bad_idx = await verify_chain(clean_db)
    assert ok is False
    assert bad_idx == 0


async def test_concurrent_appends_stay_linear(db_engine):
    """8 transaction append song song vẫn tạo chuỗi tuyến tính (advisory lock)."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def one(i: int) -> None:
        async with maker() as s:
            await append_audit(s, action=f"x{i}", actor="u", target="t")
            await s.commit()

    await asyncio.gather(*(one(i) for i in range(8)))

    async with maker() as s:
        ok, bad_idx = await verify_chain(s)
        assert ok is True
        assert bad_idx is None
