"""Tests cho `app.core.egress` — private-host validation (R7/V3-6).

Dùng monkeypatch `socket.getaddrinfo` để kiểm tra phân loại IP tất định (không phụ
thuộc DNS thật); các test IP literal không cần DNS.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import socket
import threading
from typing import ClassVar

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


# ── URL dị dạng → EgressError có category (không rò ValueError thô) ──


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1/v1",  # IPv6 thiếu ] — urlparse ném ValueError
        "http://10.0.0.5:bad/v1",  # port không phải số
        "http://10.0.0.5:65536/v1",  # port ngoài 0–65535
        "http://[::1]:99999/v1",
    ],
)
def test_malformed_url_raises_categorized_egress_error(url):
    with pytest.raises(EgressError) as exc:
        resolve_private_host(url)
    assert f"[{EGRESS_CATEGORY}]" in str(exc.value)


def test_malformed_redirect_location_raises_categorized_egress_error():
    with pytest.raises(EgressError) as exc:
        assert_redirect_allowed("http://10.0.0.5/v1", "http://[::1/v1", False)
    assert f"[{EGRESS_CATEGORY}]" in str(exc.value)


def test_malformed_url_in_llm_client_raises_egress_error():
    from app.services.llm import LlmClient

    with pytest.raises(EgressError):
        LlmClient("http://10.0.0.5:bad/v1", "k", "m")


# ── Thực thi ở tầng transport: client không đọc proxy env, không theo redirect ──


async def _client_settings(base_url="http://10.0.0.5:11434/v1", **kwargs):
    from app.services.llm import LlmClient

    llm = LlmClient(base_url, "k", "m", **kwargs)
    async with llm:
        return {
            "trust_env": llm._client.trust_env,
            "follow_redirects": llm._client.follow_redirects,
        }


def test_llm_client_disables_env_proxy_and_redirect_following():
    s = asyncio.run(_client_settings())
    assert s["trust_env"] is False
    assert s["follow_redirects"] is False


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    """Server nội bộ: ghi lại Host + path, trả JSON OpenAI-compatible cho /models."""

    requests: ClassVar[list[dict]] = []

    def _record(self):
        type(self).requests.append(
            {"path": self.path, "host": self.headers.get("Host")}
        )

    def do_GET(self):
        self._record()
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "local-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_a):  # im lặng
        pass


@pytest.fixture
def local_http_server():
    handler = type("Handler", (_RecordingHandler,), {"requests": []})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, port, handler.requests
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_llm_client_pins_ip_against_dns_rebinding(local_http_server, monkeypatch):
    """Sau khi validate, DNS đổi sang IP public — request vẫn tới IP đã ghim."""
    from app.services.llm import LlmClient

    _srv, port, requests = local_http_server
    real_gai = socket.getaddrinfo

    def _private(host, port_, *a, **k):
        if host == "llm.internal":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_))]
        return real_gai(host, port_, *a, **k)

    monkeypatch.setattr("app.core.egress.socket.getaddrinfo", _private)
    llm = LlmClient(f"http://llm.internal:{port}/v1", "k", "m")

    # DNS đổi hướng công khai SAU khi validate/ghim.
    def _public(host, port_, *a, **k):
        if host == "llm.internal":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port_))]
        return real_gai(host, port_, *a, **k)

    monkeypatch.setattr("app.core.egress.socket.getaddrinfo", _public)

    async def _call():
        async with llm:
            return await llm.list_models()

    assert asyncio.run(_call()) == ["local-model"]
    assert requests and requests[0]["host"] == f"llm.internal:{port}"
    assert requests[0]["path"].endswith("/models")


def test_llm_client_ignores_environment_proxy(local_http_server, monkeypatch):
    """HTTP_PROXY/ALL_PROXY trong env không được nhận request (trust_env=False)."""
    from app.services.llm import LlmClient

    # NO_PROXY/no_proxy kế thừa có thể MIỄN trừ loopback khỏi proxy → test pass
    # giả dù trust_env bị bật lại. Xoá trước để phép đo cô lập.
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    _srv, port, requests = local_http_server
    proxy_hits: list[str] = []

    class _ProxyHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            proxy_hits.append(self.path)
            self.send_response(502)
            self.end_headers()

        def do_CONNECT(self):
            proxy_hits.append("CONNECT " + self.path)
            self.send_response(502)
            self.end_headers()

        def log_message(self, *_a):
            pass

    proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
    proxy_port = proxy.server_address[1]
    pthread = threading.Thread(target=proxy.serve_forever, daemon=True)
    pthread.start()
    monkeypatch.setenv("ALL_PROXY", f"http://127.0.0.1:{proxy_port}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy_port}")
    try:
        llm = LlmClient(f"http://127.0.0.1:{port}/v1", "k", "m")

        async def _call():
            async with llm:
                return await llm.list_models()

        assert asyncio.run(_call()) == ["local-model"]
        assert proxy_hits == []
        assert requests and requests[0]["host"] == f"127.0.0.1:{port}"
    finally:
        proxy.shutdown()
        proxy.server_close()
        pthread.join(timeout=2)


def test_llm_client_does_not_follow_redirect(local_http_server, monkeypatch):
    """3xx tới host public: client không tự đi theo (follow_redirects=False)."""
    from app.services.llm import LlmClient

    # Ghim DNS của api.openai.com về IP public biết trước: test chỉ còn raise khi
    # guard redirect chặn host public, KHÔNG phụ thuộc DNS thật (DNS lỗi cũng sẽ
    # ném EgressError và làm test pass nhầm).
    monkeypatch.setattr(
        "app.core.egress.socket.getaddrinfo",
        lambda host, port_, *a, **k: _addr_infos(_PUBLIC_IP),
    )

    srv, port, _requests = local_http_server
    # Server tạm trả 302 sang public cho mọi request.
    srv.RequestHandlerClass.do_GET = lambda self: (
        self.send_response(302),
        self.send_header("Location", "https://api.openai.com/v1/models"),
        self.end_headers(),
    )

    llm = LlmClient(f"http://127.0.0.1:{port}/v1", "k", "m", allow_cloud=False)

    async def _call():
        async with llm:
            return await llm.list_models()

    # Không follow → response 302 chạm hook redirect và bị chặn (EgressError).
    with pytest.raises(EgressError):
        asyncio.run(_call())
