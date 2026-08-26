"""Chuẩn hóa payload inventory PHÍA SERVER — agent KHÔNG cần đổi.

Mọi payload agent v1/v2/v3 (docs/API_CONTRACT.md) vẫn được chấp nhận nguyên vẹn;
server sinh thêm các trường chuẩn hóa phục vụ thống kê:

- `os_product` / `os_release` / `os_family` — tách từ `os_name` (ProductName + DisplayVersion)
  và `os_version`. Lý do: `os_version` luôn là `10.0.<build>` cho CẢ Win10 lẫn Win11
  (cùng NT kernel) → không phân biệt được; chỉ `DisplayVersion`/`ProductName` mới phân biệt.
- security (JSONB) → cột phẳng có kiểu: `firewall_enabled`, `windows_update_enabled/status`,
  `antivirus_enabled/up_to_date`, `bitlocker`, `uac_enabled`, `secure_boot_enabled`…
- `installed_software` (JSONB) → danh sách dòng chuẩn cho bảng `machine_software`.
"""
from __future__ import annotations

import re

# DisplayVersion: "25H2", "22H2", "21H2"… (đuôi của os_name hoặc giá trị os_version)
_WIN_RELEASE_RE = re.compile(r"^(?P<release>\d{2}H\d)$", re.IGNORECASE)
_WIN_SERVER_RE = re.compile(r"windows server[^\d]*(\d{4})", re.IGNORECASE)

_LINUX_MARKERS = (
    "ubuntu", "debian", "linux", "centos", "rhel", "fedora", "arch", "alpine",
    "kali", "rocky", "suse", "oracle linux", "mint",
)

# Trạng thái windows_update_status cho thấy auto-update ĐANG bật / TẮT
_UPDATE_STATUS_ON = {"up-to-date", "up to date", "uptodate", "pending", "checking", "enabled", "on", "active"}
_UPDATE_STATUS_OFF = {"disabled", "off", "never", "paused", "stopped"}


def derive_os_fields(
    os_name: str | None,
    os_version: str | None,
    os_build: str | None,
) -> tuple[str | None, str | None, str]:
    r"""Tách (os_product, os_release, os_family) từ chuỗi agent gửi.

    - `os_product`: ProductName thuần ("Windows 11 Pro") — bỏ DisplayVersion ở đuôi.
    - `os_release`: DisplayVersion ("25H2") — token `\d{2}H\d` ở đuôi os_name, fallback os_version.
    - `os_family`:  nhóm chuẩn hóa để GROUP BY (windows_10 | windows_11 | windows_server_* | linux | other).
    """
    name = (os_name or "").strip()
    product: str | None = None
    release: str | None = None

    if name:
        tokens = name.split()
        if tokens and _WIN_RELEASE_RE.match(tokens[-1]):
            release = tokens[-1].upper()
            product = " ".join(tokens[:-1]).strip() or None
        else:
            product = name

    if not release and os_version:
        m = _WIN_RELEASE_RE.match(os_version.strip())
        if m:
            release = m.group("release").upper()

    return product, release, classify_os_family(product or name)


def classify_os_family(raw: str | None) -> str:
    """Phân loại OS → nhóm thống kê (xem bảng 4.4 trong docs/REFACTOR_SCHEMA_THONG_KE.md)."""
    t = (raw or "").lower()
    if not t:
        return "other"
    if "windows 11" in t:
        return "windows_11"
    if "windows 10" in t:
        return "windows_10"
    if "windows server" in t:
        m = _WIN_SERVER_RE.search(t)
        if m:
            return f"windows_server_{m.group(1)}"
        return "windows_server"
    if any(k in t for k in _LINUX_MARKERS):
        return "linux"
    return "other"


def derive_security_fields(security: dict | None) -> dict:
    """Ép JSONB `security` thành dict cột phẳng (kiểu rõ ràng) cho `machine_current`."""
    sec = security or {}

    antivirus = sec.get("antivirus") or []
    av_enabled: bool | None = None
    for av in antivirus:
        if not isinstance(av, dict):
            continue
        enabled = av.get("enabled")
        if enabled is None and av.get("status") is not None:
            enabled = av.get("status") == "enabled"
        if enabled is True:
            av_enabled = True
            break
        if enabled is False and av_enabled is None:
            av_enabled = False

    up_to_date_vals = [av.get("upToDate") for av in antivirus if isinstance(av, dict) and "upToDate" in av]
    av_up_to_date: bool | None = None
    if up_to_date_vals:
        av_up_to_date = all(v is True for v in up_to_date_vals)

    update_status = sec.get("windows_update_status")
    update_enabled: bool | None = None
    if isinstance(update_status, str) and update_status.strip():
        s = update_status.strip().lower()
        if s in _UPDATE_STATUS_ON:
            update_enabled = True
        elif s in _UPDATE_STATUS_OFF:
            update_enabled = False

    return {
        "antivirus": antivirus or None,
        "antivirus_enabled": av_enabled,
        "antivirus_up_to_date": av_up_to_date,
        "windows_update_status": update_status,
        "windows_update_enabled": update_enabled,
        "bitlocker": sec.get("bitlocker"),
        "firewall_enabled": sec.get("firewall_enabled"),
        "uac_enabled": sec.get("uac_enabled"),
        "secure_boot_enabled": sec.get("secure_boot_enabled"),
        "rdp_enabled": sec.get("rdp_enabled"),
        "usb_storage_blocked": sec.get("usb_storage_blocked"),
    }


def software_rows(installed_software: list | None) -> list[dict]:
    """`installed_software` (JSONB, alias v1/v2: display_name|name) → dòng chuẩn cho `machine_software`."""
    rows: list[dict] = []
    for item in installed_software or []:
        if not isinstance(item, dict):
            continue
        name = (item.get("display_name") or item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "version": item.get("version"),
                "publisher": item.get("publisher"),
                "install_date": item.get("install_date"),
            }
        )
    return rows
