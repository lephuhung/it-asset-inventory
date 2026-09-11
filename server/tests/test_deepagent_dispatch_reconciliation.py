"""P1-5: DeepAgent dispatch reconciliation — phân biệt definitive vs ambiguous failure.

Bug trước fix: khi HTTP POST sang DeepAgent gặp exception (timeout, connection
reset, response lost) backend luôn ghi `status=failed`, mặc dù request có
thể đã tới DeepAgent. Kết quả: DeepAgent vẫn chạy job trong khi backend
không có cách reconcile.

Fix:
- HTTP 4xx → definitive failure → `dispatch_failed` (giữ nguyên).
- HTTP 5xx / timeout / connection error / response lost → AMBIGUOUS →
  KHÔNG set `failed`; chuyển sang `hermes_status = "dispatch_uncertain"`
  để vòng reconcile (đã có sẵn `_state_check_deepagent_job`) GET job ID:
    * job tồn tại → chuyển sang `dispatched`.
    * 404 → `recovery_required` (re-dispatch).
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.db.models import (
    DfirInvestigation,
    Machine,
    User,
    VelociraptorConfig,
)

# ── Helpers ────────────────────────────────────────────────────────


async def _seed_velociraptor_config(db, *, encrypted_client: bytes | None = None) -> None:
    """Seed VelociraptorConfig (id=1) — required by dispatch."""
    if encrypted_client is None:
        # Tạo chuỗi YAML hợp lệ cho Velociraptor api_client
        # (chỉ cần có data để giải mã thành công)
        from app.core.security import encrypt_aes_gcm

        yaml_content = (
            "ca_certificate: test\n"
            "client_cert: test\n"
            "client_private_key: test\n"
        )
        encrypted_client = encrypt_aes_gcm(yaml_content)

    cfg = VelociraptorConfig(
        id=1,
        server_url="https://velo.test.local",
        client_config_encrypted=encrypted_client,
    )
    db.add(cfg)
    await db.commit()


async def _seed_llm_config(db, admin):
    """Seed LlmConfig minimal (enabled + URL + model)."""
    from app.core.security import encrypt_aes_gcm
    from app.db.models import LlmConfig

    cfg = LlmConfig(
        enabled=True,
        provider="openai",
        base_url="http://llm.test/v1",
        api_key_encrypted=encrypt_aes_gcm("test-key"),
        model="gpt-test",
        temperature=0.0,
        request_timeout=180,
        max_tokens=8000,
        updated_by=admin.id,
    )
    db.add(cfg)
    await db.commit()


async def _make_dispatchable_investigation(
    session_factory, seeded_env, *, external_orchestrator: str = "deepagent"
):
    """Tạo investigation đang ở trạng thái chờ dispatch (status='analyzing', hermes='dispatching')."""

    from app.db.models import MachineCurrent

    async with session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == seeded_env["email"]))
        ).scalar_one()

        await _seed_velociraptor_config(db)
        await _seed_llm_config(db, admin)

        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="dispatch-test",
            hostname="DISPATCH-TEST",
            status="online",
        )
        db.add(machine)
        await db.flush()
        # MachineCurrent với platform=windows để dispatch function resolve được
        from datetime import UTC, datetime
        db.add(
            MachineCurrent(
                machine_id=machine.id,
                collected_at=datetime.now(UTC),
                platform="windows",
            )
        )
        # DfirInvestigation carries the Velociraptor client_id directly
        inv = DfirInvestigation(
            machine_id=machine.id,
            velociraptor_client_id="C.dispatch-test",
            artifacts=["Windows.Triage"],
            status="analyzing",
            external_orchestrator=external_orchestrator,
            hermes_status="dispatching",
            external_job_id=None,
            requested_by=admin.id,
        )
        db.add(inv)
        await db.commit()
        return inv.id


# ── Regression tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_4xx_is_definitive_failure(
    seeded_env, session_factory, monkeypatch
):
    """HTTP 401/403/422 từ DeepAgent → `dispatch_failed` ngay (không retry)."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    async def fake_post(self, url, **kwargs):
        return httpx.Response(401, json={"detail": "unauthorized"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.status == "failed"
        assert stored.hermes_status == "dispatch_failed"


@pytest.mark.asyncio
async def test_dispatch_timeout_marks_uncertain_not_failed(
    seeded_env, session_factory, monkeypatch
):
    """P1-5 fix: HTTP timeout KHÔNG được set status=failed — đánh dấu uncertain."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("simulated network timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        # Trước fix: status="failed". Sau fix: status KHÔNG thay đổi thành failed;
        # chuyển sang dispatch_uncertain để reconcile loop xử lý.
        assert stored.status != "failed", (
            "BUG: timeout không nên kết thúc với status=failed — DeepAgent có thể đã nhận"
        )
        assert stored.hermes_status == "dispatch_uncertain", (
            f"hermes_status phải là 'dispatch_uncertain' để reconcile, hiện: {stored.hermes_status!r}"
        )


@pytest.mark.asyncio
async def test_dispatch_connection_error_marks_uncertain(
    seeded_env, session_factory, monkeypatch
):
    """P1-5 fix: connection reset / ConnectError cũng được xếp vào nhóm ambiguous."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectError("simulated connection reset")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.status != "failed"
        assert stored.hermes_status == "dispatch_uncertain"


@pytest.mark.asyncio
async def test_dispatch_5xx_marks_uncertain_not_failed(
    seeded_env, session_factory, monkeypatch
):
    """P1-5 fix: HTTP 5xx (gateway error) cũng ambiguous — request có thể đã tới."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    async def fake_post(self, url, **kwargs):
        # response.raise_for_status() sẽ raise vì status_code=502
        req = httpx.Request("POST", url)
        return httpx.Response(502, text="Bad Gateway", request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.status != "failed"
        assert stored.hermes_status == "dispatch_uncertain"


@pytest.mark.asyncio
async def test_dispatch_validation_422_is_definitive(
    seeded_env, session_factory, monkeypatch
):
    """HTTP 422 (validation error) → definitive failure, không retry."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    async def fake_post(self, url, **kwargs):
        return httpx.Response(422, json={"detail": "invalid artifact"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.status == "failed"
        assert stored.hermes_status == "dispatch_failed"


@pytest.mark.asyncio
async def test_dispatch_reconcile_after_timeout_finds_job(
    seeded_env, session_factory, monkeypatch
):
    """Timeout → uncertain → GET job → tìm thấy → chuyển sang dispatched."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    # Step 1: dispatch với timeout
    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("simulated timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    # Step 2: reconcile bằng GET — giả lập DeepAgent job tồn tại
    async def fake_get(self, url, **kwargs):
        job_id = url.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={"job_id": job_id, "status": "running"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        await inv_svc._state_check_deepagent_job(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.hermes_status == "dispatched", (
            f"Reconcile thấy job tồn tại → phải chuyển dispatched, hiện: {stored.hermes_status!r}"
        )


@pytest.mark.asyncio
async def test_dispatch_reconcile_after_timeout_job_missing_requeues(
    seeded_env, session_factory, monkeypatch
):
    """Timeout → uncertain → GET 404 → recovery_required (re-dispatch)."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    # Step 1: dispatch với timeout
    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("simulated timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        with pytest.raises(Exception):
            await inv_svc._state_dispatch_deepagent(db, inv)

    # Step 2: GET trả 404
    async def fake_get(self, url, **kwargs):
        return httpx.Response(404, json={"detail": "not found"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        await inv_svc._state_check_deepagent_job(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.hermes_status == "recovery_required"
        assert stored.status == "pending"


@pytest.mark.asyncio
async def test_dispatch_success_path_unaffected(
    seeded_env, session_factory, monkeypatch
):
    """HTTP 2xx với job_id khớp → dispatched (happy path không thay đổi)."""
    from app.core import config as config_mod
    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(config_mod.settings, "deepagent_enabled", True)
    monkeypatch.setattr(config_mod.settings, "deepagent_url", "http://deepagent.test/")
    monkeypatch.setattr(config_mod.settings, "deepagent_api_key", "test-token")

    investigation_id = await _make_dispatchable_investigation(session_factory, seeded_env)

    async def fake_post(self, url, **kwargs):
        req = httpx.Request("POST", url)
        return httpx.Response(
            202,
            json={"job_id": f"deepagent-{investigation_id}", "status": "accepted"},
            request=req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        await inv_svc._state_dispatch_deepagent(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored.hermes_status == "dispatched"