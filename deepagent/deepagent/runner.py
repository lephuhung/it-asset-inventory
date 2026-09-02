from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from deepagent.analysis_model import AnalysisModel
from deepagent.callback import BackendCallbackClient
from deepagent.config import Settings
from deepagent.graph import build_investigation_graph
from deepagent.mcp_client import VelociraptorMCP
from deepagent.models import CallbackPayload, InvestigationRequest
from deepagent.observability import investigation_context, log_event


class InvestigationRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        mcp: VelociraptorMCP,
        model: AnalysisModel,
        callback: BackendCallbackClient,
    ):
        self.settings = settings
        self.model = model
        self.callback = callback
        self.graph = build_investigation_graph(mcp=mcp, model=model, settings=settings)

    async def run(self, request: InvestigationRequest, job_id: str | None = None) -> CallbackPayload:
        external_job_id = job_id or f"deepagent-{uuid4()}"
        started_at = perf_counter()
        sensitive_values = (
            request.llm_runtime.api_key,
            request.velociraptor_api_client_yaml,
            request.suspicious_activity,
            request.llm_runtime.system_prompt or "",
        )
        with investigation_context(
            investigation_id=str(request.investigation_id),
            job_id=external_job_id,
            sensitive_values=sensitive_values,
        ):
            try:
                # H-4 fix: set current_step and total_steps from phase/progress_percent
                total_steps = self.settings.max_steps + 2  # +2 for event-log detail steps
                await self._status(
                    request,
                    external_job_id=external_job_id,
                    phase="running",
                    progress_percent=0,
                    current_step=0,
                    total_steps=total_steps,
                    message="DeepAgent bắt đầu điều tra read-only",
                )
                # Emit collecting phase before triage/detail phases.
                # Step counts are safe; never include raw event IDs, filters, or prompts.
                await self._status(
                    request,
                    external_job_id=external_job_id,
                    phase="collecting",
                    progress_percent=30,
                    current_step=1,
                    total_steps=total_steps,
                    message="Đang thu thập dữ liệu từ endpoint...",
                )
                state = await self.graph.ainvoke(
                    {"request": request},
                    {"recursion_limit": self.settings.max_steps + 8},
                )
                await self._status(
                    request,
                    external_job_id=external_job_id,
                    phase="finalizing",
                    progress_percent=90,
                    current_step=total_steps,
                    total_steps=total_steps,
                    message="Đã thu thập xong, đang tổng hợp báo cáo",
                )
                assessment = state["assessment"]
                payload = CallbackPayload(
                    report_markdown=state["report_markdown"],
                    severity=assessment.severity,
                    findings_count=len(assessment.findings),
                    findings=[item.model_dump(mode="json") for item in assessment.findings],
                    iocs=[item.model_dump(mode="json") for item in assessment.iocs],
                    llm_model=self.model.model_name,
                    external_job_id=external_job_id,
                    raw_response={
                        "workflow": "bounded-langgraph-v1",
                        "tools": [item.tool for item in state["evidence"]],
                        "evidence_status": [
                            {"evidence_id": item.evidence_id, "ok": item.ok}
                            for item in state["evidence"]
                        ],
                    },
                )
                await self.callback.submit(str(request.investigation_id), payload)
            except Exception as exc:
                evidence = locals().get("state", {}).get("evidence", [])
                log_event(
                    phase="job_summary",
                    outcome="failed",
                    duration_ms=(perf_counter() - started_at) * 1000,
                    model=self.model.model_name,
                    successful_tool_count=sum(item.ok for item in evidence),
                    failed_tool_count=sum(not item.ok for item in evidence),
                    timed_out_tool_count=sum(
                        bool(getattr(item, "timeout", False)) for item in evidence
                    ),
                    total_duration_ms=int((perf_counter() - started_at) * 1000),
                    error=exc,
                )
                raise
            evidence = state["evidence"]
            log_event(
                phase="job_summary",
                outcome="succeeded",
                duration_ms=(perf_counter() - started_at) * 1000,
                model=self.model.model_name,
                successful_tool_count=sum(item.ok for item in evidence),
                failed_tool_count=sum(not item.ok for item in evidence),
                timed_out_tool_count=sum(
                    bool(getattr(item, "timeout", False)) for item in evidence
                ),
                total_duration_ms=int((perf_counter() - started_at) * 1000),
            )
            return payload

    async def _status(
        self,
        request: InvestigationRequest,
        *,
        external_job_id: str,
        phase: str,
        progress_percent: int,
        current_step: int | None = None,
        total_steps: int | None = None,
        message: str,
    ) -> None:
        try:
            await self.callback.submit_status(
                str(request.investigation_id),
                external_job_id=external_job_id,
                phase=phase,
                progress_percent=progress_percent,
                current_step=current_step,
                total_steps=total_steps,
                message=message,
            )
        except Exception:  # noqa: BLE001 - progress không làm fail investigation
            # submit_status already emits a bounded structured failure event.
            return
