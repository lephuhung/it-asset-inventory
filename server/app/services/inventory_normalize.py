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


def derive_platform_fields(agent_meta: dict | None, os_meta: dict | None) -> tuple[str | None, str | None]:
    """Trả về (platform, agent_version) từ envelope v4. Fallback qua os_meta."""
    platform = None
    agent_version = None
    if isinstance(agent_meta, dict):
        platform = agent_meta.get("platform")
        agent_version = agent_meta.get("version")
    if not platform and isinstance(os_meta, dict):
        platform = os_meta.get("platform")
    return platform, agent_version


def derive_v4_security_fields(security) -> dict:
    """Trả về dict cột trung lập từ schema v4 (security.update, .remote_access,
    .disk_encryption, .endpoint_protection, .privilege_control). Fallback từ
    schema phẳng cũ khi thiếu v4 object."""
    sec_dict = security.model_dump() if hasattr(security, "model_dump") else (security or {})
    if not isinstance(sec_dict, dict):
        sec_dict = {}

    update = sec_dict.get("update") or {}
    if not isinstance(update, dict):
        update = {}
    remote = sec_dict.get("remote_access") or {}
    if not isinstance(remote, dict):
        remote = {}
    enc = sec_dict.get("disk_encryption") or {}
    if not isinstance(enc, dict):
        enc = {}
    ep = sec_dict.get("endpoint_protection")
    priv = sec_dict.get("privilege_control") or {}
    if not isinstance(priv, dict):
        priv = {}

    # update.status: fallback từ windows_update_status legacy
    update_status = update.get("status")
    if not update_status:
        legacy = sec_dict.get("windows_update_status")
        if legacy:
            lu = legacy.strip().lower()
            if lu in ("up-to-date", "up to date", "uptodate"):
                update_status = "up-to-date"
            elif lu in ("outdated",):
                update_status = "outdated"
            else:
                update_status = "unknown"

    # remote_desktop: fallback rdp_enabled
    remote_desktop = remote.get("remote_desktop_enabled")
    if remote_desktop is None:
        remote_desktop = sec_dict.get("rdp_enabled")

    # disk_encryption: fallback bitlocker
    enc_enabled = enc.get("enabled")
    enc_tech = enc.get("technology")
    if enc_enabled is None and sec_dict.get("bitlocker") is not None:
        enc_enabled = sec_dict.get("bitlocker") == "on"
        enc_tech = "bitlocker"

    # endpoint_protection: fallback antivirus list
    if isinstance(ep, list):
        ep_enabled = bool(ep)
    else:
        legacy_av = sec_dict.get("antivirus")
        ep_enabled = bool(legacy_av) if isinstance(legacy_av, list) else None

    return {
        "update_status": update_status,
        "update_enabled": update.get("enabled"),
        "updates_pending": update.get("pending_count"),
        "endpoint_protection_enabled": ep_enabled,
        "disk_encryption_enabled": enc_enabled,
        "disk_encryption_technology": enc_tech,
        "ssh_enabled": remote.get("ssh_enabled"),
        "remote_desktop_enabled": remote_desktop,
    }
