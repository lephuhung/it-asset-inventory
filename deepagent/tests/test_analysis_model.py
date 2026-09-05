from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from deepagent.analysis_model import INVARIANT_BOUNDARY, OpenAIAnalysisModel
from deepagent.models import EvidenceItem, InvestigationRequest, LlmRuntime


def _runtime(system_prompt: str | None) -> LlmRuntime:
    return LlmRuntime(
        base_url="http://llm.example/v1",
        api_key="test-key",
        model="test-model",
        system_prompt=system_prompt,
    )


def test_combined_system_message_preserves_invariant_and_operator_prompt() -> None:
    """Một số OpenAI-compatible backend (đặc biệt Qwen3 strict-mode vLLM) từ chối
    request có ≥2 system messages liên tiếp với HTTP 400. _messages() phải gộp
    INVARIANT_BOUNDARY và operator_prompt thành một SystemMessage duy nhất,
    trong khi vẫn giữ nguyên fingerprint/source/prompt semantics.
    """
    model = OpenAIAnalysisModel(_runtime("DATABASE PLAYBOOK"))

    messages = model._messages("<untrusted_case_data>case</untrusted_case_data>")

    # Một system message, một human message — không có 2 system liên tiếp
    assert [type(message) for message in messages] == [SystemMessage, HumanMessage]
    assert len(messages) == 2

    # System message chứa cả invariant boundary và operator prompt
    system_content = messages[0].content
    assert isinstance(system_content, str)
    assert INVARIANT_BOUNDARY in system_content
    assert "DATABASE PLAYBOOK" in system_content
    # Separator giúp operator/reviewer phân biệt hai lớp semantic
    assert "---" in system_content
    # Invariant boundary đứng trước (ưu tiên cao hơn) operator prompt
    assert system_content.index(INVARIANT_BOUNDARY) < system_content.index("DATABASE PLAYBOOK")

    # Human message giữ nguyên task
    assert messages[1].content == "<untrusted_case_data>case</untrusted_case_data>"

    # Metadata không đổi — fingerprint chỉ track operator_prompt
    assert "Báo cáo" not in INVARIANT_BOUNDARY
    assert model.prompt_source == "database"


def test_combined_system_message_uses_default_playbook_when_database_empty() -> None:
    """Khi runtime.system_prompt rỗng, dùng DEFAULT_DFIR_PLAYBOOK; vẫn gộp đúng."""
    from deepagent.analysis_model import DEFAULT_DFIR_PLAYBOOK

    model = OpenAIAnalysisModel(_runtime(None))

    messages = model._messages("case")

    assert [type(message) for message in messages] == [SystemMessage, HumanMessage]
    system_content = messages[0].content
    assert INVARIANT_BOUNDARY in system_content
    assert DEFAULT_DFIR_PLAYBOOK in system_content
    assert model.prompt_source == "default"


def test_empty_database_prompt_uses_default_playbook_fingerprint() -> None:
    model = OpenAIAnalysisModel(_runtime(None))

    assert model.prompt_source == "default"
    assert len(model.prompt_fingerprint) == 12


@pytest.mark.asyncio
async def test_tier2_planner_returns_two_structured_triggered_steps() -> None:
    """The model adapter must preserve two independent Tier 2 selections."""

    class StructuredInvoker:
        async def ainvoke(self, _messages):
            return {
                "steps": [
                    {
                        "tool": "custom:Custom.DFIR.Windows.Execution",
                        "rationale": "Encoded PowerShell execution trigger",
                    },
                    {
                        "tool": "custom:Custom.DFIR.Windows.Persistence",
                        "rationale": "New autorun persistence trigger",
                    },
                ]
            }

    class FakeChatModel:
        def with_structured_output(self, _schema):
            return StructuredInvoker()

    now = datetime.now(UTC)
    request = InvestigationRequest(
        investigation_id="11111111-1111-4111-8111-111111111111",
        client_id="C.0123456789abcdef",
        hostname="WS-01",
        target_platform="windows",
        time_range={"from": (now - timedelta(hours=1)).isoformat(), "to": now.isoformat()},
        suspicious_activity="Encoded PowerShell and a new Run key",
        llm_runtime=_runtime("RECALL-FIRST PLAYBOOK"),
        velociraptor_api_client_yaml=(
            "ca_certificate: test\nclient_cert: test\nclient_private_key: test\n"
        ),
    )
    evidence = [
        EvidenceItem(
            evidence_id="E-001",
            tool="custom:Custom.DFIR.Windows.Triage",
            collected_at=now,
            ok=True,
            data={"rows": []},
        )
    ]
    model = OpenAIAnalysisModel(_runtime("RECALL-FIRST PLAYBOOK"))
    model._model = FakeChatModel()

    steps = await model.plan_tier2_expansion(
        request,
        evidence,
        {
            "custom:Custom.DFIR.Windows.Execution",
            "custom:Custom.DFIR.Windows.Persistence",
        },
    )

    assert [step.tool for step in steps] == [
        "custom:Custom.DFIR.Windows.Execution",
        "custom:Custom.DFIR.Windows.Persistence",
    ]
