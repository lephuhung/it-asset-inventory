"""Unit tests — trích xuất IP thật của client qua proxy chain (client_ip.py).

Bối cảnh: audit log trước đây ghi nhầm IP gateway Docker (172.22.0.1) thay vì
IP user thật vì:
1. `_parse_xff` cũ bỏ qua mọi IP private rồi lấy phần tử CUỐI (ngược chuẩn XFF)
   → mạng LAN thuần bị ghi IP proxy.
2. Portal BFF forward mù nguyên header XFF do client tự gửi (spoof được).

Các test dưới đây khoá hành vi đúng.
"""
from __future__ import annotations

import ipaddress

import pytest

from app.core.client_ip import (
    _normalize,
    _parse_trusted,
    _parse_xff,
    _peer_is_trusted,
    get_client_ip,
    reset_trusted_cache,
)


# ── _parse_xff ───────────────────────────────────────────────────


class TestParseXff:
    def test_single_private_ip_lan_client(self):
        """Client LAN thuần: XFF chỉ có 1 IP private → phải trả về IP đó (leftmost).

        Phiên bản cũ trả về None/sai vì skip private rồi rơi vào nhánh cuối.
        """
        assert _parse_xff("10.8.0.8") == "10.8.0.8"

    def test_lan_client_behind_gateway(self):
        """Client LAN 10.8.0.8 → gateway 172.22.0.1 → backend.

        Duyệt phải→trái: 172.22.0.1 là trusted hop (private) → skip;
        10.8.0.8 cũng private nhưng là leftmost → fallback leftmost.
        """
        assert _parse_xff("10.8.0.8, 172.22.0.1") == "10.8.0.8"

    def test_public_client_behind_proxies(self):
        """Client public đằng sau 2 proxy private → leftmost public (chuẩn XFF)."""
        assert _parse_xff("203.0.113.77, 10.0.0.5, 172.22.0.1") == "203.0.113.77"

    def test_all_private_leftmost_wins(self):
        """Toàn bộ private (LAN thuần nhiều hop) → leftmost = client gốc."""
        assert _parse_xff("192.168.1.50, 10.10.0.241, 172.22.0.1") == "192.168.1.50"

    def test_empty_and_garbage(self):
        assert _parse_xff("") is None
        assert _parse_xff("   ") is None
        assert _parse_xff("not-an-ip") == "not-an-ip"  # raw passthrough

    def test_rightmost_untrusted_wins_over_left_spoof(self):
        """Client public thật + attacker spoof thêm IP public phía trước.

        Chuỗi: 'spoofed(1.2.3.4), client-thật(203.0.113.77), hop-trusted(10.8.0.8),
        nginx(172.22.0.1)'. Duyệt phải→trái: bỏ 2 hop trusted (10.8.0.8, 172.22.0.1)
        → phần tử không-trusted đầu tiên là 203.0.113.77 (client thật mà proxy
        tin cậy gần nhất nhìn thấy), KHÔNG phải 1.2.3.4 (spoof trước client).
        """
        assert (
            _parse_xff("1.2.3.4, 203.0.113.77, 10.8.0.8, 172.22.0.1")
            == "203.0.113.77"
        )


# ── _normalize / _peer_is_trusted ────────────────────────────────


class TestNormalize:
    def test_mapped_ipv6_to_ipv4(self):
        assert _normalize("::ffff:10.8.0.8") == "10.8.0.8"
        assert _normalize("::ffff:172.22.0.1") == "172.22.0.1"

    def test_ipv4_with_port(self):
        assert _normalize("10.8.0.8:5678") == "10.8.0.8"

    def test_zone_stripped(self):
        assert _normalize("fe80::1%eth0") == "fe80::1"

    def test_plain(self):
        assert _normalize("203.0.113.77") == "203.0.113.77"
        assert _normalize("") == ""


class TestPeerIsTrusted:
    def test_private_ranges(self):
        assert _peer_is_trusted("172.22.0.1")
        assert _peer_is_trusted("10.10.0.241")
        assert _peer_is_trusted("192.168.1.1")
        assert _peer_is_trusted("127.0.0.1")

    def test_mapped_ipv6_private(self):
        """Peer dạng ::ffff:172.22.0.1 vẫn phải được tính là trusted."""
        assert _peer_is_trusted("::ffff:172.22.0.1")

    def test_public_not_trusted(self):
        assert not _peer_is_trusted("203.0.113.77")
        assert not _peer_is_trusted("8.8.8.8")

    def test_garbage(self):
        assert not _peer_is_trusted("")
        assert not _peer_is_trusted("not-an-ip")
        assert not _peer_is_trusted(None)  # type: ignore[arg-type]


# ── get_client_ip (tích hợp với fake Request) ────────────────────


class _FakeClient:
    def __init__(self, host: str | None):
        self.host = host


class _FakeRequest:
    """Đủ interface FastAPI Request mà get_client_ip dùng (client, headers)."""

    def __init__(self, peer: str | None, headers: dict[str, str] | None = None):
        self.client = _FakeClient(peer) if peer is not None else None
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}

    def get(self, key: str, default=None):
        return self.headers.get(key.lower(), default)


class TestGetClientIp:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_trusted_cache()
        yield
        reset_trusted_cache()

    def test_direct_client_no_proxy(self):
        """Client kết nối thẳng (peer = client) → dùng peer."""
        req = _FakeRequest("10.8.0.8")
        assert get_client_ip(req) == "10.8.0.8"  # type: ignore[arg-type]

    def test_direct_client_spoofed_xff_ignored(self):
        """Peer là client (vẫn private → 'trusted' theo CIDR mặc định) nhưng
        XFF do chính client tự nhét — trong deploy thật portal BFF rebuild
        header, còn ở đây kiểm tra peer public thì header bị bỏ qua."""
        req = _FakeRequest("203.0.113.10", {"X-Forwarded-For": "6.6.6.6"})
        assert get_client_ip(req) == "203.0.113.10"  # type: ignore[arg-type]

    def test_via_trusted_proxy_xff(self):
        """Peer là portal (172.22.0.5, trusted) + XFF do BFF rebuild."""
        req = _FakeRequest(
            "172.22.0.5", {"X-Forwarded-For": "10.8.0.8"}
        )
        assert get_client_ip(req) == "10.8.0.8"  # type: ignore[arg-type]

    def test_via_trusted_proxy_xff_mapped_peer(self):
        """Peer dạng mapped IPv6 (::ffff:...) vẫn trusted."""
        req = _FakeRequest(
            "::ffff:172.22.0.5", {"X-Forwarded-For": "10.8.0.8"}
        )
        assert get_client_ip(req) == "10.8.0.8"  # type: ignore[arg-type]

    def test_no_peer_no_ip(self):
        req = _FakeRequest(None)
        assert get_client_ip(req) is None  # type: ignore[arg-type]

    def test_no_client_object(self):
        req = _FakeRequest.__new__(_FakeRequest)
        req.client = None
        req.headers = {}
        assert get_client_ip(req) is None  # type: ignore[arg-type]


# ── Trusted CIDRs config ─────────────────────────────────────────


class TestParseTrusted:
    def test_default_contains_private_ranges(self):
        reset_trusted_cache()
        nets = _parse_trusted()
        assert ipaddress.ip_network("172.16.0.0/12") is not None
        assert any(ipaddress.ip_address("172.22.0.1") in n for n in nets)
        assert any(ipaddress.ip_address("10.8.0.8") in n for n in nets)
