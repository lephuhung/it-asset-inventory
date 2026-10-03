"""Tests cho token budget reservation service (spec F11/R8/V3-7/V5)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import TokenReservation
from app.services import budget
from app.services.budget import (
    BudgetConflict,
    BudgetUnavailable,
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
    """Callback KHÔNG báo usage (None) → settle unknown → tính đủ envelope (spec R8)."""
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
            # KHÔNG truyền usage (mặc định None) = mất usage thật.
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


@pytest.mark.asyncio
async def test_external_callback_with_reported_zero_settles_zero(session_factory, monkeypatch):
    """Callback báo usage = 0 (biết chắc) → settled actual=0, KHÔNG phải envelope."""
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
            idempotency_key="cb-zero",
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
        assert row[0] == "settled" and row[1] == 0
        assert await charged(s, _today()) == 0


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
            # "" (không phải NULL) — mirror server_default của migration; worker
            # query `external_orchestrator != 'deepagent'` loại NULL.
            external_orchestrator="",
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


# ── Fix Round 1: rollover lock, ON CONFLICT, conflict-aware settle ──


@pytest.mark.asyncio
async def test_settle_locks_reservation_budget_date_not_today(db_engine, monkeypatch):
    """Settle phải khóa theo `budget_date` của reservation, KHÔNG phải hôm nay.

    Reservation của hôm qua; giữ advisory lock ngày hôm qua ở transaction khác →
    settle phải BỊ CHẶN. Bug cũ (lock `_utc_today()`) sẽ không bị chặn → test fail.
    """
    yesterday = _today() - timedelta(days=1)
    op = uuid.uuid4()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as s:
        s.add(
            TokenReservation(
                scope=SCOPE,
                operation_id=op,
                association_id=None,
                budget_date=yesterday,
                reserved=50,
                state="reserved",
            )
        )
        await s.commit()

    # "Hôm nay" KHÁC ngày reservation.
    monkeypatch.setattr(budget, "_utc_today", lambda: _today())

    lock_held = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with maker() as s:
            await budget._acquire_lock(s, yesterday)
            lock_held.set()
            await release.wait()
            await s.rollback()

    async def settler():
        async with maker() as s:
            await settle(s, scope=SCOPE, operation_id=op, actual=10)
            await s.commit()

    holder_task = asyncio.create_task(holder())
    await asyncio.wait_for(lock_held.wait(), timeout=5)
    settler_task = asyncio.create_task(settler())
    # Settle phải bị chặn bởi lock NGÀY HÔM QUA (không phải hôm nay).
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(settler_task), timeout=1.0)
    release.set()
    await asyncio.wait_for(holder_task, timeout=5)
    await asyncio.wait_for(settler_task, timeout=5)

    async with maker() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state, actual FROM token_reservations"
                    " WHERE scope=:sc AND operation_id=:op"
                ),
                {"sc": SCOPE, "op": op},
            )
        ).one()
        assert row[0] == "settled" and row[1] == 10


@pytest.mark.asyncio
async def test_reserve_handles_racing_insert_via_on_conflict(db_engine, monkeypatch):
    """Race qua nửa đêm: transaction khác chèn cùng (scope, op) giữa SELECT-miss và
    INSERT của reserve → reserve phải idempotent (ON CONFLICT), không ném UniqueViolation.
    """
    op = uuid.uuid4()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    today = _today()

    async def racing_charged(db, budget_date=None):
        # Side-effect: một transaction KHÁC đã chèn cùng (scope, op) sau khi reserve
        # SELECT-miss → mô phỏng retry vắt qua nửa đêm giữ lock ngày khác.
        async with maker() as other:
            other.add(
                TokenReservation(
                    scope=SCOPE,
                    operation_id=op,
                    association_id=None,
                    budget_date=today,
                    reserved=30,
                    state="reserved",
                )
            )
            await other.commit()
        return 0

    monkeypatch.setattr(budget, "charged", racing_charged)

    async with maker() as s:
        r = await reserve(s, scope=SCOPE, operation_id=op, envelope=30, budget=1000)
        await s.commit()
    assert r is not None and r.operation_id == op

    async with maker() as s:
        count = (
            await s.execute(
                text(
                    "SELECT count(*) FROM token_reservations"
                    " WHERE scope=:sc AND operation_id=:op"
                ),
                {"sc": SCOPE, "op": op},
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_settle_known_then_unknown_is_conflict(db_session):
    op = uuid.uuid4()
    await reserve(db_session, scope=SCOPE, operation_id=op, envelope=30, budget=1000)
    await settle(db_session, scope=SCOPE, operation_id=op, actual=25)
    with pytest.raises(BudgetConflict):
        await settle(db_session, scope=SCOPE, operation_id=op, actual=None)
    assert await charged(db_session, _today()) == 25


@pytest.mark.asyncio
async def test_settle_unknown_then_known_is_conflict(db_session):
    op = uuid.uuid4()
    await reserve(db_session, scope=SCOPE, operation_id=op, envelope=30, budget=1000)
    await settle(db_session, scope=SCOPE, operation_id=op, actual=None)
    with pytest.raises(BudgetConflict):
        await settle(db_session, scope=SCOPE, operation_id=op, actual=25)
    assert await charged(db_session, _today()) == 30


@pytest.mark.asyncio
async def test_reserve_translates_db_error_to_budget_unavailable(db_session, monkeypatch):
    from sqlalchemy.exc import OperationalError

    async def boom(db, d):
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr(budget, "_acquire_lock", boom)
    with pytest.raises(BudgetUnavailable):
        await reserve(
            db_session, scope=SCOPE, operation_id=uuid.uuid4(), envelope=1, budget=10
        )


@pytest.mark.asyncio
async def test_settle_translates_db_error_to_budget_unavailable(db_session, monkeypatch):
    from sqlalchemy.exc import OperationalError

    op = uuid.uuid4()
    await reserve(db_session, scope=SCOPE, operation_id=op, envelope=1, budget=10)

    async def boom(db, d):
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr(budget, "_acquire_lock", boom)
    with pytest.raises(BudgetUnavailable):
        await settle(db_session, scope=SCOPE, operation_id=op, actual=1)


@pytest.mark.asyncio
async def test_settle_unknown_fresh_closes_reservation(session_factory):
    """Cleanup dùng session MỚI vẫn settle được reservation (đường hủy/lỗi)."""
    from app.services import dfir_investigation as inv_svc

    op = uuid.uuid4()
    async with session_factory() as s:
        await reserve(s, scope=SCOPE, operation_id=op, envelope=40, budget=None)
        await s.commit()

    await inv_svc._settle_unknown_fresh(scope=SCOPE, operation_id=op)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope=:sc AND operation_id=:op"
                ),
                {"sc": SCOPE, "op": op},
            )
        ).one()
        assert row[0] == "unknown"


@pytest.mark.asyncio
async def test_local_analysis_releases_lock_before_llm_call(session_factory, monkeypatch):
    """Reservation đã commit + advisory lock đã nhả TRƯỚC khi gọi LLM.

    Trong lúc fake-LLM "chạy", một admission khác phải chạy được ngay (không block),
    và reservation đã commit phải visible. Nếu lock còn giữ, admission trong LLM sẽ
    block → `wait_for` timeout → test fail.
    """
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    async def _noop_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _noop_notify)
    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "test-key")

    observed: dict[str, bool] = {}

    class _Resp:
        content = "### 1. Low\n"
        input_tokens = 1
        output_tokens = 1
        total_tokens = 2
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
            # Trong lúc "LLM chạy": admission mới phải chạy được ngay.
            async with session_factory() as other:
                r = await reserve(
                    other,
                    scope="chat_turn",
                    operation_id=uuid.uuid4(),
                    envelope=5,
                    budget=None,
                )
                await other.commit()
                observed["reserved_during_llm"] = r is not None
            async with session_factory() as other:
                observed["visible"] = await charged(other, _today()) >= 2
            return _Resp()

    monkeypatch.setattr(inv_svc, "LlmClient", _FakeLlm)

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        await asyncio.wait_for(inv_svc._state_analyze(s, inv), timeout=10)

    assert observed.get("reserved_during_llm") is True
    assert observed.get("visible") is True


async def _seed_completed_investigation(session_factory):
    """Investigation đã 'completed' + 1 message, để chạy chat_with_llm."""
    from app.db.models import (
        DfirInvestigation,
        DfirInvestigationMessage,
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
            full_name="T6c",
            email=f"t6c-{uuid.uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        machine = Machine(
            hostname=f"T6C-{uuid.uuid4()}", org_id=org.id, machine_uuid=str(uuid.uuid4())
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
            velociraptor_client_id="C.t6c",
            artifacts=[],
            status="completed",
            requested_by=user.id,
        )
        s.add(inv)
        await s.flush()
        s.add(DfirInvestigationMessage(investigation_id=inv.id, role="user", content="q"))
        await s.commit()
        return inv.id


@pytest.mark.asyncio
async def test_chat_with_llm_cancellation_settles_unknown(session_factory, monkeypatch):
    """Hủy giữa LLM call → reservation settle unknown (không bỏ mặc reserved)."""
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    class _CancelLlm:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, messages):
            raise asyncio.CancelledError()

    monkeypatch.setattr(inv_svc, "LlmClient", _CancelLlm)

    inv_id = await _seed_completed_investigation(session_factory)
    async with session_factory() as s:
        with pytest.raises(asyncio.CancelledError):
            await inv_svc.chat_with_llm(
                s, investigation_id=str(inv_id), user_message="hi"
            )

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_chat' AND association_id=:op"
                ),
                {"op": inv_id},
            )
        ).one_or_none()
        assert row is not None and row[0] == "unknown"


@pytest.mark.asyncio
async def test_local_analysis_cancellation_settles_unknown(session_factory, monkeypatch):
    """Hủy giữa _state_analyze → reservation settle unknown."""
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    class _CancelLlm:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, messages):
            raise asyncio.CancelledError()

    monkeypatch.setattr(inv_svc, "LlmClient", _CancelLlm)

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        with pytest.raises(asyncio.CancelledError):
            await inv_svc._state_analyze(s, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one_or_none()
        assert row is not None and row[0] == "unknown"


# ── Fix Round 2: DB-failure translation, settlement coverage, cfg-independent ──


class _CommitBoomSession:
    """Bọc session: delegate mọi thứ, riêng `commit` ném OperationalError.

    Dùng chung cho cả admission lẫn settlement: chứng minh lỗi ở chính bước
    `commit` cũng được dịch thành `BudgetUnavailable` (không escape dưới dạng
    lỗi DB thô).
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self):
        raise OperationalError("COMMIT", {}, Exception("commit down"))


