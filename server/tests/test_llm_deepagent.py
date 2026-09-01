from __future__ import annotations

import pytest


async def _admin_headers(client, seeded_env):
    response = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_deepagent_config_is_masked_and_persisted(client, seeded_env):
    headers = await _admin_headers(client, seeded_env)

    response = await client.put(
        "/api/admin/llm-dfir/config",
        headers=headers,
        json={
            "deepagent_enabled": True,
            "deepagent_url": "http://deepagent.internal:8090/",
            "deepagent_service_token": "deepagent-service-token",
            "external_orchestrator": "deepagent",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deepagent_enabled"] is True
    assert payload["deepagent_url"] == "http://deepagent.internal:8090"
    assert payload["deepagent_service_token_set"] is True
    assert payload["external_orchestrator"] == "deepagent"
    assert "deepagent-service-token" not in response.text

    response = await client.get("/api/admin/llm-dfir/config", headers=headers)
    assert response.status_code == 200
    assert response.json()["deepagent_service_token_set"] is True


@pytest.mark.asyncio
async def test_deepagent_test_proxies_read_only_result(client, seeded_env, monkeypatch):
    headers = await _admin_headers(client, seeded_env)
    response = await client.put(
        "/api/admin/llm-dfir/config",
        headers=headers,
        json={
            "deepagent_enabled": True,
            "deepagent_url": "http://deepagent.internal:8090",
            "deepagent_service_token": "deepagent-service-token",
        },
    )
    assert response.status_code == 200

    calls: list[tuple[str, str, dict[str, str] | None]] = []

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

        async def post(self, url, *, headers):
            calls.append(("POST", url, headers))
            return FakeResponse()

    monkeypatch.setattr("app.api.routes.llm_dfir.httpx.AsyncClient", FakeAsyncClient)

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
        ("GET", "http://deepagent.internal:8090/health", None),
        (
            "POST",
            "http://deepagent.internal:8090/v1/mcp/test",
            {"Authorization": "Bearer deepagent-service-token"},
        ),
    ]
