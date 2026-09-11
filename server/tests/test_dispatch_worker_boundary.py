"""BLOCKER 1 — P1-5 DeepAgent ambiguous dispatch vượt qua production worker boundary.

Bug trước fix: `_state_dispatch_deepagent()` phân loại timeout / connection error /
HTTP 5xx / 408 / 429 thành ambiguous, ghi `hermes_status="dispatch_uncertain"`, sau
đó `raise` một generic `LlmError` hoặc để bubble lên. Production worker `run_pending_investigations()`
bắt generic `Exception` trong loop claim DeepAgent → ghi `inv.status = "failed"`,
`inv.completed_at = ...`, commit. Bug ở đây: `dispatch_uncertain` bị worker overwrite
thành terminal-failed.

Acceptance: ambiguity phải KHÔNG bao giờ bị worker set thành `failed`. Tạo typed
exceptions (`DispatchUncertain`, `DispatchFailed`) để worker phân biệt.

NOTE on test approach: gọi `run_pending_investigations()` (production path),
không gọi riêng `_state_dispatch_deepagent()` — đây chính là lý do fix hiện tại
chưa bắt được regression.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.core import config as config_mod
from app.db.models import DfirInvestigation, Machine, User, VelociraptorConfig, LlmConfig
from app.services import dfir_investigation as inv_svc


# ── Helpers ────────────────────────────────────────────────────────


async def _make_pending_investigation(session_factory, seeded_env) -> tuple[str, str, str]:
    """Tạo máy + investigation ở trạng thái 'pending' (để worker claim_deepagent_dispatches
    pick up). Returns (investigation_id, expected_job_id, machine_uuid).
    """
    from app.core.security import encrypt_aes_gcm

    async with session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == seeded_env["email"]))
        ).scalar_one()

        # VelociraptorConfig + LlmConfig (cho dispatch helper không fail setup)
        await db.execute(
            VelociraptorConfig.__table__.insert().values(
                id=1,
                server_url="https://velo.test.local",
                client_config_encrypted=encrypt_aes_gcm(
                    "ca: x\nclient_cert: y\nclient_private_key: z\n"
                ),
            )
        )
        await db.execute(
            LlmConfig.__table__.insert().values(
                enabled=True,
                provider="openai",
                base_url="http://test/v1",
                api_key_encrypted=encrypt_aes_gcm("test-key"),
                model="gpt-test",
                temperature=0.0,
                request_timeout=180,
                max_tokens=8000,
                updated_by=admin.id,
            )
        )

        machine = Machine(
            org_id=admin.org_id,
            machine_uuid=f"test-mt-{id(object())}",
            hostname="MACHINE-TEST",
            status="online",
            fingerprint={"velociraptor_client_id": "C.test-mt"},
        )
        db.add(machine)
        await db.flush()

        # MachineCurrent với platform=windows để _resolve_target_platform không fail
        from app.db.models import MachineCurrent
        from datetime import UTC, datetime
        db.add(MachineCurrent(
            machine_id=machine.id,
            collected_at=datetime.now(UTC),
            platform="windows",
        ))

        inv = DfirInvestigation(
            machine_id=machine.id,
            velociraptor_client_id="C.test-mt",
            artifacts=[],
            status="pending",
            external_orchestrator="deepagent",
            hermes_status="pending",
            external_job_id=None,
            requested_by=admin.id,
        )
        db.add(inv)
        await db.commit()
        expected_job_id = f"deepagent-{inv.id}"
        return str(inv.id), expected_job_id, machine.machine_uuid


def _enable_deepagent(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")


# ── Regression tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_pending_investigations_timeout_leaves_dispatch_uncertain(
    seeded_env, session_factory, monkeypatch
):
    """BLOCKER 1 core test: HTTP timeout KHÔNG được set status=failed, dù
    exception bubble qua worker. Phải giữ `dispatch_uncertain` để reconcile loop
    retry ở tick sau.
    """
    _enable_deepagent(monkeypatch)
    inv_id, _exp_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    # Mock httpx.post raise ConnectTimeout
    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("simulated timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    # Run production worker
    await inv_svc.run_pending_investigations()

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        assert stored.hermes_status == "dispatch_uncertain", (
            f"Worker đã set {stored.hermes_status!r} thay vì 'dispatch_uncertain'. "
            "Tức là production worker overwrote trạng thái ambiguous → BLOCKER 1 chưa fix."
        )
        assert stored.status != "failed", (
            f"BLOCKER 1 BUG: worker set status=failed cho ambiguous outcome. "
            f"actual={stored.status!r}. Production sẽ stale retry / cancel job phía DeepAgent."
        )


@pytest.mark.asyncio
async def test_run_pending_investigations_502_leaves_dispatch_uncertain(
    seeded_env, session_factory, monkeypatch
):
    """HTTP 502 gateway error cũng là ambiguous — KHÔNG đưa status=failed."""
    _enable_deepagent(monkeypatch)
    inv_id, _exp_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    async def fake_post(self, url, **kwargs):
        req = httpx.Request("POST", url)
        return httpx.Response(502, text="Bad Gateway", request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await inv_svc.run_pending_investigations()

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        assert stored.hermes_status == "dispatch_uncertain"
        assert stored.status != "failed"


@pytest.mark.asyncio
async def test_run_pending_investigations_4xx_sets_failed(
    seeded_env, session_factory, monkeypatch
):
    """HTTP 401/422 (definitive) → status=failed đúng như cũ. Đây là hành vi
    mong đợi và PHẢI giữ sau fix.
    """
    _enable_deepagent(monkeypatch)
    inv_id, _exp_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    async def fake_post(self, url, **kwargs):
        req = httpx.Request("POST", url)
        return httpx.Response(401, json={"detail": "unauthorized"}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await inv_svc.run_pending_investigations()

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        assert stored.status == "failed", (
            f"Definitive failure phải set status=failed. actual={stored.status!r}"
        )
        assert stored.hermes_status == "dispatch_failed"


@pytest.mark.asyncio
async def test_next_worker_tick_uncertain_job_with_existing_becomes_dispatched(
    seeded_env, session_factory, monkeypatch
):
    """Worker tick sau: job tồn tại trên DeepAgent (GET 200) → dispatch_uncertain →
    dispatched (reconcile path). End-to-end qua worker.
    """
    _enable_deepagent(monkeypatch)
    inv_id, exp_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    # Pre-set state: đã qua 1 dispatch attempt timeout, đang ở dispatch_uncertain
    # với external_job_id đã được set (giả lập worker trước đó commit
    # dispatch_uncertain rồi).
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        stored.hermes_status = "dispatch_uncertain"
        stored.external_job_id = exp_job_id
        stored.status = "analyzing"  # worker routes via _state_check_deepagent_job
        stored.started_at = datetime.now(UTC)
        await db.commit()

    # Tick 1: GET /v1/jobs/{id} returns 200 (job tồn tại)
    async def fake_get(self, url, **kwargs):
        return httpx.Response(
            200,
            json={"job_id": exp_job_id, "status": "running"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    # Worker: inv.status="analyzing" → route tới _state_check_deepagent_job
    await inv_svc.run_pending_investigations()

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        # Sau reconcile thành công: hermes_status=dispatched, status KHÔNG phải failed
        assert stored.hermes_status == "dispatched", (
            f"Reconcile qua worker phải chuyển dispatch_uncertain → dispatched. "
            f"actual={stored.hermes_status!r}"
        )
        assert stored.status != "failed"


@pytest.mark.asyncio
async def test_next_worker_tick_uncertain_job_404_becomes_recovery(
    seeded_env, session_factory, monkeypatch, caplog
):
    """Worker tick sau: job không tồn tại trên DeepAgent (GET 404) →
    reconcile detect, set recovery_required. Worker PHẢI không set status=failed.

    Trong 1 tick, worker thực hiện 2 phase:
      Phase 1 (reconcile): GET 404 → set recovery_required → status=pending → external_job_id=None
      Phase 2 (claim_deepagent_dispatches): row đang pending → được claim và dispatch.

    Nếu dispatch attempt ở phase 2 cũng fail, row về dispatch_uncertain. Cả 2 đều
    KHÔNG phải status=failed (BLOCKER 1 invariant). Production behavior đúng.
    """
    import logging
    _enable_deepagent(monkeypatch)
    inv_id, exp_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        stored.hermes_status = "dispatch_uncertain"
        stored.external_job_id = exp_job_id
        stored.status = "analyzing"  # để worker route qua _state_check_deepagent_job
        stored.started_at = datetime.now(UTC)
        await db.commit()

    # Phase 1: GET returns 404 (job missing) → reconcile phải fire
    # Phase 2: POST timeout (network ambiguous) — Phase 2 KHÔNG nên set failed
    async def fake_get(self, url, **kwargs):
        return httpx.Response(404, json={"detail": "not found"})

    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("post timeout after 404 reconcile")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with caplog.at_level(logging.WARNING, logger="llm.dfir"):
        await inv_svc.run_pending_investigations()

    # Verify reconcile path đã fire (key invariant: row không ở status=failed)
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        # BLOCKER 1 invariant: KHÔNG được set status=failed cho ambiguous
        assert stored.status != "failed", (
            f"Worker KHÔNG được set status=failed cho 404 reconcile outcome. "
            f"actual={stored.status!r}"
        )
        # Reconcile đã chạy — warning có log "job missing"
        assert any("DeepAgent job missing" in r.message for r in caplog.records), (
            "Reconcile path phải fire — log warning 'DeepAgent job missing'. "
            f"Captured: {[r.message for r in caplog.records]}"
        )
        # Hermes_status KHÔNG được stuck ở dispatch_failed
        assert stored.hermes_status != "dispatch_failed", (
            f"Hermes status không được stuck failed sau reconcile. "
            f"actual={stored.hermes_status!r}"
        )


@pytest.mark.asyncio
async def test_run_pending_investigations_malformed_response_body_keeps_uncertain(
    seeded_env, session_factory, monkeypatch
):
    """EDGE CASE (BLOCKER 1 follow-up): response body JSON decode fail sau HTTP 2xx —
    request đã tới server, outcome không chắc chắn về persist. Phân loại thành
    ambiguous chứ không definitive (DeepAgent có thể đã tạo job trong DB nội bộ
    của nó nhưng body trả về corrupt). Bug trước fix: coi là LlmError → terminal fail.

    Acceptance: HTTP 200 + bad JSON → dispatch_uncertain (KHÔNG dispatch_failed),
    KHÔNG set status=failed ở worker. Sẽ reconcile ở tick sau: GET /v1/jobs/{id}
    cho biết job tồn tại hay không.
    """
    _enable_deepagent(monkeypatch)
    inv_id, exp_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    async def fake_post(self, url, **kwargs):
        req = httpx.Request("POST", url)
        # 200 OK nhưng body không phải JSON hợp lệ
        return httpx.Response(200, text="not json at all{garbage", request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await inv_svc.run_pending_investigations()

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        # Phải là uncertain — KHÔNG phải failed terminal
        assert stored.status != "failed", (
            f"BLOCKER 1 follow-up: HTTP 200 + malformed body → KHÔNG set status=failed. "
            f"actual={stored.status!r}. Request đã tới server, có thể đã tạo job — "
            "để reconcile loop kiểm tra."
        )
        # hermes_status phải là uncertain, KHÔNG phải dispatched (vì chưa verify job_id)
        assert stored.hermes_status == "dispatch_uncertain", (
            f"hermes_status phải uncertain (chưa verify được job_id từ response). "
            f"actual={stored.hermes_status!r}"
        )


# ── BLOCKER 1 v3 — DispatchFailed KHÔNG bị reclassify thành DispatchUncertain ─


@pytest.mark.asyncio
async def test_worker_wrong_job_id_remains_definitive_dispatch_failure(
    seeded_env, session_factory, monkeypatch
):
    """BLOCKER 1 v3: HTTP 2xx + body.job_id != expected_job_id là DEFINITIVE
    failure. Trước fix, code set status=failed rồi raise DispatchFailed
    (subclass của LlmError → Exception). Nhưng except Exception phía dưới
    check `inv.external_job_id is not None` → reclassify thành DispatchUncertain.
    → state inconsistent: status=failed + hermes_status=dispatch_uncertain
    + completed_at set. Worker catch DispatchUncertain → KHÔNG overwrite;
    investigation bị stuck ở status=failed nhưng reconcile loop vẫn tưởng
    uncertain.

    Acceptance: qua production worker run_pending_investigations, row phải
    kết thúc với status=failed + hermes_status=dispatch_failed +
    completed_at NOT NULL, KHÔNG bị flip sang dispatch_uncertain.
    """
    import httpx
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    inv_id, expected_job_id, _machine = await _make_pending_investigation(
        session_factory, seeded_env
    )

    async def fake_post(self, url, **kwargs):
        req = httpx.Request("POST", url)
        # Trả 202 + body.job_id KHÁC expected_job_id → wrong-job-id path
        return httpx.Response(
            202,
            json={"job_id": "deepagent-WRONG-uuid-XXX", "status": "accepted"},
            request=req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    # Run production worker — dispatch helper raise, worker catch
    await inv_svc.run_pending_investigations()

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, inv_id)
        # Invariant: status=failed (terminal)
        assert stored.status == "failed", (
            f"BLOCKER 1 v3 BUG: wrong job_id path nên kết thúc status=failed, "
            f"actual={stored.status!r}"
        )
        # Invariant: hermes_status=dispatch_failed (KHÔNG phải dispatch_uncertain)
        assert stored.hermes_status == "dispatch_failed", (
            f"BLOCKER 1 v3 BUG: DispatchFailed bị reclassify thành "
            f"{stored.hermes_status!r} (dispatch_uncertain) — state inconsistent. "
            f"Terminal failure phải có hermes=dispatch_failed, không phải "
            f"dispatch_uncertain (vì completed_at đã set + status=failed)."
        )
        # Invariant: completed_at set
        assert stored.completed_at is not None, (
            f"BLOCKER 1 v3 BUG: completed_at không được set trong DispatchFailed. "
            f"actual={stored.completed_at!r}"
        )
        # Invariant: error message được lưu
        assert stored.error and "job ID không khớp" in stored.error, (
            f"BLOCKER 1 v3 BUG: error message không được lưu. "
            f"actual={stored.error!r}"
        )