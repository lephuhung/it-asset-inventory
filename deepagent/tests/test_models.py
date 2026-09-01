from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from deepagent.models import InvestigationRequest


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
