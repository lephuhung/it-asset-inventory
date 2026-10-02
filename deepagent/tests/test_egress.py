"""Tests cho `deepagent.egress` — private-host validation (R7/V3-6).

Bản sao của `server/tests/test_egress.py` cho package deepagent (container riêng).
Dùng monkeypatch `socket.getaddrinfo` để tất định, không phụ thuộc DNS thật.
"""
from __future__ import annotations

import asyncio
import datetime
import http.server
import json
import socket
import ssl
import threading
from typing import ClassVar

import pytest

from deepagent.egress import (
    EGRESS_CATEGORY,
    EgressError,
    assert_llm_egress,
    assert_redirect_allowed,
    build_pinned_async_client,
    build_pinned_sync_client,
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


# ── URL dị dạng → EgressError có category ──


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1/v1",
        "http://10.0.0.5:bad/v1",
        "http://10.0.0.5:65536/v1",
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


# ── Ghim IP ở tầng transport (thực thi, không chỉ thuộc tính) ──


class _JsonHandler(http.server.BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []

    def do_GET(self):
        type(self).requests.append({"path": self.path, "host": self.headers.get("Host")})
        body = json.dumps({"data": [{"id": "local-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


class _RedirectHandler(_JsonHandler):
    def do_GET(self):
        type(self).requests.append({"path": self.path, "host": self.headers.get("Host")})
        self.send_response(302)
        self.send_header("Location", "https://api.openai.com/v1/models")
        self.end_headers()


def _serve(handler_cls, *, tls=None):
    handler = type("Handler", (handler_cls,), {"requests": []})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if tls is not None:
        cert_path, key_path = tls
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, port, handler.requests, thread


def _stop(srv, thread):
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=2)


def _self_signed_cert(tmp_path, hostname="llm.internal"):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


def test_build_pinned_clients_disable_proxy_env_and_redirects():
    sync = build_pinned_sync_client("http://llm.internal:11434/v1", "10.0.0.5")
    asyn = build_pinned_async_client("http://llm.internal:11434/v1", "10.0.0.5")
    assert sync.trust_env is False and sync.follow_redirects is False
    assert asyn.trust_env is False and asyn.follow_redirects is False
    sync.close()
    asyncio.run(asyn.aclose())


def test_pinned_async_client_survives_dns_rebinding(monkeypatch):
    srv, port, requests, thread = _serve(_JsonHandler)
    real_gai = socket.getaddrinfo

    def _private(host, port_, *a, **k):
        if host == "llm.internal":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_))]
        return real_gai(host, port_, *a, **k)

    monkeypatch.setattr("deepagent.egress.socket.getaddrinfo", _private)
    client = build_pinned_async_client(f"http://llm.internal:{port}", "127.0.0.1")

    def _public(host, port_, *a, **k):
        if host == "llm.internal":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port_))]
        return real_gai(host, port_, *a, **k)

    monkeypatch.setattr("deepagent.egress.socket.getaddrinfo", _public)

    async def _go():
        r = await client.get(f"http://llm.internal:{port}/models")
        await client.aclose()
        return r

    r = asyncio.run(_go())
    assert r.status_code == 200
    assert requests and requests[0]["host"] == f"llm.internal:{port}"
    _stop(srv, thread)


def test_pinned_async_client_preserves_sni_over_tls(monkeypatch, tmp_path):
    cert_path, key_path = _self_signed_cert(tmp_path)
    srv, port, requests, thread = _serve(_JsonHandler, tls=(cert_path, key_path))
    real_gai = socket.getaddrinfo

    def _private(host, port_, *a, **k):
        if host == "llm.internal":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_))]
        return real_gai(host, port_, *a, **k)

    monkeypatch.setattr("deepagent.egress.socket.getaddrinfo", _private)
    ctx = ssl.create_default_context(cafile=cert_path)
    client = build_pinned_async_client(
        f"https://llm.internal:{port}", "127.0.0.1", verify=ctx
    )

    async def _go():
        r = await client.get(f"https://llm.internal:{port}/models")
        await client.aclose()
        return r

    # TLS verify chỉ thành công nếu SNI/hostname = llm.internal (không phải IP).
    r = asyncio.run(_go())
    assert r.status_code == 200 and requests
    _stop(srv, thread)


def test_pinned_async_client_does_not_follow_public_redirect(monkeypatch):
    srv, port, requests, thread = _serve(_RedirectHandler)
    monkeypatch.setattr(
        "deepagent.egress.socket.getaddrinfo",
        lambda host, port_, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_))
        ],
    )
    client = build_pinned_async_client(f"http://llm.internal:{port}", "127.0.0.1")

    async def _go():
        r = await client.get(f"http://llm.internal:{port}/models")
        await client.aclose()
        return r

    r = asyncio.run(_go())
    assert r.status_code == 302  # không đi theo
    assert len(requests) == 1
    _stop(srv, thread)


def test_pinned_async_client_ignores_environment_proxy(monkeypatch):
    # NO_PROXY/no_proxy kế thừa từ môi trường có thể MIỄN trừ loopback khỏi proxy,
    # khiến test pass dù trust_env bị bật lại. Xoá trước để phép đo cô lập.
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    srv, port, requests, thread = _serve(_JsonHandler)
    proxy_hits: list[str] = []

    class _Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            proxy_hits.append(self.path)
            self.send_response(502)
            self.end_headers()

        def log_message(self, *_a):
            pass

    proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
    proxy_port = proxy.server_address[1]
    pthread = threading.Thread(target=proxy.serve_forever, daemon=True)
    pthread.start()
    monkeypatch.setenv("ALL_PROXY", f"http://127.0.0.1:{proxy_port}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy_port}")
    client = build_pinned_async_client(f"http://127.0.0.1:{port}", "127.0.0.1")

    async def _go():
        r = await client.get(f"http://127.0.0.1:{port}/models")
        await client.aclose()
        return r

    r = asyncio.run(_go())
    assert r.status_code == 200 and proxy_hits == [] and requests
    proxy.shutdown()
    proxy.server_close()
    pthread.join(timeout=2)
    _stop(srv, thread)


# ── Wiring: ChatOpenAI dùng đúng client đã ghim ──


def test_openai_analysis_model_uses_pinned_transport():
    from deepagent.analysis_model import OpenAIAnalysisModel
    from deepagent.models import LlmRuntime

    runtime = LlmRuntime(base_url="http://127.0.0.1:11434/v1", api_key="k", model="m")
    model = OpenAIAnalysisModel(runtime)
    rc = model._model.root_async_client
    assert rc._client is model._async_client
    assert rc._client.trust_env is False
    assert rc._client.follow_redirects is False
    assert model._async_client._transport.__class__.__name__ == "PinnedAsyncHTTPTransport"


def test_openai_analysis_model_client_reaches_validated_host():
    from deepagent.analysis_model import OpenAIAnalysisModel
    from deepagent.models import LlmRuntime

    srv, port, requests, thread = _serve(_JsonHandler)
    runtime = LlmRuntime(base_url=f"http://127.0.0.1:{port}/v1", api_key="k", model="m")
    model = OpenAIAnalysisModel(runtime)

    async def _go():
        try:
            page = await model._model.root_async_client.models.list()
            return [m.id for m in page.data]
        finally:
            await model._async_client.aclose()

    assert asyncio.run(_go()) == ["local-model"]
    assert requests and requests[0]["host"] == f"127.0.0.1:{port}"
    _stop(srv, thread)
