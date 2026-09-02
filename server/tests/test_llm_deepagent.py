from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.security import encrypt_aes_gcm
from app.db.models import (
    ApiKey,
    DfirInvestigation,
    Machine,
    Organization,
    User,
    VelociraptorConfig,
)
from app.services.dfir_investigation import claim_deepagent_dispatches


@pytest.mark.asyncio
async def test_investigation_created_at_is_evaluated_for_each_insert(db):
    """Catch a frozen ORM timestamp default shared by later investigations."""
    organization = Organization(name="Created-at test organization")
    db.add(organization)
    await db.flush()
    admin = User(
        org_id=organization.id,
        full_name="Created-at test admin",
        email="created-at-test@example.invalid",
    )
    db.add(admin)
    await db.flush()
    machine = Machine(
        org_id=organization.id,
        machine_uuid="created-at-test-machine",
        hostname="CREATED-AT-TEST",
        status="online",
    )
    db.add(machine)
    await db.flush()

    first = DfirInvestigation(
        machine_id=machine.id,
        artifacts=[],
        requested_by=admin.id,
    )
    db.add(first)
    await db.flush()
    first_created_at = first.created_at

    await asyncio.sleep(0.01)

    second = DfirInvestigation(
        machine_id=machine.id,
        artifacts=[],
        requested_by=admin.id,
    )
    db.add(second)
    await db.flush()

    assert second.created_at > first_created_at


async def _admin_headers(client, seeded_env):
    response = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_deepagent_enablement_is_persisted_without_service_credentials(client, seeded_env):
    headers = await _admin_headers(client, seeded_env)

    response = await client.put(
        "/api/admin/llm-dfir/config",
        headers=headers,
        json={
            "deepagent_enabled": True,
            "external_orchestrator": "deepagent",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deepagent_enabled"] is True
    assert payload["deepagent_service_token_set"] is False
    assert payload["external_orchestrator"] == "deepagent"
    assert "deepagent-service-token" not in response.text

    response = await client.get("/api/admin/llm-dfir/config", headers=headers)
    assert response.status_code == 200
    assert response.json()["deepagent_service_token_set"] is False


@pytest.mark.asyncio
async def test_llm_config_accepts_and_persists_128000_max_tokens(client, seeded_env):
    headers = await _admin_headers(client, seeded_env)

    response = await client.put(
        "/api/admin/llm-dfir/config",
        headers=headers,
        json={"max_tokens": 128_000},
    )

    assert response.status_code == 200
    assert response.json()["max_tokens"] == 128_000

    response = await client.get("/api/admin/llm-dfir/config", headers=headers)
    assert response.status_code == 200
    assert response.json()["max_tokens"] == 128_000


@pytest.mark.asyncio
async def test_llm_config_rejects_max_tokens_below_64000(client, seeded_env):
    headers = await _admin_headers(client, seeded_env)

    response = await client.put(
        "/api/admin/llm-dfir/config",
        headers=headers,
        json={"max_tokens": 63_999},
    )

    assert response.status_code == 422
    assert "[64000, 128000]" in response.json()["detail"]


@pytest.mark.asyncio
async def test_external_callback_persists_failure_status(
    client, seeded_env, session_factory, monkeypatch
):
    """Callback lỗi phải chuyển investigation khỏi trạng thái analyzing."""
    callback_key = "callback-test-key-32-characters-long"
    async with session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == seeded_env["email"]))
        ).scalar_one()
        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="callback-test-machine",
            hostname="CALLBACK-TEST",
            status="online",
        )
        db.add(machine)
        await db.flush()
        investigation = DfirInvestigation(
            machine_id=machine.id,
            artifacts=[],
            status="analyzing",
            external_orchestrator="deepagent",
            external_job_id="callback-test-job",
            requested_by=admin.id,
        )
        db.add(investigation)
        db.add(
            ApiKey(
                name="callback-test",
                key_hash=hashlib.sha256(callback_key.encode()).hexdigest(),
                scope="investigation:write",
                created_by=admin.id,
            )
        )
        await db.commit()
        investigation_id = investigation.id

    async def no_notification(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.dfir_investigation._notify_investigation_result",
        no_notification,
    )
    response = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "callback-test-job",
        },
        json={
            "report_markdown": "# Điều tra thất bại",
            "error": "LLM planner failed",
            "external_job_id": "callback-test-job",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.error == "External (deepagent): LLM planner failed"


async def _create_callback_investigation(
    session_factory,
    seeded_env,
    *,
    external_job_id="deepagent-test-job",
    external_orchestrator="deepagent",
):
    callback_key = "callback-test-key-32-characters-long"
    async with session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == seeded_env["email"]))
        ).scalar_one()
        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="callback-test-machine",
            hostname="CALLBACK-TEST",
            status="online",
        )
        db.add(machine)
        await db.flush()
        investigation = DfirInvestigation(
            machine_id=machine.id,
            artifacts=[],
            status="analyzing",
            external_orchestrator=external_orchestrator,
            external_job_id=external_job_id,
            requested_by=admin.id,
        )
        db.add(investigation)
        db.add(
            ApiKey(
                name="callback-test",
                key_hash=hashlib.sha256(callback_key.encode()).hexdigest(),
                scope="investigation:write",
                created_by=admin.id,
            )
        )
        await db.commit()
        return investigation.id, callback_key


