"""Tests cho token budget reservation service (spec F11/R8/V3-7/V5)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services import budget
from app.services.budget import (
    BudgetConflict,
    charged,
    reserve,
    settle,
)

SCOPE = "chat_turn"


@pytest_asyncio.fixture
async def db_session(session_factory):
    async with session_factory() as s:
        yield s


def _today() -> date:
    return datetime.now(UTC).date()


async def reserve_for(engine, *, op, envelope, budget_amount, scope=SCOPE, association_id=None):
    """Reserve trong 1 session riêng rồi commit (để advisory lock serialize)."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        r = await reserve(
            s,
            scope=scope,
            operation_id=op,
            association_id=association_id,
            envelope=envelope,
            budget=budget_amount,
        )
        await s.commit()
        return r


# ── Admission ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admission_never_exceeds_budget(db_engine):
    """5 reserve envelope=30 song song, budget=100 → nhiều nhất 3 thành công."""
    budget_amount = 100
    results = await asyncio.gather(
        *[
            reserve_for(db_engine, op=uuid.uuid4(), envelope=30, budget_amount=budget_amount)
            for _ in range(5)
        ]
    )
    granted = sum(r is not None for r in results)
    assert granted == 3, f"charged vượt trần: {granted} reservation cho budget 100/30"
    assert granted * 30 <= budget_amount


@pytest.mark.asyncio
async def test_over_budget_returns_none(db_session):
    r1 = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=80, budget=100
    )
    assert r1 is not None
    r2 = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=30, budget=100
    )
    assert r2 is None  # 80 + 30 > 100
    assert await charged(db_session, _today()) == 80


@pytest.mark.asyncio
async def test_budget_none_is_unlimited(db_session):
    for _ in range(5):
        r = await reserve(
            db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=10_000, budget=None
        )
        assert r is not None


@pytest.mark.asyncio
async def test_invalid_scope_rejected(db_session):
    with pytest.raises(ValueError):
        await reserve(
            db_session, scope="bogus", operation_id=uuid.uuid4(), envelope=1, budget=10
        )


# ── Settle & invariant ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_charges_envelope(db_session):
    r = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=30, budget=1000
    )
    await settle(db_session, scope=SCOPE, operation_id=r.operation_id, actual=None)
    assert await charged(db_session, _today()) == 30


@pytest.mark.asyncio
async def test_settled_charges_actual_not_envelope(db_session):
    r = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=500, budget=1000
    )
    await settle(db_session, scope=SCOPE, operation_id=r.operation_id, actual=42)
    assert await charged(db_session, _today()) == 42


@pytest.mark.asyncio
async def test_settle_idempotent_same_actual(db_session):
    op = uuid.uuid4()
    await reserve(db_session, scope=SCOPE, operation_id=op, envelope=30, budget=1000)
    await settle(db_session, scope=SCOPE, operation_id=op, actual=25)
    await settle(db_session, scope=SCOPE, operation_id=op, actual=25)  # no-op
    assert await charged(db_session, _today()) == 25


@pytest.mark.asyncio
async def test_settle_conflicting_actual_rejected(db_session):
    op = uuid.uuid4()
    await reserve(db_session, scope=SCOPE, operation_id=op, envelope=30, budget=1000)
    await settle(db_session, scope=SCOPE, operation_id=op, actual=25)
    with pytest.raises(BudgetConflict):
        await settle(db_session, scope=SCOPE, operation_id=op, actual=99)
    assert await charged(db_session, _today()) == 25


@pytest.mark.asyncio
async def test_settle_without_reservation_is_noop(db_session):
    await settle(db_session, scope=SCOPE, operation_id=uuid.uuid4(), actual=10)
    assert await charged(db_session, _today()) == 0


@pytest.mark.asyncio
async def test_charged_invariant_mixed_states(db_session):
    reserved = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=100, budget=None
    )
    settled = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=100, budget=None
    )
    unknown = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=100, budget=None
    )
    await settle(db_session, scope=SCOPE, operation_id=settled.operation_id, actual=7)
    await settle(db_session, scope=SCOPE, operation_id=unknown.operation_id, actual=None)
    # reserved(100) + settled_actual(7) + unknown_reserved(100)
    assert reserved is not None
    assert await charged(db_session, _today()) == 207


