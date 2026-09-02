from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from deepagent.analysis_model import (
    AnalysisModel,
    sanitize_plan,
    validate_assessment_evidence,
)
from deepagent.config import Settings
from deepagent.mcp_client import MCPToolTimeout, VelociraptorMCP
from deepagent.models import (
    Assessment,
    EvidenceItem,
    InvestigationPlan,
    InvestigationRequest,
)
from deepagent.observability import log_event
from deepagent.report import build_markdown_report

_TIMEOUT_ERROR = "MCP collection timed out."
_FAILED_ERROR_TEMPLATE = "MCP collection failed: {exception_type}."
_FAILED_ENVELOPE_ERROR = "MCP tool returned a failed envelope."


def _safe_collection_error(exc: BaseException) -> tuple[str, bool]:
    """Map a collection failure to a constant safe error and timeout flag.

    Never include raw exception messages: they may contain VQL, YAML, evidence
    bodies, prompts or external error bodies. The timeout flag lets the runner
    count caller-deadline failures without parsing external text.
    """
    if isinstance(exc, MCPToolTimeout):
        return _TIMEOUT_ERROR, True
    return _FAILED_ERROR_TEMPLATE.format(exception_type=type(exc).__name__), False


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
        started_at = perf_counter()
        try:
            metadata = await mcp.verify_target(
                client_id=request.client_id,
                org_id=request.org_id or settings.velociraptor_org_id,
            )
        except Exception as exc:
            log_event(
                phase="target_verification",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                error=exc,
            )
            raise
        log_event(
            phase="target_verification",
            outcome="succeeded",
            duration_ms=(perf_counter() - started_at) * 1000,
            metadata_field_count=len(metadata),
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
        timed_out = False
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
                error=None if ok else _FAILED_ENVELOPE_ERROR,
            )
        except Exception as exc:  # noqa: BLE001 - một tool lỗi không làm mất bằng chứng khác
            error_message, timed_out = _safe_collection_error(exc)
            item = EvidenceItem(
                evidence_id=evidence_id,
                tool=step.tool,
                collected_at=datetime.now(UTC),
                ok=False,
                error=error_message,
                timeout=timed_out,
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
        started_at = perf_counter()
        try:
            report_markdown = build_markdown_report(
                state["request"], state["assessment"], state["evidence"]
            )
        except Exception as exc:
            log_event(
                phase="report_rendering",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                error=exc,
            )
            raise
        log_event(
            phase="report_rendering",
            outcome="succeeded",
            duration_ms=(perf_counter() - started_at) * 1000,
            report_chars=len(report_markdown),
        )
        return {"report_markdown": report_markdown}

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
