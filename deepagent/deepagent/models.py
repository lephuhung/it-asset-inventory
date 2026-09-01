from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Severity = Literal["critical", "high", "medium", "low", "info"]
Confidence = Literal["high", "medium", "low"]


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
    max_tokens: int = Field(default=4096, ge=64, le=32000)
    system_prompt: str | None = Field(default=None, max_length=8000)


class InvestigationRequest(BaseModel):
    schema_version: Literal["dfir.deepagent.request/1.1"] = "dfir.deepagent.request/1.1"
    investigation_id: UUID
    client_id: str = Field(min_length=3, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    time_range: TimeRange
    suspicious_activity: str = Field(min_length=1, max_length=4000)
    org_id: str | None = Field(default=None, max_length=128)
    llm_runtime: LlmRuntime
    velociraptor_api_client_yaml: str = Field(min_length=32, max_length=256_000)


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
    error: str | None = None


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
