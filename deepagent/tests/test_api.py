from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepagent import api
from deepagent.config import Settings, get_settings
from deepagent.models import InvestigationRequest, JobStatus, LlmRuntime


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
