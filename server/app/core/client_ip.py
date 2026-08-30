"""Helper trích xuất IP thật của client qua proxy chain.

Vấn đề: Khi portal BFF (Next.js) hoặc nginx đứng trước FastAPI, request.client.host
luôn trả về IP của proxy (127.0.0.1 / 10.10.0.241) thay vì IP user thật.

Giải pháp chuẩn:
- Portal/nginx forward `X-Forwarded-For: <original>, <proxy1>, <proxy2>, ...`
  (leftmost = IP gốc của user).
- Backend đọc header này, nhưng CHỈ TIN nếu peer (request.client.host) là trusted proxy
  (portal BFF, nginx trong cùng mạng). Nếu peer không phải trusted → bỏ qua header,
  dùng peer IP — tránh attacker spoof IP qua header giả.

Trusted proxies cấu hình qua env `TRUSTED_PROXY_CIDRS` (CSV, default: 127.0.0.0/8,
::1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7 — tức các dải private/loopback).
"""
from __future__ import annotations

import ipaddress
from typing import Iterable

from fastapi import Request

from app.core.config import settings

_TRUSTED_PROXIES: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None


def _parse_trusted() -> list:
    """Parse TRUSTED_PROXY_CIDRS env thành list of IPNetwork. Cache lazy."""
    global _TRUSTED_PROXIES
    if _TRUSTED_PROXIES is not None:
        return _TRUSTED_PROXIES

    raw = getattr(settings, "trusted_proxy_cidrs", "") or ""
    nets: list = []
    for cidr in raw.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            # Log warning nhưng không fail
            pass

    # Fallback nếu config trống: cho phép các dải private + loopback (mặc định an toàn)
    if not nets:
        defaults = [
            "127.0.0.0/8",
            "::1/128",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fc00::/7",
        ]
        for cidr in defaults:
            try:
                nets.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass
    _TRUSTED_PROXIES = nets
    return nets


def reset_trusted_cache() -> None:
    """Test helper: ép reload config."""
    global _TRUSTED_PROXIES
    _TRUSTED_PROXIES = None


def _peer_is_trusted(peer_ip: str) -> bool:
    """Check xem peer IP có thuộc trusted proxy CIDRs không."""
    if not peer_ip:
        return False
    try:
        ip = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for net in _parse_trusted():
        if ip in net:
            return True
    return False


def _parse_xff(xff: str) -> str | None:
    """Lấy IP leftmost từ X-Forwarded-For (IP gốc của user, trước các proxy).

    Skip các giá trị rỗng / không parse được. Nếu chỉ có 1 IP và nó là trusted proxy
    → chính nó là peer (không có client trước đó).
    """
    if not xff:
        return None
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    for raw in parts:
        try:
            ip = ipaddress.ip_address(raw)
            # Bỏ qua private/loopback trong chain (proxy hop)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                continue
            return str(ip)
        except ValueError:
            continue
    # Nếu tất cả là private (vd: user trong cùng LAN), lấy cái leftmost
    try:
        return str(ipaddress.ip_address(parts[0]))
    except (ValueError, IndexError):
        return None


def _normalize(ip_str: str) -> str:
    """Chuẩn hoá IP string — bỏ port nếu có, bỏ zone IPv6, parse OK thì trả canonical."""
    if not ip_str:
        return ""
    # IPv6 with zone (fe80::1%eth0) — bỏ zone
    if "%" in ip_str:
        ip_str = ip_str.split("%")[0]
    # IPv4 with port (1.2.3.4:5678) — chỉ IPv4 mới có dạng này
    if ":" in ip_str and ip_str.count(":") == 1:
        ip_str = ip_str.split(":")[0]
    try:
        return str(ipaddress.ip_address(ip_str))
    except ValueError:
        return ip_str  # trả raw nếu không parse được


def get_client_ip(
    request: Request,
    *,
    _trusted_override: Iterable[str] | None = None,
) -> str | None:
    """Trả về IP thật của client, đã qua xác thực trusted proxy.

    Thứ tự ưu tiên:
      1. X-Forwarded-For (nếu peer trusted)
      2. X-Real-IP         (nếu peer trusted)
      3. request.client.host

    Trả về None nếu không xác định được.
    """
    peer = request.client.host if request.client else None
    peer_normalized = _normalize(peer) if peer else None

    # Nếu peer không phải trusted proxy → KHÔNG tin header (tránh spoof)
    is_trusted = peer_normalized and (
        _peer_is_trusted(peer_normalized)
        if _trusted_override is None
        else peer_normalized in (_trusted_override or [])
    )

    if is_trusted:
        # Ưu tiên X-Forwarded-For
        xff = request.headers.get("x-forwarded-for")
        if xff:
            real_ip = _parse_xff(xff)
            if real_ip:
                return _normalize(real_ip)
        # Fallback X-Real-IP
        xri = request.headers.get("x-real-ip")
        if xri:
            return _normalize(xri.strip())

    return _normalize(peer) if peer else None
