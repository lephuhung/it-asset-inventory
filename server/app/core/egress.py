"""Egress validation cho endpoint LLM (và tool tương lai) — R7/V3-6.

Thay thế kiểm tra substring "host có vẻ nội bộ" bằng chuỗi chặt:
  parse URL (``urllib.parse``) → resolve host (``socket.getaddrinfo``) →
  phân loại IP (``ipaddress``) → chỉ chấp nhận loopback/private/link-local/CGNAT
  (IPv4 + IPv6). IP đã resolve được trả về để caller **ghim** (pin) khi kết nối,
  đóng lỗ hổng DNS-rebinding giữa lúc kiểm tra và lúc kết nối.

Bản sao tương đương chức năng nằm ở ``deepagent/deepagent/egress.py``: deepagent là
package/container RIÊNG (không import được ``server.app``). Khi sửa một bản, sửa cả hai.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse, urlunparse

logger = logging.getLogger("egress")

#: Danh mục lỗi dùng chung với taxonomy của Chat Assistant (spec §Error taxonomy).
EGRESS_CATEGORY = "chat_upstream_llm"

#: CGNAT (RFC 6598) — ``is_private`` KHÔNG bao phủ dải này, phải kiểm tra tay.
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

    Từ chối (``EgressError``) nếu **bất kỳ** IP phân giải được là public và
    ``allow_cloud=False``. ``allow_cloud=True`` bỏ qua kiểm tra nhưng vẫn ghi log
    host public (spec: "bypass but still records it").
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
    """Chặn redirect sang host public (R7: "cấm redirect sang public").

    ``location`` có thể là URL tuyệt đối hoặc đường dẫn tương đối; resolve theo
    ``request_url`` rồi áp cùng policy egress.
    """
    try:
        target = urljoin(request_url, location)
    except ValueError as exc:
        raise EgressError(
            f"[{EGRESS_CATEGORY}] redirect URL không hợp lệ: {location!r} ({exc})"
        ) from exc
    resolve_private_host(target, allow_cloud=allow_cloud)


def pinned_base_url(url: str, pinned_ip: str) -> str:
    """URL dùng để KẾT NỐI: thay host bằng IP đã ghim (giữ scheme/port/path).

    Host gốc vẫn phải được gửi qua ``Host`` header + ``sni_hostname`` để TLS/virtual
    host đúng (xem :func:`host_header`). IPv6 được bọc ``[]``.
    """
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
    """Hostname gốc (không port/bracket) cho ``sni_hostname`` extension của TLS.

    Cần thiết để chứng chỉ TLS vẫn khớp hostname khi URL kết nối đã bị đổi sang IP.
    """
    return urlparse(url).hostname or ""


__all__ = [
    "EGRESS_CATEGORY",
    "EgressError",
    "assert_llm_egress",
    "assert_redirect_allowed",
    "host_header",
    "pinned_base_url",
    "resolve_private_host",
    "sni_hostname",
]
