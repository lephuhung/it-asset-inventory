"""Tests for max_tokens runaway fix (deepagent Tier 2 plan timeout).

Fix verified by GPT review (run 6e28d61c-aad0-47fd-bbe8-c1cc53c97617):

  - Change 1: relax LlmRuntime.max_tokens constraint to ge=1_000
  - Change 2: per-call max_tokens override on 4 with_structured_output() calls
  - Change 3: pin ChatOpenAI max_retries=0 to fail fast instead of 3× timeout
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from deepagent.analysis_model import OpenAIAnalysisModel
from deepagent.models import (
    Assessment,
    EventLogExpansion,
    EventLogExpansionList,
    InvestigationPlan,
    InvestigationRequest,
    LlmRuntime,
    Tier2Decision,
)


# ===========================================================================
# Change 1: LlmRuntime constraint
# ===========================================================================


class TestLlmRuntimeMaxTokensConstraint:
    def test_default_max_tokens_is_8000(self) -> None:
        """After fix, default is 8_000 (was 64_000) — defense-in-depth
        against max_tokens runaway if per-call override is forgotten.
        """
        runtime = LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        )
        assert runtime.max_tokens == 8_000

    def test_accepts_1000_as_minimum(self) -> None:
        """Lower bound 1_000 — prevents pathological max_tokens=100 config."""
        runtime = LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
            max_tokens=1_000,
        )
        assert runtime.max_tokens == 1_000

    def test_rejects_max_tokens_below_1000(self) -> None:
        """Anything below 1_000 is too small for any schema in this codebase."""
        with pytest.raises(ValidationError):
            LlmRuntime(
                base_url="http://llm.example/v1",
                api_key="test-key",
                model="test-model",
                max_tokens=500,
            )

    def test_rejects_max_tokens_zero(self) -> None:
        with pytest.raises(ValidationError):
            LlmRuntime(
                base_url="http://llm.example/v1",
                api_key="test-key",
                model="test-model",
                max_tokens=0,
            )

    def test_upper_bound_unchanged(self) -> None:
        """Upper bound 128_000 still valid (existing test kept)."""
        runtime = LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
            max_tokens=128_000,
        )
        assert runtime.max_tokens == 128_000


# ===========================================================================
# Change 3: ChatOpenAI max_retries=0
# ===========================================================================


class TestChatOpenAIMaxRetries:
    def test_openai_analysis_model_pins_max_retries_zero(self) -> None:
        """The constructor must pass max_retries=0 so a timeout doesn't
        amplify to 3× wall-clock via the langchain retry layer.
        """
        runtime = LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        )
        model = OpenAIAnalysisModel(runtime)
        # ChatOpenAI instance is stored on ._model
        assert model._model.max_retries == 0


# ===========================================================================
# Change 2: per-call max_tokens overrides
# Mock-based tests for stability across langchain-openai versions.
# ===========================================================================


def _make_request() -> InvestigationRequest:
    now = datetime.now(UTC)
    return InvestigationRequest(
        investigation_id=UUID("11111111-1111-4111-8111-111111111111"),
        client_id="C.0123456789abcdef",
        hostname="WS-01",
        target_platform="windows",
        time_range={"from": (now - timedelta(hours=1)).isoformat(), "to": now.isoformat()},
        suspicious_activity="test",
        llm_runtime={"base_url": "http://llm.local/v1", "api_key": "k", "model": "m"},
        velociraptor_api_client_yaml=(
            "ca_certificate: t\nclient_cert: t\nclient_private_key: t\n"
        ),
    )


class _SpyChatModel:
    """Spy that captures kwargs passed to with_structured_output().

    Returns a fake planner whose ainvoke() returns a deterministic
    structured value, so the calling code under test can run end-to-end
    without touching the real OpenAI client.
    """

    def __init__(self, return_value):
        self._return_value = return_value
        self.captured_kwargs: list[dict] = []
        self.captured_schema: list = []

    def with_structured_output(self, schema, **kwargs):
        self.captured_schema.append(schema)
        self.captured_kwargs.append(kwargs)

        planner = MagicMock()
        planner.ainvoke = AsyncMock(return_value=self._return_value)
        return planner


class TestPerCallMaxTokensOverrides:
    def _model_with_spy(self, return_value) -> tuple[OpenAIAnalysisModel, _SpyChatModel]:
        runtime = LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="test-key",
            model="test-model",
        )
        model = OpenAIAnalysisModel(runtime)
        spy = _SpyChatModel(return_value)
        model._model = spy
        return model, spy

    def test_plan_tier1_passes_max_tokens_8000(self) -> None:
        """Tier 1 plan sized at 8_000 (default).

        4_000 caused LengthFinishReasonError on Qwen3.6-35B with general
        instructions (reasoning text exceeds 4K before structured JSON).
        Plan output is bounded by INITIAL_TRIAGE_MAX_STEPS=3 + hypothesis,
        but Qwen emits pre-answer reasoning that counts against the cap.
        """
        plan = InvestigationPlan(
            hypothesis="x" * 1000,
            steps=[
                {"tool": "windows_pslist", "rationale": "y" * 500}
                for _ in range(3)
            ],
        )
        model, spy = self._model_with_spy(plan)
        asyncio.run(model.plan(_make_request()))

        assert len(spy.captured_kwargs) == 1
        assert spy.captured_kwargs[0].get("max_tokens") == 8_000

    def test_plan_tier2_expansion_passes_max_tokens_16000(self) -> None:
        """Tier 2 plan: structured JSON, max 2 steps × ~500 tokens.

        Sized at 16_000 because Qwen3.6-35B reasoning model with general
        instructions can emit >8K tokens of pre-answer reasoning before
        structured JSON is satisfied. 8_000 caused LengthFinishReasonError.
        """
        decision = Tier2Decision(
            steps=[
                {"tool": "windows_pslist", "rationale": "y" * 500},
                {"tool": "windows_autoruns", "rationale": "z" * 500},
            ]
        )
        model, spy = self._model_with_spy(decision)
        request = _make_request()
        evidence = []
        asyncio.run(model.plan_tier2_expansion(request, evidence, {"tool1"}))

        assert len(spy.captured_kwargs) == 1
        assert spy.captured_kwargs[0].get("max_tokens") == 16_000

    def test_plan_event_log_expansion_passes_max_tokens_1500(self) -> None:
        """EventLogExpansionList: up to 2 items × ~600 chars ≈ 1500 tokens."""
        expansions = EventLogExpansionList(
            expansions=[
                EventLogExpansion(
                    date_after=datetime(2026, 1, 1, tzinfo=UTC),
                    date_before=datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
                    event_ids=["4624"],
                    rationale="x" * 500,
                )
            ]
        )
        model, spy = self._model_with_spy(expansions)
        request = _make_request()
        sampled_ids = {"4624"}
        triage_result = {"rows": 100, "truncated": False, "event_ids": ["4624"]}
        asyncio.run(
            model.plan_event_log_expansion(request, sampled_ids, triage_result)
        )

        assert len(spy.captured_kwargs) == 1
        assert spy.captured_kwargs[0].get("max_tokens") == 1_500

    def test_assess_passes_max_tokens_8000(self) -> None:
        """Assess produces a markdown report. 10 findings × ~1500 chars
        + boilerplate can approach 6000-8000 tokens; 8000 is the safe
        ceiling per GPT review.
        """
        assessment = Assessment(
            severity="low",
            confidence="medium",
            executive_summary="summary",
            conclusion="conclusion",
            findings=[],
        )
        model, spy = self._model_with_spy(assessment)
        asyncio.run(model.assess(_make_request(), []))

        assert len(spy.captured_kwargs) == 1
        assert spy.captured_kwargs[0].get("max_tokens") == 8_000


# ===========================================================================
# Per-call logging (improvement #6 from review): log max_tokens
# ===========================================================================


class TestLogEventIncludesMaxTokens:
    """Operators need max_tokens in log events to debug future latency issues."""

    def test_plan_logs_max_tokens(self, monkeypatch) -> None:
        captured: list[dict] = []

        def fake_log_event(**kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(
            "deepagent.analysis_model.log_event", fake_log_event
        )

        plan = InvestigationPlan(
            hypothesis="x",
            steps=[{"tool": "windows_pslist", "rationale": "y"}],
        )
        runtime = LlmRuntime(
            base_url="http://llm.example/v1",
            api_key="k",
            model="m",
        )
        model = OpenAIAnalysisModel(runtime)
        spy = _SpyChatModel(plan)
        model._model = spy

        asyncio.run(model.plan(_make_request()))

        assert any(c.get("max_tokens") == 8_000 for c in captured), (
            f"Expected log_event to receive max_tokens=8000, "
            f"got kwargs: {captured}"
        )
