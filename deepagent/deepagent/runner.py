from __future__ import annotations

from uuid import uuid4

from deepagent.analysis_model import AnalysisModel
from deepagent.callback import BackendCallbackClient
from deepagent.config import Settings
from deepagent.graph import build_investigation_graph
from deepagent.mcp_client import VelociraptorMCP
from deepagent.models import CallbackPayload, InvestigationRequest


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
        state = await self.graph.ainvoke(
            {"request": request},
            {"recursion_limit": self.settings.max_steps + 8},
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
        return payload
