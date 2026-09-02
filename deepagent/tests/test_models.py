from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from deepagent.models import EvidenceItem, InvestigationRequest, TimeRange


def test_request_normalizes_time_to_utc() -> None:
    now = datetime.now(UTC)
    request = InvestigationRequest(
        investigation_id="11111111-1111-4111-8111-111111111111",
        client_id="C.0123456789abcdef",
        hostname="WS-01",
        time_range={"from": (now - timedelta(hours=2)).isoformat(), "to": now.isoformat()},
        suspicious_activity="Test",
        llm_runtime={"base_url": "http://llm.local/v1", "api_key": "test-key", "model": "test"},
        velociraptor_api_client_yaml="ca_certificate: test\nclient_cert: test\nclient_private_key: test\n",
    )
    assert request.time_range.from_.tzinfo == UTC
    assert request.time_range.to.tzinfo == UTC


def test_request_rejects_naive_or_reversed_time_range() -> None:
    with pytest.raises(ValidationError):
        InvestigationRequest(
            investigation_id="11111111-1111-4111-8111-111111111111",
            client_id="C.0123456789abcdef",
            hostname="WS-01",
            time_range={"from": "2026-01-01T10:00:00", "to": "2026-01-01T09:00:00"},
            suspicious_activity="Test",
            llm_runtime={"base_url": "http://llm.local/v1", "api_key": "test-key", "model": "test"},
            velociraptor_api_client_yaml="ca_certificate: test\nclient_cert: test\nclient_private_key: test\n",
        )


# -------------------------------------------------------------------------
# Task 3: Event log expansion validation and evidence budgeting
# -------------------------------------------------------------------------

# Shared fixtures for expansion tests
FROM = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
TO = datetime(2026, 6, 1, 11, 0, 0, tzinfo=UTC)
REQUEST_RANGE = TimeRange(**{"from": FROM, "to": TO})


def valid_expansion(event_id: str) -> dict:
    """Create a valid expansion dict for testing."""
    return {
        "date_after": FROM.isoformat(),
        "date_before": TO.isoformat(),
        "event_ids": [event_id],
        "rationale": f"expand {event_id}",
    }


def test_expansion_rejects_time_outside_case_window() -> None:
    """Expansions outside the request time range must be rejected."""
    from deepagent.models import validate_event_log_expansions

    # Expansion window starts before case window
    expansion = {
        "date_after": (FROM - timedelta(seconds=1)).isoformat(),
        "date_before": TO.isoformat(),
        "event_ids": ["4688"],
        "rationale": "x",
    }
    accepted, rejections = validate_event_log_expansions([expansion], REQUEST_RANGE, {"4688"})
    assert accepted == []
    # M-3 fix: rejection label is recorded
    assert len(rejections) > 0


def test_expansion_rejects_duration_over_60_minutes() -> None:
    """Expansions longer than 60 minutes must be rejected."""
    from deepagent.models import validate_event_log_expansions

    # 61 minutes duration
    expansion = {
        "date_after": FROM.isoformat(),
        "date_before": (FROM + timedelta(minutes=61)).isoformat(),
        "event_ids": ["4688"],
        "rationale": "x",
    }
    accepted, rejections = validate_event_log_expansions([expansion], REQUEST_RANGE, {"4688"})
    assert accepted == []
    # M-3 fix: rejection label is recorded
    assert "window_exceeds_60_minutes" in rejections


def test_expansion_rejects_unknown_event_ids() -> None:
    """Expansions with event IDs not in sampled set must be rejected."""
    from deepagent.models import validate_event_log_expansions

    expansion = valid_expansion("99999")  # Not in sampled set
    accepted, rejections = validate_event_log_expansions([expansion], REQUEST_RANGE, {"4688", "1102"})
    assert accepted == []
    # M-3 fix: rejection label is recorded
    assert "event_ids_not_in_sample" in rejections