class _NthCommitBoom:
    """Bọc session: commit thứ `fail_on` ném OperationalError, còn lại delegate."""

    def __init__(self, inner, *, fail_on: int):
        self._inner = inner
        self._n = 0
        self._fail_on = fail_on

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self):
        self._n += 1
        if self._n == self._fail_on:
            raise OperationalError("COMMIT", {}, Exception("commit down"))
        return await self._inner.commit()


@pytest.mark.asyncio
async def test_admit_budget_translates_commit_failure(session_factory, monkeypatch):
    """`_admit_budget`: lỗi ở chính `commit` admission → `BudgetUnavailable` (Finding 1)."""
    from app.db.models import LlmConfig
    from app.services import dfir_investigation as inv_svc
    from app.services.budget import BudgetUnavailable

    async with session_factory() as s:
        cfg = LlmConfig(
            id=1, enabled=True, provider="ollama",
            base_url="http://127.0.0.1:11434/v1", model="m",
            daily_token_budget=100_000, tokens_used_today=0,
        )
        s.add(cfg)
        await s.flush()
        with pytest.raises(BudgetUnavailable):
            await inv_svc._admit_budget(
                _CommitBoomSession(s),
                scope="investigation_analysis",
                operation_id=uuid.uuid4(),
                association_id=None,
                cfg=cfg,
            )