@pytest.mark.asyncio
async def test_deepagent_callback_requires_bound_job_id(
    client, seeded_env, session_factory, monkeypatch
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        assert inv is not None
        inv.external_job_id = None
        await db.commit()
    async def no_notification(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.dfir_investigation._notify_investigation_result",
        no_notification,
    )
    response = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "unbound-job-callback",
        },
        json={"report_markdown": "# unbound"},
    )

    status = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/status",
        headers={"Authorization": f"Bearer {callback_key}"},
        json={
            "external_job_id": "stale-job",
            "phase": "running",
            "progress_percent": 0,
        },
    )

    assert response.status_code == 409
    assert status.status_code == 409


@pytest.mark.asyncio
async def test_deepagent_dispatch_timeout_without_job_is_requeued(
    seeded_env, session_factory
):
    investigation_id, _ = await _create_callback_investigation(
        session_factory, seeded_env
    )
    from app.services import dfir_investigation as inv_svc

    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        assert inv is not None
        inv.external_job_id = None
        inv.hermes_status = "dispatching"
        inv.started_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()
        await inv_svc._process_one(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.status == "pending"
        assert stored.hermes_status == "recovery_required"


@pytest.mark.asyncio
async def test_external_status_ignores_regressing_progress(
    client, seeded_env, session_factory
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    headers = {"Authorization": f"Bearer {callback_key}"}
    first = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/status",
        headers=headers,
        json={
            "external_job_id": "deepagent-test-job",
            "phase": "collecting",
            "progress_percent": 60,
        },
    )
    second = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/status",
        headers=headers,
        json={
            "external_job_id": "deepagent-test-job",
            "phase": "running",
            "progress_percent": 40,
        },
    )
    cross_phase = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/status",
        headers=headers,
        json={
            "external_job_id": "deepagent-test-job",
            "phase": "finalizing",
            "progress_percent": 0,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert cross_phase.status_code == 200
    assert cross_phase.json()["accepted"] is False
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.hermes_status == "collecting"
        assert stored.hermes_response["progress_percent"] == 60


@pytest.mark.asyncio
async def test_missing_deepagent_job_is_requeued_after_restart(
    seeded_env, session_factory, monkeypatch
):
    investigation_id, _ = await _create_callback_investigation(
        session_factory, seeded_env
    )

    class FakeResponse:
        status_code = 404

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return FakeResponse()

    from app.services import dfir_investigation as inv_svc

    monkeypatch.setattr(inv_svc.httpx, "AsyncClient", FakeClient)
    async with session_factory() as db:
        inv = await db.get(DfirInvestigation, investigation_id)
        assert inv is not None
        await inv_svc._process_one(db, inv)

    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.status == "pending"
        assert stored.external_job_id is None
        assert stored.hermes_status == "recovery_required"


@pytest.mark.asyncio
async def test_external_pending_poll_claims_each_investigation_once(
    client, seeded_env, session_factory
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env, external_orchestrator="hermes"
    )
    headers = {"Authorization": f"Bearer {callback_key}"}
    first = await client.get(
        "/api/external/llm-dfir/investigations/pending", headers=headers
    )
    second = await client.get(
        "/api/external/llm-dfir/investigations/pending", headers=headers
    )

    assert first.status_code == 200
    assert str(investigation_id) in {item["id"] for item in first.json()}
    assert second.status_code == 200
    assert second.json() == []


@pytest.mark.asyncio
async def test_external_callback_rejects_invalid_investigation_id(
    client, seeded_env, session_factory
):
    _, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    response = await client.post(
        "/api/external/llm-dfir/investigations/not-a-uuid/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "invalid-id-callback",
        },
        json={"report_markdown": "# invalid"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_external_callback_returns_404_for_unknown_investigation(
    client, seeded_env, session_factory
):
    _, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    response = await client.post(
        f"/api/external/llm-dfir/investigations/{uuid4()}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "unknown-id-callback",
        },
        json={"report_markdown": "# unknown"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_external_callback_rejects_wrong_external_job(
    client, seeded_env, session_factory, monkeypatch
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    async def no_notification(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.dfir_investigation._notify_investigation_result",
        no_notification,
    )
    response = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "wrong-job-callback",
        },
        json={
            "report_markdown": "# stale",
            "external_job_id": "different-job",
        },
    )

    assert response.status_code == 409
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.status == "analyzing"
        assert stored.callback_received_at is None


@pytest.mark.asyncio
async def test_external_status_rejects_wrong_external_job(
    client, seeded_env, session_factory
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    response = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/status",
        headers={"Authorization": f"Bearer {callback_key}"},
        json={
            "external_job_id": "different-job",
            "phase": "running",
            "progress_percent": 50,
        },
    )

    assert response.status_code == 409
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.external_job_id == "deepagent-test-job"
        assert stored.hermes_status is None


@pytest.mark.asyncio
async def test_external_status_rejects_wrong_job_for_terminal_investigation(
    client, seeded_env, session_factory, monkeypatch
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    async def no_notification(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.dfir_investigation._notify_investigation_result",
        no_notification,
    )
    result = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "terminal-result",
        },
        json={"report_markdown": "# done", "external_job_id": "deepagent-test-job"},
    )
    status = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/status",
        headers={"Authorization": f"Bearer {callback_key}"},
        json={
            "external_job_id": "different-job",
            "phase": "running",
            "progress_percent": 50,
        },
    )

    assert result.status_code == 200
    assert status.status_code == 409