# ── Idempotency & rollover ───────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_same_operation_does_not_double_charge(db_session):
    op = uuid.uuid4()
    r1 = await reserve(db_session, scope=SCOPE, operation_id=op, envelope=30, budget=100)
    r2 = await reserve(db_session, scope=SCOPE, operation_id=op, envelope=30, budget=100)
    assert r1 is not None and r2 is not None
    assert r2.operation_id == op
    assert await charged(db_session, _today()) == 30


@pytest.mark.asyncio
async def test_new_operation_reserves_fresh(db_session):
    await reserve(db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=30, budget=100)
    await reserve(db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=30, budget=100)
    assert await charged(db_session, _today()) == 60


@pytest.mark.asyncio
async def test_association_id_is_link_only(db_session):
    inv_id = uuid.uuid4()
    for scope, assoc in (
        ("chat_turn", None),
        ("investigation_chat", inv_id),
        ("investigation_analysis", inv_id),
    ):
        r = await reserve(
            db_session,
            scope=scope,
            operation_id=uuid.uuid4(),
            association_id=assoc,
            envelope=10,
            budget=None,
        )
        assert r is not None and r.association_id == assoc


@pytest.mark.asyncio
async def test_rollover_by_date(db_session, monkeypatch):
    """Reservation ngày mai không tính vào ngân sách hôm nay."""
    d0 = date(2026, 1, 1)
    monkeypatch.setattr(budget, "_utc_today", lambda: d0)
    await reserve(db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=40, budget=100)
    assert await charged(db_session, d0) == 40

    monkeypatch.setattr(budget, "_utc_today", lambda: d0 + timedelta(days=1))
    assert await charged(db_session, _today()) == 0
    r = await reserve(
        db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=90, budget=100
    )
    assert r is not None  # ngân sách ngày mới còn trống

    assert await charged(db_session, d0) == 40
    assert await charged(db_session, d0 + timedelta(days=1)) == 90


@pytest.mark.asyncio
async def test_concurrent_same_operation_is_single_charge(db_engine):
    """Hai reserve song song cùng (scope, operation_id) → chỉ 1 dòng, charged = envelope."""
    op = uuid.uuid4()
    results = await asyncio.gather(
        reserve_for(db_engine, op=op, envelope=30, budget_amount=1000),
        reserve_for(db_engine, op=op, envelope=30, budget_amount=1000),
    )
    assert all(r is not None for r in results)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as s:
        count = (
            await s.execute(
                text(
                    "SELECT count(*) FROM token_reservations"
                    " WHERE scope = :sc AND operation_id = :op"
                ),
                {"sc": SCOPE, "op": op},
            )
        ).scalar_one()
        assert count == 1
        assert await charged(s, _today()) == 30


# ── Integration: dfir_investigation settle wiring ────────────────


async def _seed_external_investigation(session_factory, *, envelope: int):
    """1 investigation DeepAgent đang 'analyzing' + reservation đã giữ chỗ."""
    from app.db.models import (
        DfirInvestigation,
        LlmConfig,
        Machine,
        Organization,
        OrgType,
        User,
        UserRole,
    )

    async with session_factory() as s:
        org = Organization(name=f"Org {uuid.uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        user = User(
            org_id=org.id,
            full_name="T6",
            email=f"t6-{uuid.uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        machine = Machine(hostname=f"T6-{uuid.uuid4()}", org_id=org.id, machine_uuid=str(uuid.uuid4()))
        s.add(machine)
        await s.flush()
        cfg = LlmConfig(
            id=1, enabled=True, provider="ollama", base_url="http://127.0.0.1:11434/v1",
            model="m", daily_token_budget=100_000, tokens_used_today=0,
        )
        s.add(cfg)
        inv = DfirInvestigation(
            machine_id=machine.id,
            velociraptor_client_id="C.t6",
            artifacts=[],
            status="analyzing",
            external_orchestrator="deepagent",
            external_job_id="deepagent-job-1",
            hermes_status="dispatched",
            requested_by=user.id,
        )
        s.add(inv)
        await s.flush()
        # Dispatch đã reserve envelope cho operation_id=inv.id.
        r = await reserve(
            s,
            scope="investigation_analysis",
            operation_id=inv.id,
            association_id=inv.id,
            envelope=envelope,
            budget=cfg.daily_token_budget,
        )
        assert r is not None
        await s.commit()
        return inv.id


@pytest.mark.asyncio
async def test_external_callback_settles_dispatch_reservation(session_factory, monkeypatch):
    """Dispatch reserve → callback settle với usage thật (không double-charge)."""
    from app.services import dfir_investigation as inv_svc

    async def _noop_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _noop_notify)

    inv_id = await _seed_external_investigation(session_factory, envelope=1000)
    async with session_factory() as s:
        assert await charged(s, _today()) == 1000  # envelope đang giữ chỗ

    async with session_factory() as s:
        await inv_svc.submit_external_result(
            s,
            investigation_id=str(inv_id),
            api_key_id=None,
            report_markdown="# report",
            severity="low",
            input_tokens=30,
            output_tokens=12,
            external_job_id="deepagent-job-1",
            idempotency_key="cb-1",
        )

    async with session_factory() as s:
        # settled → charged dùng actual thật (42), không phải envelope 1000
        assert await charged(s, _today()) == 42
        cfg = await s.get(inv_svc.LlmConfig, 1)
        assert cfg is not None and cfg.tokens_used_today == 42


