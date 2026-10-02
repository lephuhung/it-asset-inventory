"""Unit tests — audit hash chain versioning + serialized appends (Task 1).

Bổ sung cho `test_audit.py`:
- hàng legacy `hash_version=1` vẫn verify được;
- chuỗi mixed v1→v2 liên kết `prev_hash` đúng qua session mới;
- hàng mới `hash_version=2` hash cả `details`/`machine_ref`/`request_id`;
- hash chịu được `jsonb` viết lại biểu diễn số (`1e20`, `-0.0`) — regression của
  lỗi "chuỗi đứt giả tạo" do hash dict Python thô;
- `machine_id` là lookup mutable, KHÔNG hash-bound (đổi/xóa không đứt chuỗi);
- append đồng thời vẫn tuyến tính nhờ advisory lock.

Mọi verify chạy trong session MỚI đọc lại từ DB. Verify trong session ghim
identity-map (`expire_on_commit=False`) sẽ che lệch round-trip JSONB.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.audit import (
    _content_hash_v1,
    append_audit,
    verify_chain,
)
from app.db.models import AuditLog


@pytest_asyncio.fixture
async def maker(db_engine):
    """Session factory trên schema sạch (db_engine drop/create mỗi test)."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _insert_legacy_v1(session) -> AuditLog:
    """Chèn hàng legacy v1 (prev_hash = genesis) đúng công thức v1."""
    ts = datetime.now(UTC)
    row = AuditLog(
        action="legacy.first",
        target="t",
        actor="a",
        ts=ts,
        prev_hash="0" * 64,
        content_hash=_content_hash_v1("legacy.first", "t", "a", ts),
        hash_version=1,
    )
    session.add(row)
    await session.flush()
    return row


async def test_v1_row_still_verifies(maker):
    """Hàng lịch sử (hash_version=1) dùng công thức v1 phải verify được."""
    async with maker() as s:
        await _insert_legacy_v1(s)
        await s.commit()

    async with maker() as s2:
        assert await verify_chain(s2) == (True, None)


