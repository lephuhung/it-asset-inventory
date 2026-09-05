from __future__ import annotations

import pytest

from deepagent.callback import BackendCallbackClient
from deepagent.config import Settings
from deepagent.models import CallbackPayload


@pytest.mark.asyncio
async def test_submit_status_posts_progress_to_backend(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return FakeResponse()

    monkeypatch.setattr("deepagent.callback.httpx.AsyncClient", FakeClient)
    callback = BackendCallbackClient(
        Settings(backend_url="http://api:8000", backend_api_key="callback-key")
    )

    result = await callback.submit_status(
        "inv-1",
        external_job_id="job-1",
        phase="collecting",
        progress_percent=50,
        current_step=2,
        total_steps=4,
        message="Đang thu thập bằng chứng",
    )

    assert result == {"accepted": True}
    assert captured["url"] == "http://api:8000/api/external/llm-dfir/investigations/inv-1/status"
    assert captured["headers"] == {"Authorization": "Bearer callback-key"}
    assert captured["json"] == {
        "external_job_id": "job-1",
        "phase": "collecting",
        "progress_percent": 50,
        "current_step": 2,
        "total_steps": 4,
        "message": "Đang thu thập bằng chứng",
    }


@pytest.mark.asyncio
async def test_result_callback_retries_three_times_with_same_idempotency_key(monkeypatch):
    requests = []
    statuses = iter([503, 502, 200])

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return {"accepted": True}

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json):
            requests.append((url, headers.copy(), json))
            return FakeResponse(next(statuses))

    monkeypatch.setattr("deepagent.callback.httpx.AsyncClient", FakeClient)
    callback = BackendCallbackClient(
        Settings(backend_url="http://api:8000", backend_api_key="callback-key")
    )
    payload = CallbackPayload(
        report_markdown="---\nschema_version: dfir.report/1.0\n---\n",
        severity="info",
        findings_count=0,
        findings=[],
        iocs=[],
        llm_model="test-model",
        external_job_id="job-stable-key",
    )

    result = await callback.submit("inv-1", payload)

    assert result == {"accepted": True}
    assert len(requests) == 3
    assert {item[1]["X-Idempotency-Key"] for item in requests} == {"job-stable-key"}


@pytest.mark.asyncio
async def test_result_callback_rejects_non_200_success_after_three_attempts(monkeypatch):
    attempts = 0

    class FakeResponse:
        status_code = 201

        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": True}

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json):
            nonlocal attempts
            attempts += 1
            return FakeResponse()

    monkeypatch.setattr("deepagent.callback.httpx.AsyncClient", FakeClient)
    callback = BackendCallbackClient(
        Settings(backend_url="http://api:8000", backend_api_key="callback-key")
    )
    payload = CallbackPayload(
        report_markdown="report",
        severity="info",
        findings_count=0,
        findings=[],
        iocs=[],
        llm_model="test-model",
        external_job_id="job-1",
    )

    with pytest.raises(RuntimeError, match="HTTP 201"):
        await callback.submit("inv-1", payload)

    assert attempts == 3
