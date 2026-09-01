from __future__ import annotations

import pytest
from types import SimpleNamespace
from app.core.security import encrypt_aes_gcm
from app.db.models import VelociraptorConfig


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
        return FakeVelociraptor(), SimpleNamespace(server_url="https://veloci.example.test:8889")

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