@pytest.mark.asyncio
async def test_external_failure_callback_allows_missing_report_but_requires_idempotency(
    client, seeded_env, session_factory, monkeypatch
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    async def no_notification(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.dfir_investigation._notify_investigation_result",
        no_notification,
    )
    base = {"error": "planner failed", "external_job_id": "deepagent-test-job"}
    missing_key = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={"Authorization": f"Bearer {callback_key}"},
        json={**base, "report_markdown": "# failure"},
    )
    missing_report = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "failure-callback-1",
        },
        json=base,
    )

    assert missing_key.status_code == 400
    assert missing_report.status_code == 200
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.external_callback_idempotency_key == "failure-callback-1"


@pytest.mark.asyncio
async def test_external_callback_rejects_different_idempotency_key(
    client, seeded_env, session_factory, monkeypatch
):
    investigation_id, callback_key = await _create_callback_investigation(
        session_factory, seeded_env
    )
    notifications = []

    async def record_notification(*args, **kwargs):
        notifications.append((args, kwargs))

    monkeypatch.setattr(
        "app.services.dfir_investigation._notify_investigation_result",
        record_notification,
    )
    payload = {
        "report_markdown": "# first report",
        "severity": "low",
        "findings_count": 0,
        "findings": [],
        "iocs": [],
        "llm_model": "test-model",
        "external_job_id": "deepagent-test-job",
        "input_tokens": 10,
        "output_tokens": 20,
    }
    first = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "callback-result-1",
        },
        json=payload,
    )
    replay = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "callback-result-1",
        },
        json={**payload, "external_job_id": None, "report_markdown": "# replay"},
    )
    second = await client.post(
        f"/api/external/llm-dfir/investigations/{investigation_id}/result",
        headers={
            "Authorization": f"Bearer {callback_key}",
            "X-Idempotency-Key": "callback-result-2",
        },
        json={**payload, "report_markdown": "# overwritten"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert second.status_code == 409
    assert len(notifications) == 1
    async with session_factory() as db:
        stored = await db.get(DfirInvestigation, investigation_id)
        assert stored is not None
        assert stored.status == "completed"
        assert stored.report_markdown == "# first report"
        assert stored.input_tokens == 10
        assert stored.output_tokens == 20
        assert stored.external_callback_idempotency_key == "callback-result-1"


@pytest.mark.asyncio
async def test_deepagent_test_sends_saved_velociraptor_yaml(
    client, seeded_env, session_factory, monkeypatch
):
    headers = await _admin_headers(client, seeded_env)
    yaml_content = (
        "ca_certificate: test-ca\nclient_cert: test-cert\n"
        "client_private_key: test-private-key\n"
    )
    async with session_factory() as db:
        db.add(
            VelociraptorConfig(
                id=1,
                enabled=True,
                client_config_encrypted=encrypt_aes_gcm(yaml_content),
            )
        )
        await db.commit()
    response = await client.put(
        "/api/admin/llm-dfir/config",
        headers=headers,
        json={
            "deepagent_enabled": True,
        },
    )
    assert response.status_code == 200

    calls: list[tuple[str, str, dict | None]] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "tools": ["get_client", "list_clients"],
                "client_count_sampled": 1,
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            calls.append(("GET", url, None))
            return FakeResponse()

        async def post(self, url, *, headers, json):
            calls.append(("POST", url, {"headers": headers, "json": json}))
            return FakeResponse()

    monkeypatch.setattr("app.api.routes.llm_dfir.httpx.AsyncClient", FakeAsyncClient)
    from app.core.config import settings

    monkeypatch.setattr(settings, "deepagent_url", "http://deepagent:8090")
    monkeypatch.setattr(settings, "deepagent_api_key", "compose-service-token")

    response = await client.post("/api/admin/llm-dfir/deepagent/test", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service_ok": True,
        "mcp_ok": True,
        "tools": ["get_client", "list_clients"],
        "client_count_sampled": 1,
        "error": None,
    }
    assert calls == [
        ("GET", "http://deepagent:8090/health", None),
        (
            "POST",
            "http://deepagent:8090/v1/mcp/test",
            {
                "headers": {"Authorization": "Bearer compose-service-token"},
                "json": {"velociraptor_api_client_yaml": yaml_content},
            },
        ),
    ]


@pytest.mark.asyncio
async def test_velociraptor_test_runs_mcp_check_after_success(
    client, seeded_env, session_factory, monkeypatch
):
    """MCP chỉ được kiểm sau khi test gRPC Velociraptor thành công."""
    headers = await _admin_headers(client, seeded_env)
    yaml_content = "ca_certificate: test-ca\nclient_cert: test-cert\nclient_private_key: test-key\n"
    async with session_factory() as db:
        db.add(VelociraptorConfig(
            id=1,
            enabled=True,
            server_url="https://veloci.example.test:8889",
            client_config_encrypted=encrypt_aes_gcm(yaml_content),
        ))
        await db.commit()

    class FakeVelociraptor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def test_connection(self):
            return {"ok": True, "client_count_sampled": 2}

    async def fake_build(_db):
        return FakeVelociraptor(), SimpleNamespace(
            server_url="https://veloci.example.test:8889",
            client_config_encrypted=encrypt_aes_gcm(yaml_content),
        )

    async def fake_mcp(_yaml):
        return {"ok": True, "service_ok": True, "mcp_ok": True, "tools": ["list_clients"], "client_count_sampled": 2, "error": None}

    monkeypatch.setattr("app.api.routes.velociraptor._build_velociraptor_client", fake_build)
    monkeypatch.setattr("app.api.routes.velociraptor.test_deepagent_mcp_for_yaml", fake_mcp, raising=False)

    response = await client.post("/api/admin/velociraptor/test", headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["mcp"] == {
        "ok": True,
        "service_ok": True,
        "mcp_ok": True,
        "tools": ["list_clients"],
        "client_count_sampled": 2,
        "error": None,
    }


@pytest.mark.asyncio
async def test_llm_models_endpoint_loads_models_from_saved_config(client, seeded_env, monkeypatch):
    headers = await _admin_headers(client, seeded_env)

    async def fake_list_models(self):
        return ["qwen3:8b", "qwen3:14b"]

    monkeypatch.setattr("app.api.routes.llm_dfir.LlmClient.list_models", fake_list_models)

    response = await client.post("/api/admin/llm-dfir/config/models", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"models": ["qwen3:8b", "qwen3:14b"]}


# ── DeepAgent capacity queue tests ─────────────────────────────────────


async def _seed_deepagent_investigation(
    db,
    *,
    machine,
    requested_by,
    status="pending",
    external_orchestrator="deepagent",
    external_job_id=None,
):
    """Helper: tạo một DfirInvestigation dùng DeepAgent orchestrator."""
    inv = DfirInvestigation(
        machine_id=machine.id,
        velociraptor_client_id="test-client-id",
        artifacts=[],
        status=status,
        external_orchestrator=external_orchestrator,
        external_job_id=external_job_id,
        requested_by=requested_by,
    )
    db.add(inv)
    await db.flush()
    return inv


async def _seed_deepagent_investigations(
    db, machine, requested_by, count=3
):
    """Helper: tạo N DfirInvestigation dùng DeepAgent orchestrator."""
    return [
        await _seed_deepagent_investigation(db, machine=machine, requested_by=requested_by)
        for _ in range(count)
    ]


@pytest.mark.asyncio
async def test_deepagent_dispatch_claims_oldest_pending_rows_up_to_capacity(
    session_factory, seeded_env
):
    """claim_deepagent_dispatches chọn đúng N rows pending cũ nhất theo FIFO."""
    async with session_factory() as db:
        admin = (
            await db.execute(
                select(User).where(User.email == seeded_env["email"])
            )
        ).scalar_one()
        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="capacity-test-machine",
            hostname="CAPACITY-TEST",
            status="online",
        )
        db.add(machine)
        await db.flush()

        first, second, third = await _seed_deepagent_investigations(
            db, machine=machine, requested_by=admin.id, count=3
        )
        await db.commit()

        claimed = await claim_deepagent_dispatches(db, capacity=2)
        assert [row.id for row in claimed] == [first.id, second.id]
        await db.refresh(third)
        assert third.status == "pending"


@pytest.mark.asyncio
async def test_deepagent_dispatch_claim_respects_existing_active_slots(
    session_factory, seeded_env
):
    """Active (analyzing) rows chiếm slot; chỉ dispatch đủ capacity còn trống."""
    async with session_factory() as db:
        admin = (
            await db.execute(
                select(User).where(User.email == seeded_env["email"])
            )
        ).scalar_one()
        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="active-slot-machine",
            hostname="ACTIVE-SLOT",
            status="online",
        )
        db.add(machine)
        await db.flush()

        # 1 active analyzing
        active = await _seed_deepagent_investigation(
            db,
            machine=machine,
            requested_by=admin.id,
            status="analyzing",
            external_job_id="deepagent-active-job",
        )
        # 2 pending
        queued = await _seed_deepagent_investigations(
            db, machine=machine, requested_by=admin.id, count=2
        )
        await db.commit()

        claimed = await claim_deepagent_dispatches(db, capacity=2)
        # capacity=2, active=1 → còn 1 slot → chỉ claimed 1
        assert [row.id for row in claimed] == [queued[0].id]
        await db.refresh(active)
        assert active.status == "analyzing"


@pytest.mark.asyncio
async def test_deepagent_max_concurrent_jobs_setting_validation():
    """Settings deepagent_max_concurrent_jobs phải nằm trong khoảng 1..3."""
    from app.core.config import Settings

    # Giá trị hợp lệ
    for val in (1, 2, 3):
        s = Settings(deepagent_max_concurrent_jobs=val)
        assert s.deepagent_max_concurrent_jobs == val

    # Giá trị không hợp lệ
    for val in (0, 4, -1, 10):
        with pytest.raises(ValidationError):
            Settings(deepagent_max_concurrent_jobs=val)


@pytest.mark.asyncio
async def test_deepagent_dispatch_claim_returns_empty_when_capacity_zero(
    session_factory, seeded_env
):
    """capacity=0 không dispatch gì cả."""
    async with session_factory() as db:
        admin = (
            await db.execute(
                select(User).where(User.email == seeded_env["email"])
            )
        ).scalar_one()
        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="zero-capacity-machine",
            hostname="ZERO-CAPACITY",
            status="online",
        )
        db.add(machine)
        await db.flush()

        await _seed_deepagent_investigations(
            db, machine=machine, requested_by=admin.id, count=3
        )
        await db.commit()

        claimed = await claim_deepagent_dispatches(db, capacity=0)
        assert claimed == []


