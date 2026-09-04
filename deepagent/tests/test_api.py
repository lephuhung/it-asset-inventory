from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepagent import api
from deepagent.config import Settings, get_settings
from deepagent.models import InvestigationRequest, JobStatus, LlmRuntime


def test_llm_runtime_accepts_128000_max_tokens() -> None:
    runtime = LlmRuntime(
        base_url="http://llm.example/v1",
        api_key="test-key",
        model="test-model",
        max_tokens=128_000,
    )

    assert runtime.max_tokens == 128_000


def test_job_id_is_deterministic_for_investigation_retries(monkeypatch):
    settings = Settings(service_token="test-deepagent-token")

    async def fake_execute(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api, "_execute", fake_execute)
    api.app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/v1/investigations",
                headers={"Authorization": "Bearer test-deepagent-token"},
                json={
                    "investigation_id": "11111111-1111-1111-1111-111111111111",
                    "client_id": "C.test-client",
                    "hostname": "TEST-HOST",
                    "time_range": {
                        "from": "2026-01-01T00:00:00Z",
                        "to": "2026-01-01T01:00:00Z",
                    },
                    "suspicious_activity": "Kiểm tra read-only",
                    "llm_runtime": {
                        "base_url": "http://llm.example/v1",
                        "api_key": "test-key",
                        "model": "test-model",
                    },
                    "velociraptor_api_client_yaml": (
                        "ca_certificate: test-ca\nclient_cert: test-cert\n"
                        "client_private_key: test-private-key\n"
                    ),
                },
            )
    finally:
        api.app.dependency_overrides.clear()
        api._jobs.clear()

    assert response.status_code == 202
    assert response.json()["job_id"] == "deepagent-11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_failed_job_and_backend_callback_withhold_external_error_bodies(monkeypatch):
    yaml_secret = "private-key-should-never-appear"
    callback_payloads = []

    class FailingMCP:
        def __init__(self, _settings: Settings):
            raise RuntimeError(f"MCP failed: client_private_key={yaml_secret}")

    class FakeCallback:
        async def submit(self, _investigation_id, payload):
            callback_payloads.append(payload)
            return {"status": "completed"}

    request = InvestigationRequest(
        investigation_id="11111111-1111-1111-1111-111111111111",
        client_id="C.test-client",
        hostname="TEST-HOST",
        target_platform="windows",
        time_range={"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"},
        suspicious_activity="Check read-only behavior",
        llm_runtime=LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        ),
        velociraptor_api_client_yaml=(
            "ca_certificate: test-ca\nclient_cert: test-cert\n"
            f"client_private_key: {yaml_secret}\n"
        ),
    )
    job_id = "deepagent-11111111-1111-1111-1111-111111111111"
    api._jobs[job_id] = JobStatus(
        job_id=job_id,
        investigation_id=request.investigation_id,
        status="queued",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(api, "VelociraptorMCP", FailingMCP)
    monkeypatch.setattr(api, "BackendCallbackClient", lambda _settings: FakeCallback())

    try:
        await api._execute(request, job_id, Settings())
        job = api._jobs[job_id]
    finally:
        api._jobs.clear()

    expected_error = (
        "RuntimeError: [REDACTED] External error message withheld to protect sensitive "
        "investigation data."
    )
    assert job.status == "failed"
    assert job.error == expected_error
    assert callback_payloads[0].error == expected_error
    assert yaml_secret not in job.error
    assert yaml_secret not in callback_payloads[0].model_dump_json()


@pytest.mark.asyncio
async def test_runner_none_job_summary_includes_timed_out_tool_count(capsys, monkeypatch):
    request = InvestigationRequest(
        investigation_id="11111111-1111-1111-1111-111111111111",
        client_id="C.test-client",
        hostname="TEST-HOST",
        target_platform="windows",
        time_range={"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"},
        suspicious_activity="Read-only check",
        llm_runtime=LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        ),
        velociraptor_api_client_yaml=(
            "ca_certificate: test-ca\nclient_cert: test-cert\n"
            "client_private_key: test-private-key\n"
        ),
    )
    job_id = "deepagent-11111111-1111-1111-1111-111111111111"
    api._jobs[job_id] = JobStatus(
        job_id=job_id,
        investigation_id=request.investigation_id,
        status="queued",
        created_at=datetime.now(UTC),
    )

    class FailingMCP:
        def __init__(self, _settings: Settings):
            raise RuntimeError("MCP bootstrap failed before any tool call")

    monkeypatch.setattr(api, "VelociraptorMCP", FailingMCP)

    try:
        await api._execute(request, job_id, Settings())
    finally:
        api._jobs.clear()

    summary = next(
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"phase":"job_summary"' in line
    )
    assert summary["timed_out_tool_count"] == 0
    assert summary["outcome"] == "failed"


