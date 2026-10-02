"""Egress validation cho endpoint LLM của DeepAgent — R7/V3-6.

Bản sao tương đương chức năng của ``server/app/core/egress.py``. DeepAgent là
package/container RIÊNG (Dockerfile chỉ COPY ``deepagent/``, không có ``server``),
nên KHÔNG thể import bản canonical. Khi sửa logic ở một bản, sửa cả hai để giữ parity.

Chuỗi kiểm tra: parse URL → resolve host (``socket.getaddrinfo``) → phân loại IP
(``ipaddress``) → chỉ chấp nhận loopback/private/link-local/CGNAT (IPv4 + IPv6).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

logger = logging.getLogger("egress")

EGRESS_CATEGORY = "chat_upstream_llm"

_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")


class EgressError(ValueError):
    """Endpoint không thoả policy egress. Message mang prefix ``[chat_upstream_llm]``."""


def _is_allowed_ip(ip: str) -> bool:
    """True nếu IP thuộc loopback / private / link-local / CGNAT (IPv4 + IPv6)."""
    addr = ipaddress.ip_address(ip)
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return True
    return isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT_V4


def _resolve_addresses(host: str, port: int) -> list[str]:
    """Danh sách IP (đã khử trùng) của ``host``. IP literal không cần DNS."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressError(
            f"[{EGRESS_CATEGORY}] không phân giải được host {host}: {exc}"
        ) from exc
    addrs: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in addrs:
            addrs.append(ip)
    if not addrs:
        raise EgressError(f"[{EGRESS_CATEGORY}] host {host} không có địa chỉ IP")
    return addrs


def _parse_http_url(url: str) -> tuple[str, str]:
    """Parse ``url`` thành ``(host, port)``; mọi lỗi parse → ``EgressError``.

    ``urlparse`` và ``parsed.port`` có thể ném ``ValueError`` (IPv6 thiếu ``]``,
    port không phải số, port ngoài 0–65535) hoặc ``AttributeError``. Các lỗi này
    phải đi qua taxonomy ``[chat_upstream_llm]`` thay vì rò rỉ exception thô.
    """
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
    except (ValueError, AttributeError) as exc:
        raise EgressError(
            f"[{EGRESS_CATEGORY}] URL không hợp lệ: {url!r} ({exc})"
        ) from exc
    if scheme not in ("http", "https"):
        raise EgressError(f"[{EGRESS_CATEGORY}] scheme không hợp lệ: {scheme!r}")
    if not host:
        raise EgressError(f"[{EGRESS_CATEGORY}] URL thiếu host: {url!r}")
    return host, port


def resolve_private_host(url: str, *, allow_cloud: bool = False) -> tuple[str, str]:
    """Phân giải ``url`` và trả ``(host, pinned_ip)``.

    Từ chối (``EgressError``) nếu bất kỳ IP phân giải được là public và
    ``allow_cloud=False``.
    """
    host, port = _parse_http_url(url)
    addrs = _resolve_addresses(host, port)
    public = [addr for addr in addrs if not _is_allowed_ip(addr)]
    if public and not allow_cloud:
        raise EgressError(
            f"[{EGRESS_CATEGORY}] host {host} phân giải tới IP công khai {public}; "
            "allow_cloud=false — từ chối egress"
        )
    if public:
        logger.warning("egress allow_cloud: host=%s public_ips=%s", host, public)
    return host, addrs[0]


def assert_llm_egress(base_url: str, allow_cloud: bool) -> str:
    """Xác thực endpoint LLM; trả IP đã ghim để caller dùng khi kết nối."""
    _host, pinned = resolve_private_host(base_url, allow_cloud=allow_cloud)
    return pinned


def assert_redirect_allowed(request_url: str, location: str, allow_cloud: bool) -> None:
    """Chặn redirect sang host public (R7: "cấm redirect sang public")."""
    try:
        target = urljoin(request_url, location)
    except ValueError as exc:
        raise EgressError(
            f"[{EGRESS_CATEGORY}] redirect URL không hợp lệ: {location!r} ({exc})"
        ) from exc
    resolve_private_host(target, allow_cloud=allow_cloud)


def pinned_base_url(url: str, pinned_ip: str) -> str:
    """URL dùng để KẾT NỐI: thay host bằng IP đã ghim (giữ scheme/port/path)."""
    parsed = urlparse(url)
    host_part = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    netloc = f"{host_part}:{parsed.port}" if parsed.port else host_part
    return urlunparse(parsed._replace(netloc=netloc))