def test_expansion_keeps_at_most_two_50_row_requests_with_sampled_ids() -> None:
    """At most two valid expansions are kept; extras are discarded."""
    from deepagent.models import validate_event_log_expansions

    expansions = [
        valid_expansion("4688"),
        valid_expansion("1102"),
        valid_expansion("4625"),
    ]
    accepted, rejections = validate_event_log_expansions(
        expansions, REQUEST_RANGE, {"4688", "1102", "4625"}
    )
    assert len(accepted) == 2
    # M-3 fix: overflow rejection is recorded
    assert "expansion_count_exceeded" in rejections


def test_fit_evidence_budget_never_exceeds_global_max_chars() -> None:
    """Evidence budget enforcement must never exceed the configured max_chars."""
    from deepagent.models import fit_evidence_budget

    evidence = [
        EvidenceItem(
            evidence_id=f"E-{index:03d}",
            tool="windows_event_logs",
            collected_at=datetime.now(UTC),
            ok=True,
            data={"payload": "x" * 80_000},
        )
        for index in range(3)
    ]
    bounded = fit_evidence_budget(evidence, max_chars=120_000)
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in bounded],
        ensure_ascii=False,
        default=str,
    )
    assert len(serialized) <= 120_000


def test_fit_evidence_budget_preserves_evidence_metadata() -> None:
    """Evidence budget must preserve IDs, tools, flags, and truncation metadata."""
    from deepagent.models import fit_evidence_budget

    now = datetime.now(UTC)
    evidence = [
        EvidenceItem(
            evidence_id="E-001",
            tool="windows_pslist",
            collected_at=now,
            ok=True,
            data={"rows": 100},
        ),
        EvidenceItem(
            evidence_id="E-002",
            tool="windows_event_logs",
            collected_at=now,
            ok=False,
            error="MCP collection failed.",
            timeout=False,
        ),
        EvidenceItem(
            evidence_id="E-003",
            tool="windows_netstat_enriched",
            collected_at=now,
            ok=True,
            timeout=True,
            data={"rows": 50, "truncated": True, "preview": "x" * 500},
        ),
    ]
    bounded = fit_evidence_budget(evidence, max_chars=50_000)
    # All evidence items must be preserved (they're small enough)
    assert len(bounded) == 3
    assert {item.evidence_id for item in bounded} == {"E-001", "E-002", "E-003"}
    assert {item.tool for item in bounded} == {"windows_pslist", "windows_event_logs", "windows_netstat_enriched"}
    # Flags must be preserved
    failed = next(item for item in bounded if item.evidence_id == "E-002")
    assert failed.ok is False
    assert failed.error == "MCP collection failed."
    timed = next(item for item in bounded if item.evidence_id == "E-003")
    assert timed.timeout is True


def test_fit_evidence_budget_keeps_evidence_item_if_data_budget_remains() -> None:
    """Evidence items should not be removed entirely unless data budget is zero."""
    from deepagent.models import fit_evidence_budget

    now = datetime.now(UTC)
    # Create evidence with large data
    evidence = [
        EvidenceItem(
            evidence_id="E-001",
            tool="windows_event_logs",
            collected_at=now,
            ok=True,
            data={"payload": "x" * 5000},
        ),
    ]
    # Very small budget but not zero - item should be kept with truncated data
    bounded = fit_evidence_budget(evidence, max_chars=500)
    assert len(bounded) == 1
    # The item is kept but data may be reduced
    assert bounded[0].evidence_id == "E-001"


def test_fit_evidence_budget_removes_item_only_when_data_budget_is_zero() -> None:
    """Evidence item should be removed only if data budget is zero."""
    from deepagent.models import fit_evidence_budget

    now = datetime.now(UTC)
    evidence = [
        EvidenceItem(
            evidence_id="E-001",
            tool="windows_event_logs",
            collected_at=now,
            ok=True,
            data={"payload": "x" * 100},
        ),
    ]
    # Zero budget - item is removed
    bounded = fit_evidence_budget(evidence, max_chars=0)
    assert len(bounded) == 0
