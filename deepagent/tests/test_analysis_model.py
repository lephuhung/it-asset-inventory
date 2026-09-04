from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from deepagent.analysis_model import INVARIANT_BOUNDARY, OpenAIAnalysisModel
from deepagent.models import LlmRuntime


def _runtime(system_prompt: str | None) -> LlmRuntime:
    return LlmRuntime(
        base_url="http://llm.example/v1",
        api_key="test-key",
        model="test-model",
        system_prompt=system_prompt,
    )


def test_database_prompt_is_a_distinct_system_message() -> None:
    model = OpenAIAnalysisModel(_runtime("DATABASE PLAYBOOK"))

    messages = model._messages("<untrusted_case_data>case</untrusted_case_data>")

    assert [type(message) for message in messages] == [
        SystemMessage,
        SystemMessage,
        HumanMessage,
    ]
    assert messages[0].content == INVARIANT_BOUNDARY
    assert messages[1].content == "DATABASE PLAYBOOK"
    assert "Báo cáo" not in INVARIANT_BOUNDARY
    assert model.prompt_source == "database"


def test_empty_database_prompt_uses_default_playbook_fingerprint() -> None:
    model = OpenAIAnalysisModel(_runtime(None))

    assert model.prompt_source == "default"
    assert len(model.prompt_fingerprint) == 12