async def test_mixed_v1_then_v2_chain_verifies(maker):
    """v2 nối tiếp v1: `prev_hash` trỏ đúng hash v1 và cả chuỗi verify được."""
    async with maker() as s:
        legacy = await _insert_legacy_v1(s)
        await s.commit()
        legacy_hash = legacy.content_hash

    async with maker() as s2:
        entry = await append_audit(
            s2,
            action="chat.query.inventory",
            actor="u",
            target="mc",
            request_id="req-1",
            details={"tool": "inventory_search", "machine_ref": "WS-01"},
        )
        await s2.commit()
        assert entry.prev_hash == legacy_hash
        assert entry.hash_version == 2

    async with maker() as s3:
        rows = (
            (await s3.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
        )
        assert [r.hash_version for r in rows] == [1, 2]
        assert rows[1].prev_hash == rows[0].content_hash
        assert await verify_chain(s3) == (True, None)


async def test_v2_hashes_details_and_machine_ref(maker):
    """Hàng mới (v2) hash cả details + machine_ref; verify session mới phải khớp."""
    async with maker() as s:
        await append_audit(
            s,
            action="chat.query.inventory",
            actor="u",
            target="mc",
            details={"tool": "inventory_search", "machine_ref": "WS-01"},
        )
        await s.commit()

    async with maker() as s2:
        assert await verify_chain(s2) == (True, None)
        row = (await s2.execute(select(AuditLog))).scalar_one()
        assert row.hash_version == 2
        assert row.details == {"tool": "inventory_search", "machine_ref": "WS-01"}


async def test_v2_detects_details_tampering(maker):
    """Sửa details của hàng v2 phải làm đứt chuỗi (details nằm trong hash)."""
    async with maker() as s:
        await append_audit(
            s,
            action="chat.query.inventory",
            actor="u",
            target="mc",
            details={"machine_ref": "WS-01"},
        )
        await s.commit()

    async with maker() as s2:
        row = (await s2.execute(select(AuditLog))).scalar_one()
        row.details = {"machine_ref": "WS-99"}
        await s2.commit()

    async with maker() as s3:
        assert await verify_chain(s3) == (False, 0)


async def test_v2_jsonb_numeric_normalization_round_trips(maker):
    """Regression: `jsonb` viết lại `1e20`→int, `-0.0`→`0.0`; hash phải canonical.

    Nếu hash thẳng dict Python thô, hash lúc ghi (`1e+20`, `-0.0`) khác giá trị
    đọc lại từ jsonb (`100000000000000000000`, `0.0`) và `verify_chain` báo đứt
    dù hàng nguyên vẹn.
    """
    cases = {
        "plain": {"machine_ref": "WS-01", "tool": "inventory_search"},
        "exp": {"machine_ref": "WS-01", "n": 1e20},
        "negzero": {"machine_ref": "WS-01", "n": -0.0},
        "float": {"machine_ref": "WS-01", "n": 1.0},
        "int": {"machine_ref": "WS-01", "n": 1},
        "nested": {
            "machine_ref": "WS-01",
            "nested": {"v": 1e20, "k": -0.0},
            "arr": [1e20, -0.0, 1],
        },
    }
    async with maker() as s:
        for label, details in cases.items():
            await append_audit(
                s,
                action=f"test.{label}",
                actor="u",
                target="t",
                request_id="req-1",
                details=details,
            )
        await s.commit()

    async with maker() as s2:
        assert await verify_chain(s2) == (True, None)
        rows = (
            (await s2.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
        )
        by_action = {r.action: r.details for r in rows}

        assert by_action["test.plain"] == {
            "machine_ref": "WS-01",
            "tool": "inventory_search",
        }
        # 1e20 -> integer canonical (không còn "1e+20")
        assert by_action["test.exp"]["n"] == 100000000000000000000
        assert isinstance(by_action["test.exp"]["n"], int)
        # -0.0 -> 0.0 (repr phân biệt được -0.0)
        assert repr(by_action["test.negzero"]["n"]) == "0.0"
        assert by_action["test.float"]["n"] == 1.0
        assert by_action["test.int"]["n"] == 1
        # nested + array canonical hóa đệ quy
        assert by_action["test.nested"]["nested"]["v"] == 100000000000000000000
        assert repr(by_action["test.nested"]["nested"]["k"]) == "0.0"
        assert by_action["test.nested"]["arr"][0] == 100000000000000000000
        assert repr(by_action["test.nested"]["arr"][1]) == "0.0"


async def test_v2_detects_request_id_tampering(maker):
    """`request_id` nằm trong hash v2 — sửa nó phải làm đứt chuỗi."""
    async with maker() as s:
        await append_audit(
            s,
            action="chat.query.inventory",
            actor="u",
            target="mc",
            request_id="req-orig",
            details={"machine_ref": "WS-01"},
        )
        await s.commit()

    async with maker() as s2:
        row = (await s2.execute(select(AuditLog))).scalar_one()
        row.request_id = "req-tampered"
        await s2.commit()

    async with maker() as s3:
        assert await verify_chain(s3) == (False, 0)


async def test_machine_id_is_not_hash_bound(maker):
    """`machine_id` là lookup mutable (R3): xóa máy SET NULL không được đứt chuỗi."""
    from app.db.models import Machine, Organization, OrgType

    async with maker() as s:
        org = Organization(name="Org A", type=OrgType.SO_BAN_NGANH.value)
        s.add(org)
        await s.flush()
        machine = Machine(
            org_id=org.id,
            machine_uuid="uuid-chat-1",
            hostname="PC-1",
            status="offline",
            enrolled_at=datetime.now(UTC),
        )
        s.add(machine)
        await s.flush()
        await append_audit(
            s,
            action="chat.query.inventory",
            actor="u",
            target="mc",
            request_id="req-1",
            machine_id=machine.id,
            details={"machine_ref": "PC-1"},
        )
        await s.commit()

    async with maker() as s2:
        assert await verify_chain(s2) == (True, None)
        row = (await s2.execute(select(AuditLog))).scalar_one()
        assert row.machine_id is not None
        row.machine_id = None  # mô phỏng route xóa máy: SET machine_id=NULL
        await s2.commit()

    async with maker() as s3:
        assert await verify_chain(s3) == (True, None)


async def test_concurrent_appends_stay_linear(maker):
    """8 transaction append song song vẫn tạo chuỗi tuyến tính (advisory lock)."""

    async def one(i: int) -> None:
        async with maker() as s:
            await append_audit(s, action=f"x{i}", actor="u", target="t")
            await s.commit()

    await asyncio.gather(*(one(i) for i in range(8)))

    async with maker() as s:
        assert await verify_chain(s) == (True, None)
