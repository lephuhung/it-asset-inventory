from __future__ import annotations

import pytest

from deepagent.callback import BackendCallbackClient
from deepagent.config import Settings


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
