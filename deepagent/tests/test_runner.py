from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from deepagent.config import Settings
from deepagent.models import Assessment, InvestigationRequest, LlmRuntime
from deepagent.runner import InvestigationRunner


@pytest.mark.asyncio
async def test_runner_emits_progress_before_final_result(monkeypatch, capsys):
    class FakeGraph:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "assessment": Assessment(
                    severity="info",
                    confidence="high",
                    executive_summary="Không phát hiện bất thường rõ ràng.",
                    conclusion="Không đủ bằng chứng để kết luận xâm nhập.",
                ),
                "report_markdown": "# Báo cáo",
                "evidence": [],
            }

    class FakeCallback:
        def __init__(self):
            self.statuses = []
            self.results = []

        async def submit_status(self, *args, **kwargs):
            self.statuses.append((args, kwargs))
            return {"accepted": True}

        async def submit(self, *args, **kwargs):
            self.results.append((args, kwargs))
            return {"status": "completed"}

    monkeypatch.setattr(
        "deepagent.runner.build_investigation_graph",
        lambda **_kwargs: FakeGraph(),
    )
    callback = FakeCallback()
    runner = InvestigationRunner(
        settings=Settings(max_steps=4),
        mcp=object(),
        model=type("FakeModel", (), {"model_name": "test-model"})(),
        callback=callback,
    )
    request = InvestigationRequest(
        investigation_id="11111111-1111-1111-1111-111111111111",
        client_id="C.test-client",
        hostname="TEST-HOST",
        time_range={
            "from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "to": datetime.now(UTC).isoformat(),
        },
        suspicious_activity="Kiểm tra read-only",
        llm_runtime=LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        ),
        velociraptor_api_client_yaml="ca_certificate: test\nclient_cert: test\nclient_private_key: test\n",
    )

    await runner.run(request, job_id="deepagent-test-job")

    assert [item[1]["phase"] for item in callback.statuses] == [
        "running",
        "finalizing",
    ]
    assert callback.statuses[0][1]["progress_percent"] == 0
    assert callback.statuses[1][1]["progress_percent"] == 90
    assert len(callback.results) == 1

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    summary = next(event for event in events if event["phase"] == "job_summary")
    assert summary["outcome"] == "succeeded"
    assert summary["investigation_id"] == "11111111-1111-1111-1111-111111111111"
    assert summary["job_id"] == "deepagent-test-job"
    assert summary["model"] == "test-model"
    assert summary["duration_ms"] >= 0
    assert summary["total_duration_ms"] >= 0
    assert summary["successful_tool_count"] == 0
    assert summary["failed_tool_count"] == 0


@pytest.mark.asyncio
async def test_runner_logs_safe_failed_job_summary(monkeypatch, capsys):
    raw_activity = "raw-evidence-should-never-appear"

    class FailingGraph:
        async def ainvoke(self, *_args, **_kwargs):
            raise RuntimeError(f"graph failed: {raw_activity}")

    class FakeCallback:
        async def submit_status(self, *_args, **_kwargs):
            return {"accepted": True}

        async def submit(self, *_args, **_kwargs):
            raise AssertionError("A failed graph must not submit a final result")

    monkeypatch.setattr(
        "deepagent.runner.build_investigation_graph",
        lambda **_kwargs: FailingGraph(),
    )
    runner = InvestigationRunner(
        settings=Settings(max_steps=4),
        mcp=object(),
        model=type("FakeModel", (), {"model_name": "test-model"})(),
        callback=FakeCallback(),
    )
    request = InvestigationRequest(
        investigation_id="11111111-1111-1111-1111-111111111111",
        client_id="C.test-client",
        hostname="TEST-HOST",
        time_range={
            "from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "to": datetime.now(UTC).isoformat(),
        },
        suspicious_activity=raw_activity,
        llm_runtime=LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        ),
        velociraptor_api_client_yaml="ca_certificate: test\nclient_cert: test\nclient_private_key: test\n",
    )

    with pytest.raises(RuntimeError, match="graph failed"):
        await runner.run(request, job_id="deepagent-test-job")

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    summary = next(event for event in events if event["phase"] == "job_summary")
    assert summary["outcome"] == "failed"
    assert summary["duration_ms"] >= 0
    assert summary["total_duration_ms"] >= 0
    assert summary["successful_tool_count"] == 0
    assert summary["failed_tool_count"] == 0
    assert summary["error_type"] == "RuntimeError"
    assert raw_activity not in json.dumps(summary)
