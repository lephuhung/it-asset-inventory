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
        "collecting",
        "finalizing",
    ]
    assert callback.statuses[0][1]["progress_percent"] == 0
    assert callback.statuses[1][1]["progress_percent"] == 30  # collecting phase
    assert callback.statuses[2][1]["progress_percent"] == 90
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
    assert summary["timed_out_tool_count"] == 0


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
    assert summary["timed_out_tool_count"] == 0
    assert summary["error_type"] == "RuntimeError"
    assert raw_activity not in json.dumps(summary)


@pytest.mark.asyncio
async def test_runner_reports_event_log_triage_and_detail_progress(monkeypatch, capsys):
    """Progress callback must include collecting phase with step counts, no raw event IDs."""
    collected_statuses: list[dict] = []

    class FakeGraph:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "assessment": Assessment(
                    severity="info",
                    confidence="high",
                    executive_summary="Không phát hiện bất thường.",
                    conclusion="Không đủ bằng chứng.",
                ),
                "report_markdown": "# Báo cáo",
                "evidence": [],
            }

    class FakeCallback:
        async def submit_status(self, *_args, **kwargs):
            collected_statuses.append(dict(kwargs))
            return {"accepted": True}

        async def submit(self, *_args, **_kwargs):
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

    # Must have collecting phase before finalizing
    phases = [s["phase"] for s in collected_statuses]
    assert "collecting" in phases, f"Expected 'collecting' in phases: {phases}"

    # H-4 fix: verify current_step and total_steps are set on each status
    for status in collected_statuses:
        assert "current_step" in status, f"current_step missing in {status}"
        assert "total_steps" in status, f"total_steps missing in {status}"
        assert isinstance(status["current_step"], int), \
            f"current_step must be int, got {type(status['current_step'])}"
        assert isinstance(status["total_steps"], int), \
            f"total_steps must be int, got {type(status['total_steps'])}"

    # Collecting phase must have safe messages without raw event IDs
    for status in collected_statuses:
        if status["phase"] == "collecting":
            # Never expose raw event IDs in message
            assert "4624" not in str(status.get("message", ""))
            assert "Security" not in str(status.get("message", ""))

    # Verify phase progression: running(0) -> collecting(1) -> finalizing(8)
    running_status = next((s for s in collected_statuses if s["phase"] == "running"), None)
    collecting_status = next((s for s in collected_statuses if s["phase"] == "collecting"), None)
    finalizing_status = next((s for s in collected_statuses if s["phase"] == "finalizing"), None)
    if running_status is not None:
        assert running_status["current_step"] == 0, \
            f"running phase should have current_step=0, got {running_status['current_step']}"
    if collecting_status is not None:
        assert collecting_status["current_step"] == 1, \
            f"collecting phase should have current_step=1, got {collecting_status['current_step']}"
    if finalizing_status is not None:
        assert finalizing_status["current_step"] == finalizing_status["total_steps"], \
            f"finalizing should have current_step == total_steps, got {finalizing_status}"


@pytest.mark.asyncio
async def test_runner_job_summary_counts_timed_out_evidence_safely(monkeypatch, capsys):
    raw_evidence = "raw-evidence-should-never-appear"

    from deepagent.models import EvidenceItem

    timed_out = EvidenceItem(
        evidence_id="E-001",
        tool="windows_pslist",
        collected_at=datetime.now(UTC),
        ok=False,
        timeout=True,
        error="MCP collection timed out.",
    )
    succeeded = EvidenceItem(
        evidence_id="E-002",
        tool="windows_powershell_scriptblock",
        collected_at=datetime.now(UTC),
        ok=True,
        data={"marker": raw_evidence},
    )

    class FakeGraph:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "assessment": Assessment(
                    severity="info",
                    confidence="high",
                    executive_summary="Không phát hiện bất thường rõ ràng.",
                    conclusion="Tiếp tục theo dõi.",
                ),
                "report_markdown": "# Báo cáo",
                "evidence": [timed_out, succeeded],
            }

    class FakeCallback:
        async def submit_status(self, *_args, **_kwargs):
            return {"accepted": True}

        async def submit(self, *_args, **_kwargs):
            return {"status": "completed"}

    monkeypatch.setattr(
        "deepagent.runner.build_investigation_graph",
        lambda **_kwargs: FakeGraph(),
    )
    runner = InvestigationRunner(
        settings=Settings(max_steps=4),
        mcp=object(),
        model=type("FakeModel", (), {"model_name": "test-model"})(),
        callback=FakeCallback(),
    )
    request = InvestigationRequest(
        investigation_id="11111111-1111-4111-8111-111111111111",
        client_id="C.test-client",
        hostname="TEST-HOST",
        time_range={
            "from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "to": datetime.now(UTC).isoformat(),
        },
        suspicious_activity="Kiểm tra timeout",
        llm_runtime=LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        ),
        velociraptor_api_client_yaml="ca_certificate: test\nclient_cert: test\nclient_private_key: test\n",
    )

    await runner.run(request, job_id="deepagent-test-job")

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    summary = next(event for event in events if event["phase"] == "job_summary")
    assert summary["successful_tool_count"] == 1
    assert summary["failed_tool_count"] == 1
    assert summary["timed_out_tool_count"] == 1
    assert raw_evidence not in json.dumps(summary)
