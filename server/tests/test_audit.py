"""Unit tests — audit log hash chain (append-only + phát hiện giả mạo)."""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import delete, select

from app.core.audit import append_audit, verify_chain
from app.db.models import AuditLog


@pytest_asyncio.fixture
async def clean_db(db):
    await db.execute(delete(AuditLog))
    await db.commit()
    return db


async def test_chain_appends_and_verifies(clean_db):
    await append_audit(clean_db, action="token.create", actor="u1", target="tok1")
    await append_audit(clean_db, action="enroll.success", actor="agent:m1", target="m1")
    await append_audit(clean_db, action="auth.login", actor="u1")
    await clean_db.commit()

    ok, bad_idx = await verify_chain(clean_db)
    assert ok is True
    assert bad_idx is None


async def test_chain_detects_tampering(clean_db):
    await append_audit(clean_db, action="a", actor="u1")
    await append_audit(clean_db, action="b", actor="u2")
    await append_audit(clean_db, action="c", actor="u3")
    await clean_db.commit()

    # Giả mạo dòng giữa (sửa action) — phải phát hiện đứt chuỗi
    middle = (await clean_db.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()[1]
    middle.action = "b_hacked"
    await clean_db.commit()

    ok, bad_idx = await verify_chain(clean_db)
    assert ok is False
    assert bad_idx == 1


async def test_genesis_hash(clean_db):
    await append_audit(clean_db, action="first")
    await clean_db.commit()
    row = (await clean_db.execute(select(AuditLog))).scalar_one()
    assert row.prev_hash == "0" * 64