@pytest.mark.asyncio
async def test_external_callback_without_usage_charges_envelope(session_factory, monkeypatch):
    """Callback không báo usage → settle unknown → tính đủ envelope (spec R8)."""
    from app.services import dfir_investigation as inv_svc

    async def _noop_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _noop_notify)

    inv_id = await _seed_external_investigation(session_factory, envelope=700)
    async with session_factory() as s:
        await inv_svc.submit_external_result(
            s,
            investigation_id=str(inv_id),
            api_key_id=None,
            report_markdown="# report",
            severity="low",
            input_tokens=0,
            output_tokens=0,
            external_job_id="deepagent-job-1",
            idempotency_key="cb-2",
        )

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state, actual FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "unknown"
        assert await charged(s, _today()) == 700


async def _seed_analyzing_investigation(session_factory):
    """1 investigation local (không external) đang 'analyzing' để chạy _state_analyze."""
    from app.db.models import (
        DfirInvestigation,
        LlmConfig,
        Machine,
        Organization,
        OrgType,
        User,
        UserRole,
    )

    async with session_factory() as s:
        org = Organization(name=f"Org {uuid.uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        user = User(
            org_id=org.id,
            full_name="T6-local",
            email=f"t6l-{uuid.uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        machine = Machine(
            hostname=f"T6L-{uuid.uuid4()}", org_id=org.id, machine_uuid=str(uuid.uuid4())
        )
        s.add(machine)
        await s.flush()
        s.add(
            LlmConfig(
                id=1,
                enabled=True,
                provider="ollama",
                base_url="http://127.0.0.1:11434/v1",
                model="m",
                daily_token_budget=100_000,
                tokens_used_today=0,
            )
        )
        await s.flush()
        inv = DfirInvestigation(
            machine_id=machine.id,
            velociraptor_client_id="C.t6-local",
            artifacts=[],
            raw_artifacts={},
            status="analyzing",
            requested_by=user.id,
        )
        s.add(inv)
        await s.commit()
        return inv.id


async def test_local_analysis_reserves_then_settles_actual(session_factory, monkeypatch):
    """_state_analyze: reserve trước LLM, settle actual sau; tokens_used_today đồng bộ."""
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    async def _noop_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _noop_notify)
    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "test-key")

    class _Resp:
        content = "### 1. Low\nMức độ nghiêm trọng: low\n"
        input_tokens = 11
        output_tokens = 5
        total_tokens = 16
        estimated_cost_usd = 0.0
        model = "m"

    class _FakeLlm:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, messages):
            return _Resp()

    monkeypatch.setattr(inv_svc, "LlmClient", _FakeLlm)

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        await inv_svc._state_analyze(s, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state, actual FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "settled" and row[1] == 16
        assert await charged(s, _today()) == 16
        cfg = await s.get(inv_svc.LlmConfig, 1)
        assert cfg is not None and cfg.tokens_used_today == 16
        stored = await s.get(DfirInvestigation, inv_id)
        assert stored is not None and stored.status == "completed"