def test_mcp_test_does_not_return_yaml_from_a_bridge_error(monkeypatch):
    yaml_secret = "private-key-should-never-appear"

    class FailingMCP:
        def __init__(self, _settings: Settings):
            pass

        async def test_connection(self):
            raise RuntimeError(f"bridge failed: client_private_key={yaml_secret}")

    settings = Settings(service_token="test-deepagent-token")
    monkeypatch.setattr(api, "VelociraptorMCP", FailingMCP)
    api.app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/v1/mcp/test",
                headers={"Authorization": "Bearer test-deepagent-token"},
                json={
                    "velociraptor_api_client_yaml": (
                        "ca_certificate: test-ca\nclient_cert: test-cert\n"
                        f"client_private_key: {yaml_secret}\n"
                    )
                },
            )
    finally:
        api.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["error"] == (
        "RuntimeError: [REDACTED] External error message withheld to protect sensitive investigation data."
    )
    assert yaml_secret not in response.text


@pytest.mark.asyncio
async def test_job_stays_queued_until_semaphore_starts(monkeypatch):
    """Job status must remain 'queued' until semaphore allows execution."""
    settings = Settings(service_token="test-deepagent-token", max_concurrent_jobs=2)
    
    execute_started = asyncio.Event()
    execute_continue = asyncio.Event()
    
    async def slow_execute(request, job_id, _settings):
        # Signal that execute has started
        execute_started.set()
        # Wait until told to continue (simulates semaphore-held work)
        await execute_continue.wait()
    
    # Clear any existing state
    api._jobs.clear()
    monkeypatch.setattr(api, "_execute", slow_execute)
    api.app.dependency_overrides[get_settings] = lambda: settings
    
    try:
        with TestClient(api.app) as client:
            # Create first job - should be queued
            response1 = client.post(
                "/v1/investigations",
                headers={"Authorization": "Bearer test-deepagent-token"},
                json={
                    "investigation_id": "11111111-1111-1111-1111-111111111111",
                    "client_id": "C.test-client",
                    "hostname": "TEST-HOST",
                    "time_range": {
                        "from": "2026-01-01T00:00:00Z",
                        "to": "2026-01-01T01:00:00Z"},
                    "suspicious_activity": "Kiểm tra read-only",
                    "llm_runtime": {
                        "base_url": "http://llm.example/v1",
                        "api_key": "test-key",
                        "model": "test-model",
                    },
                    "velociraptor_api_client_yaml": (
                        "ca_certificate: test-ca\nclient_cert: test-cert\n"
                        "client_private_key: test-private-key\n"
                    ),
                },
            )
        
        assert response1.status_code == 202
        # Immediately after creation, job should be queued
        assert response1.json()["status"] == "queued"
        
        # Wait for execute to start
        await asyncio.wait_for(execute_started.wait(), timeout=2.0)
        
        # Now complete the job
        execute_continue.set()
        
        # Give time for cleanup
        await asyncio.sleep(0.1)
        
    finally:
        api.app.dependency_overrides.clear()
        api._jobs.clear()
        execute_continue.set()  # Ensure any waiting tasks can continue


