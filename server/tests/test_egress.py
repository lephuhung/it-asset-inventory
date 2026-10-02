"""Tests cho `app.core.egress` — private-host validation (R7/V3-6).

Dùng monkeypatch `socket.getaddrinfo` để kiểm tra phân loại IP tất định (không phụ
thuộc DNS thật); các test IP literal không cần DNS.
"""
from __future__ import annotations

import socket

import pytest

from app.core.egress import (
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
    """Ép `socket.getaddrinfo` trả về các IP cho trước (không DNS thật)."""

    def _set(*ips: str):
        monkeypatch.setattr(
            "app.core.egress.socket.getaddrinfo",
            lambda host, port, *a, **k: _addr_infos(*ips),
        )

    return _set


# ── Host name không còn bị nhầm là private vì substring ──


def test_substring_host_not_treated_private(resolve_hosts):
    """`localhost.attacker.example` resolve ra IP public → phải bị từ chối."""
    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        assert_llm_egress("http://localhost.attacker.example/v1", allow_cloud=False)


def test_substring_hostname_with_private_ip_allowed(resolve_hosts):
    """Tên chứa `localhost` nhưng thực sự trỏ về IP private → chấp nhận."""
    resolve_hosts("10.0.0.7")
    pinned = assert_llm_egress("http://localhost.internal.example/v1", allow_cloud=False)
    assert pinned == "10.0.0.7"


# ── Phân loại IP literal ──


def test_private_ip_allowed():
    assert assert_llm_egress("http://10.0.0.5:11434/v1", allow_cloud=False) == "10.0.0.5"


def test_ipv4_loopback_allowed():
    assert assert_llm_egress("http://127.0.0.1:11434/v1", allow_cloud=False) == "127.0.0.1"


def test_ipv6_loopback_accepted():
    assert assert_llm_egress("http://[::1]:11434/v1", allow_cloud=False) == "::1"


def test_link_local_accepted():
    assert assert_llm_egress("http://169.254.0.1/v1", allow_cloud=False) == "169.254.0.1"


def test_cgnat_accepted():
    assert assert_llm_egress("http://100.64.0.1/v1", allow_cloud=False) == "100.64.0.1"


def test_ipv6_private_accepted():
    assert assert_llm_egress("http://[fd00::1]/v1", allow_cloud=False) == "fd00::1"


def test_public_rejected_when_cloud_off():
    with pytest.raises(EgressError):
        assert_llm_egress(f"http://{_PUBLIC_IP}/v1", allow_cloud=False)


def test_public_rejected_via_dns(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        assert_llm_egress("https://api.openai.com/v1", allow_cloud=False)


# ── allow_cloud ──


def test_allow_cloud_bypasses_public_check(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    assert assert_llm_egress("https://api.openai.com/v1", allow_cloud=True) == _PUBLIC_IP


def test_allow_cloud_records_public_host(resolve_hosts, caplog):
    resolve_hosts(_PUBLIC_IP)
    with caplog.at_level("WARNING", logger="egress"):
        resolve_private_host("https://api.openai.com/v1", allow_cloud=True)
    assert any("public" in rec.message for rec in caplog.records)


# ── Kết quả ghim + an toàn DNS ──


def test_pinned_ip_returned():
    host, pinned = resolve_private_host("http://10.0.0.5:11434/v1")
    assert (host, pinned) == ("10.0.0.5", "10.0.0.5")


def test_hostname_pins_resolved_ip(resolve_hosts):
    resolve_hosts("10.1.2.3")
    host, pinned = resolve_private_host("http://llm.internal:11434/v1")
    assert host == "llm.internal"
    assert pinned == "10.1.2.3"


def test_mixed_private_and_public_rejected(resolve_hosts):
    """Nếu hostname resolve ra CẢ private lẫn public → fail closed."""
    resolve_hosts("10.0.0.5", _PUBLIC_IP)
    with pytest.raises(EgressError):
        resolve_private_host("http://rebind.example/v1")


def test_unresolvable_host_rejected(monkeypatch):
    def _raise(*_a, **_k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr("app.core.egress.socket.getaddrinfo", _raise)
    with pytest.raises(EgressError):
        resolve_private_host("http://does-not-exist.example/v1")


def test_bad_scheme_rejected():
    with pytest.raises(EgressError):
        resolve_private_host("ftp://10.0.0.5/v1")


def test_error_message_carries_category():
    with pytest.raises(EgressError) as exc:
        assert_llm_egress(f"http://{_PUBLIC_IP}/v1", allow_cloud=False)
    assert f"[{EGRESS_CATEGORY}]" in str(exc.value)


# ── Redirect ──


def test_redirect_to_public_rejected(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        assert_redirect_allowed(
            "http://10.0.0.5:11434/v1/models", "https://api.openai.com/v1/models", False
        )


def test_relative_redirect_on_private_host_allowed():
    # đường dẫn tương đối → giữ nguyên host private
    assert_redirect_allowed("http://10.0.0.5:11434/v1/models", "/v1/other", False)


def test_redirect_to_public_allowed_when_cloud_on(resolve_hosts):
    resolve_hosts(_PUBLIC_IP)
    assert_redirect_allowed(
        "http://10.0.0.5/v1", "https://api.openai.com/v1", allow_cloud=True
    )


# ── Helpers ghim kết nối ──


def test_pinned_base_url_replaces_host_keeps_scheme_port_path():
    assert (
        pinned_base_url("https://llm.internal:8443/v1", "10.0.0.5")
        == "https://10.0.0.5:8443/v1"
    )


def test_pinned_base_url_brackets_ipv6():
    assert pinned_base_url("http://[::1]:11434/v1", "::1") == "http://[::1]:11434/v1"


def test_host_header_keeps_original_host_and_port():
    assert host_header("https://llm.internal:8443/v1") == "llm.internal:8443"
    assert host_header("http://llm.internal/v1") == "llm.internal"


def test_host_header_brackets_ipv6():
    assert host_header("http://[fd00::1]:11434/v1") == "[fd00::1]:11434"


# ── Wiring: LlmClient thực sự validate + ghim ──


def test_llm_client_rejects_public_base_url(resolve_hosts):
    from app.services.llm import LlmClient

    resolve_hosts(_PUBLIC_IP)
    with pytest.raises(EgressError):
        LlmClient("https://api.openai.com/v1", "k", "m")


def test_llm_client_rejects_unresolvable_base_url(monkeypatch):
    from app.services.llm import LlmClient

    def _raise(*_a, **_k):
        raise socket.gaierror("nope")

    monkeypatch.setattr("app.core.egress.socket.getaddrinfo", _raise)
    with pytest.raises(EgressError):
        LlmClient("http://llm.internal/v1", "k", "m")


def test_llm_client_pins_ip_and_preserves_host(resolve_hosts):
    from app.services.llm import LlmClient

    resolve_hosts("10.1.2.3")
    c = LlmClient("http://llm.internal:11434/v1", "k", "m")
    assert c._pinned_ip == "10.1.2.3"
    assert c._pinned_base_url == "http://10.1.2.3:11434/v1"
    assert c._host_header == "llm.internal:11434"
    assert c._sni_hostname == "llm.internal"
    assert c._request_extensions() == {"sni_hostname": "llm.internal"}


def test_llm_client_allows_public_when_cloud_on(resolve_hosts):
    from app.services.llm import LlmClient

    resolve_hosts(_PUBLIC_IP)
    c = LlmClient("https://api.openai.com/v1", "k", "m", allow_cloud=True)
    assert c._pinned_base_url == f"https://{_PUBLIC_IP}/v1"


def test_llm_client_redirect_guard_blocks_public(resolve_hosts):
    import httpx

    from app.services.llm import LlmClient

    resolve_hosts(_PUBLIC_IP)
    c = LlmClient("http://10.0.0.5:11434/v1", None, "m", allow_cloud=False)
    req = httpx.Request("GET", "http://10.0.0.5:11434/v1/models")
    resp = httpx.Response(
        302,
        headers={"location": "https://api.openai.com/v1/models"},
        request=req,
    )
    with pytest.raises(EgressError):
        c._guard_redirect(resp)


def test_llm_client_redirect_guard_allows_relative(resolve_hosts):
    import httpx

    from app.services.llm import LlmClient

    c = LlmClient("http://10.0.0.5:11434/v1", None, "m", allow_cloud=False)
    req = httpx.Request("GET", "http://10.0.0.5:11434/v1/models")
    resp = httpx.Response(307, headers={"location": "/v1/other"}, request=req)
    c._guard_redirect(resp)  # không raise