@pytest.mark.asyncio
async def test_local_analysis_admission_commit_failure_fails_closed(session_factory, monkeypatch):
    """`_state_analyze`: commit admission lỗi → investigation failed + chat_budget_unavailable."""
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        # commit #1: persist llm_provider/model; commit #2: admission (lỗi).
        wrapped = _NthCommitBoom(s, fail_on=2)
        await inv_svc._state_analyze(wrapped, inv)

    async with session_factory() as s:
        stored = await s.get(DfirInvestigation, inv_id)
        assert stored.status == "failed"
        assert "chat_budget_unavailable" in (stored.error or "")


async def _seed_dispatchable_no_velo(session_factory):
    """Investigation DeepAgent 'analyzing' + reservation, KHÔNG có VelociraptorConfig."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from app.core.security import encrypt_aes_gcm
    from app.db.models import (
        DfirInvestigation,
        LlmConfig,
        Machine,
        MachineCurrent,
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
            full_name="T6d",
            email=f"t6d-{uuid.uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        machine = Machine(
            hostname=f"T6D-{uuid.uuid4()}", org_id=org.id, machine_uuid=str(uuid.uuid4())
        )
        s.add(machine)
        await s.flush()
        s.add(
            MachineCurrent(
                machine_id=machine.id, collected_at=_dt.now(_UTC), platform="windows"
            )
        )
        cfg = LlmConfig(
            id=1, enabled=True, provider="ollama",
            base_url="http://127.0.0.1:11434/v1",
            api_key_encrypted=encrypt_aes_gcm("k"), model="m",
            daily_token_budget=100_000, tokens_used_today=0,
        )
        s.add(cfg)
        inv = DfirInvestigation(
            machine_id=machine.id,
            velociraptor_client_id="C.t6d",
            artifacts=[],
            status="analyzing",
            external_orchestrator="deepagent",
            hermes_status="dispatching",
            requested_by=user.id,
        )
        s.add(inv)
        await s.flush()
        r = await reserve(
            s,
            scope="investigation_analysis",
            operation_id=inv.id,
            association_id=inv.id,
            envelope=500,
            budget=cfg.daily_token_budget,
        )
        assert r is not None
        await s.commit()
        return inv.id


@pytest.mark.asyncio
async def test_dispatch_config_missing_settles_unknown(session_factory, monkeypatch):
    """Thiếu VelociraptorConfig sau admission → definitive → settle unknown (Finding 2)."""
    from app.core import config as config_mod
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    inv_id = await _seed_dispatchable_no_velo(session_factory)

    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        with pytest.raises(inv_svc.DispatchFailed):
            await inv_svc._state_dispatch_deepagent(s, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "unknown"
        stored = await s.get(DfirInvestigation, inv_id)
        assert stored.status == "failed"
        assert stored.hermes_status == "dispatch_failed"


@pytest.mark.asyncio
async def test_local_analysis_unexpected_error_settles_unknown(session_factory, monkeypatch):
    """Lỗi KHÔNG phải LlmError sau khi reserve → settle unknown rồi re-raise (Finding 2)."""
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    class _BoomLlm:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, messages):
            raise RuntimeError("unexpected non-LLM failure")

    monkeypatch.setattr(inv_svc, "LlmClient", _BoomLlm)

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        with pytest.raises(RuntimeError):
            await inv_svc._state_analyze(s, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "unknown"


@pytest.mark.asyncio
async def test_local_analysis_survives_settlement_failure(session_factory, monkeypatch):
    """Settle lỗi → rollback expire ORM; notification vẫn chạy dùng snapshot (Finding 3).

    Nếu code đọc `inv.*` sau rollback sẽ ném MissingGreenlet và test fail.
    """
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    calls: dict = {}

    async def _record_notify(*args, **kwargs):
        calls["status"] = kwargs.get("status")
        calls["investigation_id"] = kwargs.get("investigation_id")

    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _record_notify)
    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    class _Resp:
        content = "### 1. Low\n"
        input_tokens = 3
        output_tokens = 2
        total_tokens = 5
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

    async def _boom_settle(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("settle down"))

    monkeypatch.setattr(inv_svc, "settle", _boom_settle)

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        await inv_svc._state_analyze(s, inv)  # phải KHÔNG ném MissingGreenlet

    assert calls.get("status") == "completed"
    assert calls.get("investigation_id") == inv_id
    async with session_factory() as s:
        stored = await s.get(DfirInvestigation, inv_id)
        assert stored.status == "completed"


@pytest.mark.asyncio
async def test_external_callback_settles_without_llm_config(session_factory, monkeypatch):
    """Callback tới khi KHÔNG còn LlmConfig → vẫn settle reservation (Finding 4)."""
    from app.db.models import LlmConfig
    from app.services import dfir_investigation as inv_svc

    async def _noop_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _noop_notify)

    inv_id = await _seed_external_investigation(session_factory, envelope=900)
    async with session_factory() as s:
        cfg = await s.get(LlmConfig, 1)
        assert cfg is not None
        await s.delete(cfg)
        await s.commit()

    async with session_factory() as s:
        await inv_svc.submit_external_result(
            s,
            investigation_id=str(inv_id),
            api_key_id=None,
            report_markdown="# report",
            severity="low",
            input_tokens=10,
            output_tokens=5,
            external_job_id="deepagent-job-1",
            idempotency_key="cb-nocfg",
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
        assert row[0] == "settled" and row[1] == 15


# ── Fix Round 3: failure/cancel coverage + caller-boundary snapshots ──


class _RollbackThenBoomCommit:
    """Bọc session: commit thứ `fail_on` rollback (mô phỏng flush lỗi thật làm
    expire ORM) rồi ném OperationalError; các commit khác delegate.
    """

    def __init__(self, inner, *, fail_on: int):
        self._inner = inner
        self._n = 0
        self._fail_on = fail_on

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self):
        self._n += 1
        if self._n == self._fail_on:
            # Flush lỗi thật trong SQLAlchemy rollback + expire mọi ORM object.
            await self._inner.rollback()
            raise OperationalError("COMMIT", {}, Exception("commit down"))
        return await self._inner.commit()


async def _seed_dispatchable_with_velo(session_factory):
    """`_seed_dispatchable_no_velo` + VelociraptorConfig → pre-POST block chạy tới commit."""
    from app.core.security import encrypt_aes_gcm
    from app.db.models import VelociraptorConfig

    inv_id = await _seed_dispatchable_no_velo(session_factory)
    async with session_factory() as s:
        s.add(
            VelociraptorConfig(
                id=1,
                enabled=True,
                server_url="https://velo.test/",
                client_config_encrypted=encrypt_aes_gcm("api_client_yaml: test"),
            )
        )
        await s.commit()
    return inv_id


async def _seed_pending_deepagent(session_factory):
    """Investigation DeepAgent 'pending' để worker claim + dispatch trong test."""
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
            full_name="T6w",
            email=f"t6w-{uuid.uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        machine = Machine(
            hostname=f"T6W-{uuid.uuid4()}", org_id=org.id, machine_uuid=str(uuid.uuid4())
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
            velociraptor_client_id="C.t6w",
            artifacts=[],
            status="pending",
            external_orchestrator="deepagent",
            requested_by=user.id,
        )
        s.add(inv)
        await s.flush()
        inv_id = inv.id
        await s.commit()
        return inv_id


def _enable_deepagent(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")


def _fake_llm_class(response_cls):
    class _FakeLlm:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, messages):
            return response_cls()

    return _FakeLlm


class _OkResp:
    content = "### 1. Low\n"
    input_tokens = 3
    output_tokens = 2
    total_tokens = 5
    estimated_cost_usd = 0.0
    model = "m"


@pytest.mark.asyncio
async def test_chat_persistence_commit_failure_settles_unknown(session_factory, monkeypatch):
    """Finding 1a: commit persist Q&A lỗi → reservation vẫn được đóng (unknown)."""
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")
    monkeypatch.setattr(inv_svc, "LlmClient", _fake_llm_class(_OkResp))

    inv_id = await _seed_completed_investigation(session_factory)
    async with session_factory() as s:
        # commit #1 = admission, commit #2 = persist Q&A (lỗi).
        wrapped = _NthCommitBoom(s, fail_on=2)
        with pytest.raises(OperationalError):
            await inv_svc.chat_with_llm(
                wrapped, investigation_id=str(inv_id), user_message="hi"
            )

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_chat' AND association_id=:op"
                ),
                {"op": inv_id},
            )
        ).one_or_none()
        assert row is not None and row[0] == "unknown"


@pytest.mark.asyncio
async def test_dispatch_pre_post_cancelled_settles_unknown(session_factory, monkeypatch):
    """Finding 1b: CancelledError TRƯỚC POST → reservation đóng (unknown)."""
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    _enable_deepagent(monkeypatch)
    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    # `_load_custom_artifact_refs` chạy BÊN TRONG block pre-POST, sau admission.
    monkeypatch.setattr(inv_svc, "_load_custom_artifact_refs", _cancel)

    inv_id = await _seed_dispatchable_with_velo(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        with pytest.raises(asyncio.CancelledError):
            await inv_svc._state_dispatch_deepagent(s, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "unknown"
        stored = await s.get(DfirInvestigation, inv_id)
        assert stored.status == "failed"
        assert stored.hermes_status == "dispatch_failed"


@pytest.mark.asyncio
async def test_local_analysis_llm_error_handler_failure_settles_unknown(
    session_factory, monkeypatch
):
    """Finding 1c: persist trạng thái thất bại lỗi (sau settle) → vẫn đóng reservation.

    Commit trạng thái là commit #4 trong nhánh lỗi LLM (sau commit admission #2 và
    commit settle #3). Handler phải settle TRƯỚC commit trạng thái, nên khi #4 lỗi
    reservation đã ở `unknown` (không bị bỏ mặc `reserved`).
    """
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc
    from app.services.llm import LlmError

    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    class _ErrLlm:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, messages):
            raise LlmError("llm boom")

    monkeypatch.setattr(inv_svc, "LlmClient", _ErrLlm)

    inv_id = await _seed_analyzing_investigation(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        # #1 persist provider/model, #2 admission, #3 settle, #4 status (lỗi).
        wrapped = _NthCommitBoom(s, fail_on=4)
        with pytest.raises(OperationalError):
            await inv_svc._state_analyze(wrapped, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "unknown"


@pytest.mark.asyncio
async def test_worker_survives_settlement_failure(client, session_factory, monkeypatch):
    """Finding 2 (hành vi): settle lỗi KHÔNG làm worker sập — vẫn processed=1/errors=0.

    `_finalize_usage` lỗi bị nuốt (rollback + log) nên `_process_one` vẫn kết thúc OK;
    worker boundary phải tổng hợp kết quả bằng id đã chụp, không đọc lại ORM.
    """
    from app.services import dfir_investigation as inv_svc

    async def _noop_notify(*args, **kwargs):
        return None

    async def _boom_settle(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("settle down"))

    monkeypatch.setattr(inv_svc, "settle", _boom_settle)
    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")
    monkeypatch.setattr(inv_svc, "LlmClient", _fake_llm_class(_OkResp))
    monkeypatch.setattr(inv_svc, "_notify_investigation_result", _noop_notify)

    await _seed_analyzing_investigation(session_factory)
    result = await inv_svc.run_pending_investigations()

    assert result.get("processed") == 1
    assert result.get("errors") == 0


@pytest.mark.asyncio
async def test_worker_boundary_survives_expired_orm(client, session_factory, monkeypatch):
    """Finding 2 (guard): helper rollback làm expire ORM (object có thay đổi pending)
    rồi raise DispatchFailed → worker handler KHÔNG được đọc `inv.*` đã expire
    (MissingGreenlet).
    """
    from app.services import dfir_investigation as inv_svc

    async def _boom_dispatch(db, inv):
        # Object có thay đổi pending → rollback expire nó (như flush/commit lỗi).
        inv.status = "analyzing"
        await db.rollback()
        raise inv_svc.DispatchFailed("simulated rollback then definitive fail")

    monkeypatch.setattr(inv_svc, "_state_dispatch_deepagent", _boom_dispatch)

    await _seed_pending_deepagent(session_factory)
    result = await inv_svc.run_pending_investigations()

    assert result.get("errors") == 1


@pytest.mark.asyncio
async def test_dispatch_pre_post_flush_failure_settles_unknown(session_factory, monkeypatch):
    """Finding 3: flush lỗi ở commit pre-POST → ORM expire; cleanup vẫn settle +
    mark failed mà KHÔNG đọc `inv.id` đã expire (MissingGreenlet).
    """
    from app.db.models import DfirInvestigation
    from app.services import dfir_investigation as inv_svc

    _enable_deepagent(monkeypatch)
    monkeypatch.setattr(inv_svc, "_decrypt_api_key", lambda enc: "k")

    inv_id = await _seed_dispatchable_with_velo(session_factory)
    async with session_factory() as s:
        inv = await s.get(DfirInvestigation, inv_id)
        # #1 admission, #2 pre-POST (lỗi + rollback → expire ORM).
        wrapped = _RollbackThenBoomCommit(s, fail_on=2)
        with pytest.raises(inv_svc.DispatchFailed):
            await inv_svc._state_dispatch_deepagent(wrapped, inv)

    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT state FROM token_reservations"
                    " WHERE scope='investigation_analysis' AND operation_id=:op"
                ),
                {"op": inv_id},
            )
        ).one()
        assert row[0] == "unknown"
        stored = await s.get(DfirInvestigation, inv_id)
        assert stored.status == "failed"
        assert stored.hermes_status == "dispatch_failed"


# ── Fix Round 4: settle-commit DB-error translation to BudgetUnavailable ──


@pytest.mark.asyncio
async def test_settle_commit_failure_translates_to_budget_unavailable(session_factory):
    """Finding 3: commit ở bước ghi nhận usage lỗi → dịch thành `chat_budget_unavailable`.

    `settle()` chỉ dịch lỗi ở đoạn đọc/khóa/ghi hàng; lỗi `commit()` nằm ngoài handler
    đó nên `_settle_usage_or_unavailable` phải tự dịch, nếu không nó escape thành lỗi
    DB thô (OperationalError) thay vì category `chat_budget_unavailable`.
    """
    from app.services import dfir_investigation as inv_svc

    op = uuid.uuid4()
    async with session_factory() as s:
        await reserve(
            s,
            scope="investigation_analysis",
            operation_id=op,
            association_id=op,
            envelope=10,
            budget=None,
        )
        await s.commit()

    async with session_factory() as s:
        wrapped = _CommitBoomSession(s)
        with pytest.raises(BudgetUnavailable) as ei:
            await inv_svc._settle_usage_or_unavailable(
                wrapped,
                scope="investigation_analysis",
                operation_id=op,
                actual=3,
                cfg=None,
            )
        assert "chat_budget_unavailable" in str(ei.value)


@pytest.mark.asyncio
async def test_finalize_usage_keeps_completed_work_on_settle_db_failure(session_factory):
    """`_finalize_usage` best-effort: settle-commit lỗi KHÔNG được ném ra (spec R8:
    "không huỷ kết quả đã hoàn thành").
    """
    from app.services import dfir_investigation as inv_svc

    op = uuid.uuid4()
    async with session_factory() as s:
        await reserve(
            s,
            scope="investigation_analysis",
            operation_id=op,
            association_id=op,
            envelope=10,
            budget=None,
        )
        await s.commit()

    async with session_factory() as s:
        wrapped = _CommitBoomSession(s)
        # Không ném: đã dịch thành BudgetUnavailable rồi nuốt trong nhánh best-effort.
        await inv_svc._finalize_usage(
            wrapped,
            scope="investigation_analysis",
            operation_id=op,
            actual=3,
            cfg=None,
        )
