from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from deepagent.analysis_model import (
    AnalysisModel,
    sanitize_plan,
    validate_assessment_evidence,
)
from deepagent.config import Settings
from deepagent.mcp_client import VelociraptorMCP
from deepagent.models import Assessment, EvidenceItem, InvestigationPlan, InvestigationRequest
from deepagent.report import build_markdown_report


class InvestigationState(TypedDict, total=False):
    request: InvestigationRequest
    target_metadata: dict
    plan: InvestigationPlan
    step_index: int
    evidence: list[EvidenceItem]
    assessment: Assessment
    report_markdown: str


def build_investigation_graph(
    *, mcp: VelociraptorMCP, model: AnalysisModel, settings: Settings
):
    async def verify_target(state: InvestigationState) -> dict:
        request = state["request"]
        metadata = await mcp.verify_target(
            client_id=request.client_id,
            org_id=request.org_id or settings.velociraptor_org_id,
        )
        return {"target_metadata": metadata, "evidence": [], "step_index": 0}

    async def plan(state: InvestigationState) -> dict:
        raw_plan = await model.plan(state["request"])
        return {"plan": sanitize_plan(raw_plan, settings.max_steps)}

    async def collect_step(state: InvestigationState) -> dict:
        request = state["request"]
        index = state["step_index"]
        step = state["plan"].steps[index]
        evidence_id = f"E-{index + 1:03d}"
        try:
            payload = await mcp.collect(
                tool_name=step.tool,
                client_id=request.client_id,
                org_id=request.org_id or settings.velociraptor_org_id,
                time_from=request.time_range.from_,
                time_to=request.time_range.to,
            )
            ok = bool(payload.get("ok"))
            item = EvidenceItem(
                evidence_id=evidence_id,
                tool=step.tool,
                collected_at=datetime.now(UTC),
                ok=ok,
                data=payload.get("data") if ok else None,
                error=None if ok else str(payload.get("error") or "MCP tool failed"),
            )
        except Exception as exc:  # noqa: BLE001 - một tool lỗi không làm mất bằng chứng khác
            item = EvidenceItem(
                evidence_id=evidence_id,
                tool=step.tool,
                collected_at=datetime.now(UTC),
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        return {"evidence": [*state.get("evidence", []), item], "step_index": index + 1}

    def after_collect(state: InvestigationState) -> Literal["collect", "assess"]:
        return "collect" if state["step_index"] < len(state["plan"].steps) else "assess"

    async def assess(state: InvestigationState) -> dict:
        assessment = await model.assess(state["request"], state["evidence"])
        return {
            "assessment": validate_assessment_evidence(assessment, state["evidence"])
        }

    def render_report(state: InvestigationState) -> dict:
        return {
            "report_markdown": build_markdown_report(
                state["request"], state["assessment"], state["evidence"]
            )
        }

    builder = StateGraph(InvestigationState)
    builder.add_node("verify_target", verify_target)
    builder.add_node("plan", plan)
    builder.add_node("collect", collect_step)
    builder.add_node("assess", assess)
    builder.add_node("render_report", render_report)
    builder.add_edge(START, "verify_target")
    builder.add_edge("verify_target", "plan")
    builder.add_edge("plan", "collect")
    builder.add_conditional_edges("collect", after_collect)
    builder.add_edge("assess", "render_report")
    builder.add_edge("render_report", END)
    return builder.compile()