def host_header(url: str) -> str:
    """Giá trị ``Host`` header gốc (``host[:port]``) — giữ virtual-host khi URL đã đổi sang IP."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    host_part = f"[{host}]" if ":" in host else host
    return f"{host_part}:{parsed.port}" if parsed.port else host_part


def sni_hostname(url: str) -> str:
    """Hostname gốc (không port/bracket) cho ``sni_hostname`` extension của TLS."""
    return urlparse(url).hostname or ""


# ── Ghim IP ở tầng transport (chống DNS rebinding khi kết nối) ──────
#
# ``resolve_private_host`` chỉ xác thực tại thời điểm gọi. Nếu client kết nối lại
# bằng hostname, DNS có thể đổi sang IP public giữa lúc validate và lúc connect
# (rebinding). Transport dưới đây viết lại host của MỌI request thành IP đã ghim,
# nên không còn tra DNS ở thời điểm kết nối; ``Host`` header + ``sni_hostname`` giữ
# nguyên hostname gốc để virtual-host và TLS SNI vẫn đúng.


class _PinnedTransportMixin:
    """Viết lại request trỏ tới IP đã ghim; giữ Host header + TLS SNI."""

    _pinned_ip: str
    _sni_hostname: str

    def _pin_request(self, request: httpx.Request) -> None:
        # Giữ Host header gốc (kể cả khi caller đã đặt sẵn), fallback netloc gốc.
        host_header = request.headers.get("host") or request.url.netloc
        request.url = request.url.copy_with(host=self._pinned_ip)
        request.headers["host"] = host_header
        request.extensions["sni_hostname"] = self._sni_hostname


class PinnedHTTPTransport(_PinnedTransportMixin, httpx.HTTPTransport):
    """``httpx.HTTPTransport`` ghim IP; mặc định tắt đọc proxy từ env."""

    def __init__(self, pinned_ip: str, sni_hostname: str, **kwargs) -> None:
        self._pinned_ip = pinned_ip
        self._sni_hostname = sni_hostname
        kwargs.setdefault("trust_env", False)
        super().__init__(**kwargs)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._pin_request(request)
        return super().handle_request(request)


class PinnedAsyncHTTPTransport(_PinnedTransportMixin, httpx.AsyncHTTPTransport):
    """``httpx.AsyncHTTPTransport`` ghim IP; mặc định tắt đọc proxy từ env."""

    def __init__(self, pinned_ip: str, sni_hostname: str, **kwargs) -> None:
        self._pinned_ip = pinned_ip
        self._sni_hostname = sni_hostname
        kwargs.setdefault("trust_env", False)
        super().__init__(**kwargs)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._pin_request(request)
        return await super().handle_async_request(request)


def build_pinned_sync_client(
    base_url: str,
    pinned_ip: str,
    *,
    verify: bool | str | ssl.SSLContext = True,
    timeout: float | httpx.Timeout | None = None,
    follow_redirects: bool = False,
) -> httpx.Client:
    """``httpx.Client`` kết nối tới ``pinned_ip``; Host/SNI giữ hostname gốc."""
    sni = sni_hostname(base_url)
    transport = PinnedHTTPTransport(pinned_ip, sni, verify=verify)
    return httpx.Client(
        transport=transport,
        timeout=timeout if timeout is not None else httpx.Timeout(180.0, connect=10.0),
        follow_redirects=follow_redirects,
        trust_env=False,
    )


def build_pinned_async_client(
    base_url: str,
    pinned_ip: str,
    *,
    verify: bool | str | ssl.SSLContext = True,
    timeout: float | httpx.Timeout | None = None,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """``httpx.AsyncClient`` kết nối tới ``pinned_ip``; Host/SNI giữ hostname gốc."""
    sni = sni_hostname(base_url)
    transport = PinnedAsyncHTTPTransport(pinned_ip, sni, verify=verify)
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout if timeout is not None else httpx.Timeout(180.0, connect=10.0),
        follow_redirects=follow_redirects,
        trust_env=False,
    )


__all__ = [
    "EGRESS_CATEGORY",
    "EgressError",
    "PinnedAsyncHTTPTransport",
    "PinnedHTTPTransport",
    "assert_llm_egress",
    "assert_redirect_allowed",
    "build_pinned_async_client",
    "build_pinned_sync_client",
    "host_header",
    "pinned_base_url",
    "resolve_private_host",
    "sni_hostname",
]
