from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from deepagent.analysis_model import (
    AnalysisModel,
    sanitize_plan,
    validate_assessment_evidence,
)
from deepagent.catalog import custom_tool_names
from deepagent.config import Settings
from deepagent.mcp_client import MCPToolTimeout, VelociraptorMCP
from deepagent.models import (
    MAX_DETAIL_CALLS,
    Assessment,
    EventLogExpansion,
    EvidenceItem,
    InvestigationPlan,
    InvestigationRequest,
    fit_evidence_budget,
    validate_event_log_expansions,
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
    # M-3 fix: safe limitations from expansion validation (never raw LLM text)
    limitations: list[str]


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
        return {
            "plan": sanitize_plan(
                raw_plan, settings.max_steps, custom_tool_names(state["request"])
            )
        }

    async def collect_step(state: InvestigationState) -> dict:
        request = state["request"]
        index = state["step_index"]
        step = state["plan"].steps[index]
        evidence_id = f"E-{index + 1:03d}"
        evidence = state.get("evidence", [])

        # Two-stage collection for windows_event_logs
        if step.tool == "windows_event_logs" and hasattr(mcp, "collect_event_log_triage"):
            result = await _collect_event_log_with_expansion(
                mcp=mcp,
                model=model,
                request=request,
                evidence_id=evidence_id,
                evidence=evidence,
                index=index,
                settings=settings,
            )
            # M-3 fix: merge validation rejection labels as safe limitations
            new_limitations = result.get("limitations", [])
            existing_limitations = state.get("limitations", [])
            return {
                **{k: v for k, v in result.items() if k != "limitations"},
                "limitations": [*existing_limitations, *new_limitations],
            }

        # Generic collection for other tools
        timed_out = False
        try:
            payload = await mcp.collect(
                tool_name=step.tool,
                client_id=request.client_id,
                org_id=request.org_id or settings.velociraptor_org_id,
                time_from=request.time_range.from_,
                time_to=request.time_range.to,
                custom_names=custom_tool_names(request),
            )
            ok = bool(payload.get("ok"))
            item = EvidenceItem(
                evidence_id=evidence_id,
                tool=step.tool,
                collected_at=datetime.now(UTC),
                ok=ok,
                data=payload.get("data") if ok else None,
                pagination=payload.get("pagination") if ok else None,
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
        return {"evidence": [*evidence, item], "step_index": index + 1}

    def after_collect(state: InvestigationState) -> Literal["collect", "assess"]:
        return "collect" if state["step_index"] < len(state["plan"].steps) else "assess"

    async def assess(state: InvestigationState) -> dict:
        # Enforce evidence budget before assessment
        bounded_evidence = fit_evidence_budget(
            state["evidence"],
            settings.max_evidence_chars,
        )
        assessment = await model.assess(state["request"], bounded_evidence)
        # M-3 fix: append safe validation rejection labels to assessment limitations
        validated = validate_assessment_evidence(assessment, bounded_evidence)
        graph_limitations = state.get("limitations", [])
        if graph_limitations:
            validated.limitations = [*(validated.limitations or []), *graph_limitations]
        return {"assessment": validated}

    def render_report(state: InvestigationState) -> dict:
        started_at = perf_counter()
        try:
            # H-1 fix: apply evidence budget before report rendering
            bounded_evidence = fit_evidence_budget(
                state["evidence"],
                settings.max_evidence_chars,
            )
            report_markdown = build_markdown_report(
                state["request"], state["assessment"], bounded_evidence
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


async def _collect_event_log_with_expansion(
    mcp: VelociraptorMCP,
    model: AnalysisModel,
    request: InvestigationRequest,
    evidence_id: str,
    evidence: list[EvidenceItem],
    index: int,
    settings: Settings,
) -> dict:
    """Two-stage event log collection: triage first, then bounded detail expansion.

    Stage 1: Collect triage metadata (hard cap 100 rows)
    Stage 2: Ask model for expansion plan using sampled Event IDs
    Stage 3: Validate and execute at most 2 detail calls

    Timeouts and ordinary failures continue to assessment.
    """
    # Stage 1: Triage collection
    triage_evidence_id = evidence_id
    triage_timed_out = False
    triage_result: dict[str, Any] = {}
    # M-3 fix: initialize validation_rejections for the return value
    validation_rejections: list[str] = []

    try:
        triage_result = await mcp.collect_event_log_triage(
            client_id=request.client_id,
            org_id=request.org_id or settings.velociraptor_org_id,
            time_from=request.time_range.from_,
            time_to=request.time_range.to,
        )
    except Exception as exc:  # noqa: BLE001 - triage failure doesn't block graph
        error_message, triage_timed_out = _safe_collection_error(exc)
        triage_item = EvidenceItem(
            evidence_id=triage_evidence_id,
            tool="windows_event_logs",
            collected_at=datetime.now(UTC),
            ok=False,
            error=error_message,
            timeout=triage_timed_out,
        )
        evidence = [*evidence, triage_item]
        # M-3: no rejections yet (triage failed before validation)
        return {"evidence": evidence, "step_index": index + 1, "limitations": []}

    # Create triage evidence item
    triage_item = EvidenceItem(
        evidence_id=triage_evidence_id,
        tool="windows_event_logs",
        collected_at=datetime.now(UTC),
        ok=True,
        data=triage_result,
    )
    evidence = [*evidence, triage_item]

    # Extract sampled Event IDs from triage result (B-3 fix: use actual EventIDs, not hardcoded fallback)
    sampled_event_ids: set[str] = set()
    if isinstance(triage_result, dict) and "event_ids" in triage_result:
        # B-3 fix: adapter now includes actual EventIDs from triage rows in envelope
        eids = triage_result["event_ids"]
        if isinstance(eids, list):
            sampled_event_ids = {str(eid) for eid in eids if eid}
    # If no event_ids in envelope, use empty set (no expansion possible)
    # — do NOT fall back to hardcoded IDs

    # Stage 2: Ask model for expansion plan
    expansion_items: list[EventLogExpansion] = []
    if hasattr(model, "plan_event_log_expansion") and sampled_event_ids:
        try:
            raw_expansions = await model.plan_event_log_expansion(
                request=request,
                sampled_event_ids=sampled_event_ids,
                triage_result=triage_result,
            )
            # Validate expansions (M-3 fix: collect rejection labels as safe limitations)
            expansion_items, validation_rejections = validate_event_log_expansions(
                raw_expansions,
                request.time_range,
                sampled_event_ids,
            )
            log_event(
                phase="event_log_expansion_validation",
                outcome="succeeded",
                raw_expansion_count=len(raw_expansions),
                validated_expansion_count=len(expansion_items),
                rejected_expansion_count=len(validation_rejections),
            )
        except Exception as exc:  # noqa: BLE001
            # Expansion planning failure doesn't block graph
            log_event(
                phase="event_log_expansion_validation",
                outcome="failed",
                error=exc,
            )

    # Stage 3: Execute at most 2 detail calls
    for detail_idx, expansion in enumerate(expansion_items[:MAX_DETAIL_CALLS], start=1):
        detail_evidence_id = f"E-{index + 1 + detail_idx:03d}"
        detail_timed_out = False

        try:
            detail_result = await mcp.collect_event_log_detail(
                client_id=request.client_id,
                org_id=request.org_id or settings.velociraptor_org_id,
                time_from=expansion.date_after,
                time_to=expansion.date_before,
                event_ids=expansion.event_ids,
            )
            detail_item = EvidenceItem(
                evidence_id=detail_evidence_id,
                tool="windows_event_logs_detail",
                collected_at=datetime.now(UTC),
                ok=True,
                data=detail_result,
            )
        except Exception as exc:  # noqa: BLE001 - detail failure doesn't block graph
            error_message, detail_timed_out = _safe_collection_error(exc)
            detail_item = EvidenceItem(
                evidence_id=detail_evidence_id,
                tool="windows_event_logs_detail",
                collected_at=datetime.now(UTC),
                ok=False,
                error=error_message,
                timeout=detail_timed_out,
            )
        evidence = [*evidence, detail_item]

    # M-3 fix: include safe validation rejection labels as limitations
    return {"evidence": evidence, "step_index": index + 1, "limitations": validation_rejections}
