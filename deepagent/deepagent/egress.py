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
from urllib.parse import urljoin, urlparse, urlunparse

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


def resolve_private_host(url: str, *, allow_cloud: bool = False) -> tuple[str, str]:
    """Phân giải ``url`` và trả ``(host, pinned_ip)``.

    Từ chối (``EgressError``) nếu bất kỳ IP phân giải được là public và
    ``allow_cloud=False``.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise EgressError(f"[{EGRESS_CATEGORY}] scheme không hợp lệ: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise EgressError(f"[{EGRESS_CATEGORY}] URL thiếu host: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
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
    target = urljoin(request_url, location)
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
