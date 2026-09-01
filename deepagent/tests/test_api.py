from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from deepagent import api
from deepagent.config import Settings, get_settings


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