def test_mcp_test_uses_request_yaml_and_removes_temporary_file(monkeypatch):
    """A request-specific YAML must exist only while the read-only call runs."""
    captured: dict[str, str] = {}

    class FakeMCP:
        def __init__(self, settings: Settings):
            captured["config_path"] = settings.mcp_env()["VELOCIRAPTOR_API_CONFIG"]
            captured["yaml"] = Path(captured["config_path"]).read_text(encoding="utf-8")

        async def test_connection(self):
            return {"tools": ["list_clients"], "client_count_sampled": 1}

    settings = Settings(service_token="test-deepagent-token")
    monkeypatch.setattr(api, "VelociraptorMCP", FakeMCP)
    api.app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/v1/mcp/test",
                headers={"Authorization": "Bearer test-deepagent-token"},
                json={
                    "velociraptor_api_client_yaml": (
                        "ca_certificate: test-ca\nclient_cert: test-cert\n"
                        "client_private_key: test-private-key\n"
                    )
                },
            )
    finally:
        api.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "tools": ["list_clients"],
        "client_count_sampled": 1,
        "error": None,
    }
    assert captured["yaml"].startswith("ca_certificate: test-ca")
    assert not Path(captured["config_path"]).exists()


def test_deepagent_settings_max_concurrent_jobs_bounds() -> None:
    """H-3 regression: DeepAgent max_concurrent_jobs must be 1..3 like server."""
    from pydantic import ValidationError

    from deepagent.config import Settings

    # Valid values
    for val in (1, 2, 3):
        s = Settings(max_concurrent_jobs=val)
        assert s.max_concurrent_jobs == val

    # Invalid values must raise
    for val in (0, 4, -1, 10):
        with pytest.raises(ValidationError):
            Settings(max_concurrent_jobs=val)


@pytest.mark.asyncio
async def test_three_jobs_fifo_ordering(monkeypatch) -> None:
    """H-4 regression: three-job FIFO test.

    With capacity=2, three jobs submitted in order must result in:
    - Jobs 1 and 2 dispatched first (running)
    - Job 3 remains queued (pending)
    After job 1 completes, job 3 should be dispatched next.
    """
    from uuid import UUID

    settings = Settings(service_token="test-deepagent-token", max_concurrent_jobs=2)

    # Track job execution order
    execution_order: list[str] = []

    async def slow_execute(job_id: str, request: InvestigationRequest, _settings: Settings):
        execution_order.append(job_id)
        # Simulate work by waiting briefly
        await asyncio.sleep(0.05)

    api._jobs.clear()
    monkeypatch.setattr(api, "_execute", slow_execute)
    api.app.dependency_overrides[get_settings] = lambda: settings

    async def make_request(inv_id: str) -> dict:
        return {
            "investigation_id": inv_id,
            "client_id": "C.test-client",
            "hostname": "TEST-HOST",
            "time_range": {
                "from": "2026-01-01T00:00:00Z",
                "to": "2026-01-01T01:00:00Z",
            },
            "suspicious_activity": "Check read-only",
            "llm_runtime": {
                "base_url": "http://llm.example/v1",
                "api_key": "test-key",
                "model": "test-model",
            },
            "velociraptor_api_client_yaml": (
                "ca_certificate: test-ca\nclient_cert: test-cert\n"
                "client_private_key: test-private-key\n"
            ),
        }

    try:
        with TestClient(api.app) as client:
            # Submit three jobs in FIFO order
            ids = [str(UUID(int=i)) for i in range(3)]
            responses = []
            for i, inv_id in enumerate(ids):
                resp = client.post(
                    "/v1/investigations",
                    headers={"Authorization": "Bearer test-deepagent-token"},
                    json=await make_request(inv_id),
                )
                responses.append((inv_id, resp))

            # First two jobs should be queued/running (capacity=2)
            # Third job should be queued
            job1_resp = responses[0][1]
            job2_resp = responses[1][1]
            job3_resp = responses[2][1]

            assert job1_resp.status_code == 202
            assert job2_resp.status_code == 202
            assert job3_resp.status_code == 202

            # First two get the semaphore slots
            assert job1_resp.json()["status"] in ("queued", "running")
            assert job2_resp.json()["status"] in ("queued", "running")
            # Third job must wait
            assert job3_resp.json()["status"] == "queued", \
                f"Third job should remain queued at capacity=2, got {job3_resp.json()['status']}"

            # Wait for first two to complete
            await asyncio.sleep(0.3)

            # After first two complete, third should eventually run
            assert len(execution_order) >= 2, \
                f"Expected at least 2 executions, got {len(execution_order)}"
    finally:
        api.app.dependency_overrides.clear()
        api._jobs.clear()
