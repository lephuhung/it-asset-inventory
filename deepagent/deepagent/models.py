from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Severity = Literal["critical", "high", "medium", "low", "info"]
Confidence = Literal["high", "medium", "low"]
Platform = Literal["windows", "linux", "macos"]

# Constants for event log expansion constraints
MAX_DETAIL_CALLS: int = 2
MAX_EVENT_LOG_DURATION_MINUTES: int = 60
MAX_EVENT_LOG_EXPANSION_ROWS: int = 50


class TimeRange(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime

    @model_validator(mode="after")
    def validate_range(self) -> TimeRange:
        if self.from_.tzinfo is None or self.to.tzinfo is None:
            raise ValueError("Khoảng thời gian phải có timezone")
        self.from_ = self.from_.astimezone(UTC)
        self.to = self.to.astimezone(UTC)
        if self.from_ >= self.to:
            raise ValueError("time_range.from phải nhỏ hơn time_range.to")
        if (self.to - self.from_).days > 31:
            raise ValueError("Một investigation không được vượt quá 31 ngày")
        return self


class LlmRuntime(BaseModel):
    base_url: str = Field(min_length=8, max_length=512)
    api_key: str = Field(min_length=1, max_length=4096)
    model: str = Field(min_length=1, max_length=255)
    temperature: float = Field(default=0, ge=0, le=2)
    timeout_seconds: int = Field(default=180, ge=10, le=600)
    max_tokens: int = Field(default=64_000, ge=64_000, le=128_000)
    system_prompt: str | None = Field(default=None, max_length=8000)


class CustomArtifactRef(BaseModel):
    """Một artifact Custom.* do backend ký phát trong request — model chỉ được
    chọn theo tên, không được tự thêm artifact hay tham số."""

    name: str = Field(
        min_length=8,
        max_length=255,
        pattern=r"^Custom\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$",
    )
    description: str = Field(default="", max_length=300)


class InvestigationRequest(BaseModel):
    schema_version: Literal["dfir.deepagent.request/1.2"] = "dfir.deepagent.request/1.2"
    investigation_id: UUID
    client_id: str = Field(min_length=3, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    target_platform: Platform
    time_range: TimeRange
    suspicious_activity: str = Field(min_length=1, max_length=4000)
    org_id: str | None = Field(default=None, max_length=128)
    llm_runtime: LlmRuntime
    velociraptor_api_client_yaml: str = Field(min_length=32, max_length=256_000)
    # Catalog động: artifact Custom.* (type CLIENT) đang enabled trên backend.
    # Optional để tương thích ngược với backend cũ (schema giữ 1.1).
    custom_artifacts: list[CustomArtifactRef] = Field(default_factory=list, max_length=20)


class InvestigationStep(BaseModel):
    tool: str
    rationale: str = Field(min_length=1, max_length=500)


class InvestigationPlan(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=1000)
    steps: list[InvestigationStep] = Field(min_length=1, max_length=12)


class EvidenceItem(BaseModel):
    evidence_id: str
    tool: str
    collected_at: datetime
    ok: bool
    data: object | None = None
    pagination: dict[str, object] | None = None
    error: str | None = None
    # Explicit non-sensitive marker set when the MCP call hit its caller
    # deadline. The runner uses it to compute timed_out_tool_count without
    # matching external error strings, which may contain sensitive content.
    timeout: bool = False


class Finding(BaseModel):
    id: str = Field(pattern=r"^F-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=300)
    severity: Severity
    confidence: Confidence
    status: Literal["observed", "inferred", "not_observed"]
    evidence_refs: list[str] = Field(default_factory=list)
    evidence: str = Field(min_length=1, max_length=4000)
    mitre_id: str | None = Field(default=None, max_length=32)
    recommendation: str = Field(min_length=1, max_length=2000)


class Ioc(BaseModel):
    type: Literal["ip", "domain", "url", "hash", "process", "file", "registry", "other"]
    value: str = Field(min_length=1, max_length=1000)
    evidence_ref: str


class Assessment(BaseModel):
    severity: Severity
    confidence: Confidence
    executive_summary: str = Field(min_length=1, max_length=4000)
    conclusion: str = Field(min_length=1, max_length=4000)
    findings: list[Finding] = Field(default_factory=list, max_length=50)
    iocs: list[Ioc] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class CallbackPayload(BaseModel):
    report_markdown: str
    severity: Severity
    findings_count: int
    findings: list[dict]
    iocs: list[dict]
    llm_provider: str = "deepagent-langgraph"
    llm_model: str
    external_job_id: str
    error: str | None = None
    raw_response: dict | None = None


class JobStatus(BaseModel):
    job_id: str
    investigation_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class McpTestResult(BaseModel):
    ok: bool
    tools: list[str] = Field(default_factory=list)
    client_count_sampled: int | None = None
    error: str | None = None


class McpTestRequest(BaseModel):
    """Velociraptor config is supplied only for the lifetime of an MCP check."""

    velociraptor_api_client_yaml: str = Field(min_length=32, max_length=256_000)


# =============================================================================
# Task 3: Event log expansion and evidence budgeting
# =============================================================================


class EventLogExpansion(BaseModel):
    """Validated event log expansion request.

    Represents a bounded request to collect event log detail for specific
    Event IDs within a constrained time window.
    """

    date_after: datetime
    date_before: datetime
    event_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_window(self) -> EventLogExpansion:
        if self.date_after.tzinfo is None or self.date_before.tzinfo is None:
            raise ValueError("Expansion timestamps must have timezone")
        self.date_after = self.date_after.astimezone(UTC)
        self.date_before = self.date_before.astimezone(UTC)
        duration = self.date_before - self.date_after
        if duration.total_seconds() < 0:
            raise ValueError("date_after must be before date_before")
        if duration > timedelta(minutes=MAX_EVENT_LOG_DURATION_MINUTES):
            raise ValueError(f"Expansion window exceeds {MAX_EVENT_LOG_DURATION_MINUTES} minutes")
        return self


class EventLogExpansionList(BaseModel):
    """H-2 fix: wrapper to allow LLM to return 0..2 expansions as a list.

    Using a single-item schema (with_structured_output(EventLogExpansion)) capped
    production at one expansion. This wrapper uses min_length=0 so the LLM can
    return an empty list when no expansion is needed, and max_length=2 so it can
    return up to two items. The downstream validate_event_log_expansions also caps
    at MAX_DETAIL_CALLS=2.
    """

    expansions: list[EventLogExpansion] = Field(
        default_factory=list,
        min_length=0,
        max_length=2,
    )


def validate_event_log_expansions(
    expansions: list[dict | EventLogExpansion],
    request_range: TimeRange,
    sampled_event_ids: set[str],
) -> tuple[list[EventLogExpansion], list[str]]:
    """Validate a list of event log expansions.

    Returns (accepted, rejections) where:
    - accepted: list of valid EventLogExpansion objects, limited to MAX_DETAIL_CALLS
    - rejections: safe static labels for invalid choices (never raw LLM text)

    Validation rules:
    - Reject more than MAX_DETAIL_CALLS items
    - Reject expansions with duration over 60 minutes
    - Reject timestamps outside request.time_range
    - Reject empty or unknown Event IDs (must be in sampled_event_ids)
    - Reject values that fail strict model schema validation

    Rejection labels use only static strings; never echo raw LLM text.
    """
    validated: list[EventLogExpansion] = []
    seen_ids: set[str] = set()  # Deduplicate by event_ids content
    rejections: list[str] = []

    for expansion in expansions:
        if len(validated) >= MAX_DETAIL_CALLS:
            # Record overflow as safe limitation (M-3 fix)
            if len(expansions) > MAX_DETAIL_CALLS:
                rejections.append("expansion_count_exceeded")
            break  # Stop after MAX_DETAIL_CALLS

        try:
            # Parse dict input to EventLogExpansion
            if isinstance(expansion, dict):
                parsed = EventLogExpansion.model_validate(expansion)
            else:
                parsed = expansion

            # Check event IDs are in sampled set
            if not parsed.event_ids:
                rejections.append("event_ids_empty")
                continue
            unknown_ids = set(parsed.event_ids) - sampled_event_ids
            if unknown_ids:
                rejections.append("event_ids_not_in_sample")
                continue  # Skip expansions with unknown event IDs

            # Check window is within request range
            if parsed.date_after < request_range.from_:
                rejections.append("window_before_case_range")
                continue  # Outside case window
            if parsed.date_before > request_range.to:
                rejections.append("window_after_case_range")
                continue  # Outside case window

            # Check duration is within limit
            duration = parsed.date_before - parsed.date_after
            if duration > timedelta(minutes=MAX_EVENT_LOG_DURATION_MINUTES):
                rejections.append("window_exceeds_60_minutes")
                continue  # Duration exceeded

            # Deduplicate by event_ids content
            ids_key = frozenset(parsed.event_ids)
            if ids_key in seen_ids:
                rejections.append("expansion_duplicate")
                continue
            seen_ids.add(ids_key)

            validated.append(parsed)

        except Exception as exc:  # noqa: BLE001 - defensive catch preserves graph flow
            # Reject values that fail strict model schema (M-3 fix: categorize the failure)
            exc_msg = str(exc).lower()
            if "60 minutes" in exc_msg or "exceeds" in exc_msg:
                rejections.append("window_exceeds_60_minutes")
            elif "before" in exc_msg or "after" in exc_msg:
                rejections.append("window_before_case_range")
            elif "timezone" in exc_msg:
                rejections.append("expansion_schema_invalid")
            else:
                rejections.append("expansion_schema_invalid")
            continue

    return validated, rejections


def fit_evidence_budget(
    evidence: list[EvidenceItem],
    max_chars: int,
) -> list[EvidenceItem]:
    """Bound evidence to fit within max_chars using deterministic JSON-size accounting.

    Rules:
    - Preserve evidence IDs, tools, success/error/timeout flags, truncation metadata
    - Preserve the earliest safe preview (from truncated data)
    - Reduce data fields until serialized list is at or below max_chars
    - Never remove an evidence item entirely unless its data budget is zero
    """
    if max_chars <= 0:
        return []  # Zero budget means no evidence

    # First pass: check if we're already within budget
    def serialize(items: list[EvidenceItem]) -> str:
        return json.dumps(
            [item.model_dump(mode="json") for item in items],
            ensure_ascii=False,
            default=str,
        )

    current = serialize(evidence)
    if len(current) <= max_chars:
        return evidence

    # Need to reduce data. Create a copy to modify.
    bounded: list[EvidenceItem] = []

    for item in evidence:
        # Copy the item
        new_data = item.data
        was_truncated = isinstance(new_data, dict) and new_data.get("truncated")

        # For items with large data, try to reduce
        if new_data is not None:
            # Serialize with current data to estimate size
            test_item = EvidenceItem(
                evidence_id=item.evidence_id,
                tool=item.tool,
                collected_at=item.collected_at,
                ok=item.ok,
                data=new_data,
                pagination=item.pagination,
                error=item.error,
                timeout=item.timeout,
            )
            test_serialized = serialize(bounded + [test_item])

            if len(test_serialized) <= max_chars:
                bounded.append(test_item)
            elif was_truncated:
                # Already truncated, keep preview only
                preview = new_data.get("preview", "") if isinstance(new_data, dict) else str(new_data)
                new_item = EvidenceItem(
                    evidence_id=item.evidence_id,
                    tool=item.tool,
                    collected_at=item.collected_at,
                    ok=item.ok,
                    data={"truncated": True, "preview": preview},
                    pagination=item.pagination,
                    error=item.error,
                    timeout=item.timeout,
                )
                test_serialized = serialize(bounded + [new_item])
                if len(test_serialized) <= max_chars:
                    bounded.append(new_item)
                else:
                    # Keep only metadata, no data
                    minimal_item = EvidenceItem(
                        evidence_id=item.evidence_id,
                        tool=item.tool,
                        collected_at=item.collected_at,
                        ok=item.ok,
                        data={"truncated": True, "preview": preview[:100] if preview else ""},
                        pagination=item.pagination,
                        error=item.error,
                        timeout=item.timeout,
                    )
                    bounded.append(minimal_item)
            else:
                # Try to truncate the data
                if isinstance(new_data, dict):
                    # Keep only simple metadata
                    new_item = EvidenceItem(
                        evidence_id=item.evidence_id,
                        tool=item.tool,
                        collected_at=item.collected_at,
                        ok=item.ok,
                        data={"truncated": True, "preview": f"{len(new_data)} fields truncated"},
                        pagination=item.pagination,
                        error=item.error,
                        timeout=item.timeout,
                    )
                    test_serialized = serialize(bounded + [new_item])
                    if len(test_serialized) <= max_chars:
                        bounded.append(new_item)
                    else:
                        bounded.append(item)  # Fallback - keep as-is
                elif isinstance(new_data, list):
                    # Try reducing list size
                    new_item = EvidenceItem(
                        evidence_id=item.evidence_id,
                        tool=item.tool,
                        collected_at=item.collected_at,
                        ok=item.ok,
                        data={"truncated": True, "preview": f"{len(new_data)} rows truncated"},
                        pagination=item.pagination,
                        error=item.error,
                        timeout=item.timeout,
                    )
                    test_serialized = serialize(bounded + [new_item])
                    if len(test_serialized) <= max_chars:
                        bounded.append(new_item)
                    else:
                        bounded.append(item)  # Fallback
                else:
                    # Other data types - keep as-is if we have room
                    bounded.append(item)
        else:
            # No data field, just add metadata
            bounded.append(item)

    # Final check: if still over budget, truncate further
    current = serialize(bounded)
    if len(current) <= max_chars:
        return bounded

    # Aggressive truncation - keep only metadata
    result: list[EvidenceItem] = []
    for item in evidence:
        minimal = EvidenceItem(
            evidence_id=item.evidence_id,
            tool=item.tool,
            collected_at=item.collected_at,
            ok=item.ok,
            data={"truncated": True, "preview": "data truncated due to budget"},
            pagination=item.pagination,
            error=item.error,
            timeout=item.timeout,
        )
        test = serialize(result + [minimal])
        if len(test) <= max_chars:
            result.append(minimal)
        else:
            # Just metadata
            bare = EvidenceItem(
                evidence_id=item.evidence_id,
                tool=item.tool,
                collected_at=item.collected_at,
                ok=item.ok,
                data=None,
                pagination=item.pagination,
                error=item.error,
                timeout=item.timeout,
            )
            test = serialize(result + [bare])
            if len(test) <= max_chars:
                result.append(bare)
            # If still doesn't fit, skip this item

    return result
