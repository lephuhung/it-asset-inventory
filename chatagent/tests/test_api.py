"""Tests cho ChatAgent skeleton (Task 12 — spec F5/F11, agent API `/healthz`)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from chatagent.api import app
from chatagent.config import Settings

client = TestClient(app)


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_requires_service_token() -> None:
    """`POST /v1/chat` cần service token (Task 15); thiếu → 401 theo format category."""
    response = client.post("/v1/chat", json={})
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail.startswith("[chat_authz]")
    assert "[HTTP 401]" in detail


def test_settings_read_chatagent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATAGENT_SERVICE_TOKEN", "tok-from-env")
    monkeypatch.setenv("CHATAGENT_BACKEND_URL", "http://backend.internal:8000")
    assert Settings().service_token == "tok-from-env"
    assert Settings().backend_url == "http://backend.internal:8000"


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.max_tool_calls == 12
    assert settings.max_evidence_chars == 120_000
    assert settings.wall_clock_seconds == 300
    assert settings.chat_timeout_seconds == 120
    assert settings.egress_allow_cloud is False


def test_settings_do_not_read_root_env_file() -> None:
    """Spec F5: chatagent KHÔNG nạp root `.env` (chỉ `CHATAGENT_*` từ env)."""
    assert Settings.model_config.get("env_file") is None
