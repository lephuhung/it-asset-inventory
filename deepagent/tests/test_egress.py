"""Tests cho `deepagent.egress` — private-host validation (R7/V3-6).

Bản sao của `server/tests/test_egress.py` cho package deepagent (container riêng).
Dùng monkeypatch `socket.getaddrinfo` để tất định, không phụ thuộc DNS thật.
"""
from __future__ import annotations

import socket

import pytest

from deepagent.egress import (
    EGRESS_CATEGORY,
    EgressError,
    assert_llm_egress,
    assert_redirect_allowed,
    host_header,
    pinned_base_url,
    resolve_private_host,
)

_PUBLIC_IP = "93.184.216.34"  # example.com


def _addr_infos(*ips: str) -> list[tuple]:
    out: list[tuple] = []
    for ip in ips:
        if ":" in ip:
            out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0)))
        else:
            out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)))
    return out


@pytest.fixture
def resolve_hosts(monkeypatch):
    def _set(*ips: str):
        monkeypatch.setattr(
            "deepagent.egress.socket.getaddrinfo",
            lambda host, port, *a, **k: _addr_infos(*ips),
        )

    return _set


def test_substring_host_not_treated_private(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        assert_llm_egress("http://localhost.attacker.example/v1", allow_cloud=False)


def test_private_ip_allowed():
    assert assert_llm_egress("http://10.0.0.5:11434/v1", allow_cloud=False) == "10.0.0.5"


def test_ipv6_loopback_accepted():
    assert assert_llm_egress("http://[::1]:11434/v1", allow_cloud=False) == "::1"


def test_link_local_accepted():
    assert assert_llm_egress("http://169.254.0.1/v1", allow_cloud=False) == "169.254.0.1"


def test_cgnat_accepted():
    assert assert_llm_egress("http://100.64.0.1/v1", allow_cloud=False) == "100.64.0.1"


def test_public_rejected_when_cloud_off(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        assert_llm_egress("https://api.openai.com/v1", allow_cloud=False)


def test_allow_cloud_bypasses_public_check(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    assert assert_llm_egress("https://api.openai.com/v1", allow_cloud=True) == _PUBLIC_IP


def test_pinned_ip_returned():
    assert resolve_private_host("http://10.0.0.5:11434/v1") == ("10.0.0.5", "10.0.0.5")


def test_mixed_private_and_public_rejected(resolve_hosts):
    resolve_hosts("10.0.0.5", _PUBLIC_IP)
    with pytest.raises(EgressError):
        resolve_private_host("http://rebind.example/v1")


def test_error_message_carries_category():
    with pytest.raises(EgressError) as exc:
        assert_llm_egress(f"http://{_PUBLIC_IP}/v1", allow_cloud=False)
    assert f"[{EGRESS_CATEGORY}]" in str(exc.value)


def test_redirect_to_public_rejected(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        assert_redirect_allowed("http://10.0.0.5/v1", "https://api.openai.com/v1", False)


def test_pinned_base_url_and_host_header_helpers():
    assert pinned_base_url("https://llm.internal:8443/v1", "10.0.0.5") == "https://10.0.0.5:8443/v1"
    assert host_header("https://llm.internal:8443/v1") == "llm.internal:8443"


# ── Wiring: OpenAIAnalysisModel validate egress trước khi tạo ChatOpenAI ──


def test_openai_analysis_model_rejects_public_base_url(resolve_hosts):
    from deepagent.analysis_model import OpenAIAnalysisModel
    from deepagent.models import LlmRuntime

    resolve_hosts(_PUBLIC_IP)
    runtime = LlmRuntime(base_url="http://public.example/v1", api_key="k", model="m")
    with pytest.raises(EgressError):
        OpenAIAnalysisModel(runtime)


def test_openai_analysis_model_allows_private_base_url():
    from deepagent.analysis_model import OpenAIAnalysisModel
    from deepagent.models import LlmRuntime

    runtime = LlmRuntime(base_url="http://127.0.0.1:11434/v1", api_key="k", model="m")
    model = OpenAIAnalysisModel(runtime)
    assert model.model_name == "m"


def test_openai_analysis_model_allows_public_when_cloud_on(resolve_hosts):
    from deepagent.analysis_model import OpenAIAnalysisModel
    from deepagent.models import LlmRuntime

    resolve_hosts(_PUBLIC_IP)
    runtime = LlmRuntime(
        base_url="https://api.openai.com/v1", api_key="k", model="m", allow_cloud=True
    )
    model = OpenAIAnalysisModel(runtime)
    assert model.model_name == "m"


def test_llm_runtime_defaults_allow_cloud_false():
    from deepagent.models import LlmRuntime

    runtime = LlmRuntime(base_url="http://127.0.0.1:11434/v1", api_key="k", model="m")
    assert runtime.allow_cloud is False