@pytest.mark.asyncio
async def test_deepagent_dispatch_claim_skips_non_deepagent_rows(
    session_factory, seeded_env
):
    """Chỉ chọn rows có external_orchestrator=deepagent."""
    async with session_factory() as db:
        admin = (
            await db.execute(
                select(User).where(User.email == seeded_env["email"])
            )
        ).scalar_one()
        machine = Machine(
            org_id=admin.org_id,
            machine_uuid="non-deepagent-machine",
            hostname="NON-DEEPAGENT",
            status="online",
        )
        db.add(machine)
        await db.flush()

        # hermes orchestrator — không được claim
        hermes_inv = DfirInvestigation(
            machine_id=machine.id,
            velociraptor_client_id="test-client",
            artifacts=[],
            status="pending",
            external_orchestrator="hermes",
            requested_by=admin.id,
        )
        db.add(hermes_inv)
        await db.flush()

        # deepagent orchestrator — được claim
        deepagent_inv = await _seed_deepagent_investigation(
            db, machine=machine, requested_by=admin.id
        )
        await db.commit()

        claimed = await claim_deepagent_dispatches(db, capacity=2)
        assert len(claimed) == 1
        assert claimed[0].id == deepagent_inv.id


@pytest.mark.asyncio
async def test_run_pending_investigations_respects_capacity_for_deepagent(
    session_factory, seeded_env, monkeypatch
):
    """run_pending_investigations must not dispatch more than capacity DeepAgent jobs.

    Regression test for B-2: the claim helper was dead code in production;
    run_pending_investigations still iterated over .limit(5) regardless of capacity.
    """
    state_dispatch_calls: list[str] = []

    # Patch _state_dispatch_deepagent to track calls without actually HTTP-posting
    from app.services import dfir_investigation as inv_svc

    original_state_dispatch = inv_svc._state_dispatch_deepagent

    async def tracking_dispatch(db, inv):
        state_dispatch_calls.append(str(inv.id))
        # Don't actually HTTP POST — we're testing the claim loop, not dispatch

    inv_svc._state_dispatch_deepagent = tracking_dispatch

    original_is_llm_enabled = inv_svc._is_llm_enabled

    async def fake_is_llm_enabled(_db):
        return True

    inv_svc._is_llm_enabled = fake_is_llm_enabled

    try:
        async with session_factory() as db:
            admin = (
                await db.execute(select(User).where(User.email == seeded_env["email"]))
            ).scalar_one()
            machine = Machine(
                org_id=admin.org_id,
                machine_uuid="three-job-machine",
                hostname="THREE-JOB",
                status="online",
            )
            db.add(machine)
            await db.flush()
            # Create 3 deepagent pending investigations (FIFO order by created_at)
            inv_ids = []
            for i in range(3):
                inv = DfirInvestigation(
                    machine_id=machine.id,
                    velociraptor_client_id="test-client-id",
                    artifacts=[],
                    status="pending",
                    external_orchestrator="deepagent",
                    requested_by=admin.id,
                )
                db.add(inv)
                await db.flush()
                inv_ids.append(inv.id)
            await db.commit()

        # Simulate capacity=2 via monkeypatching the settings
        from app.core import config as config_mod

        original_capacity = config_mod.settings.deepagent_max_concurrent_jobs
        config_mod.settings.deepagent_max_concurrent_jobs = 2

        try:
            result = await inv_svc.run_pending_investigations()
        finally:
            config_mod.settings.deepagent_max_concurrent_jobs = original_capacity
    finally:
        inv_svc._state_dispatch_deepagent = original_state_dispatch
        inv_svc._is_llm_enabled = original_is_llm_enabled

    # At capacity=2, at most 2 jobs should be dispatched
    assert len(state_dispatch_calls) <= 2, (
        f"Expected at most 2 dispatches at capacity=2, got {len(state_dispatch_calls)}: {state_dispatch_calls}"
    )

    # The dispatched jobs must be the oldest ones (FIFO)
    if len(state_dispatch_calls) >= 1:
        assert state_dispatch_calls[0] == str(inv_ids[0]), \
            f"First dispatch should be oldest (id={inv_ids[0]}), got {state_dispatch_calls[0]}"
    if len(state_dispatch_calls) == 2:
        assert state_dispatch_calls[1] == str(inv_ids[1]), \
            f"Second dispatch should be second-oldest (id={inv_ids[1]}), got {state_dispatch_calls[1]}"
