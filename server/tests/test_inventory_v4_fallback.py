"""Tests for v4 inventory schema fallback normalization (Linux + Windows)."""
from app.schemas import InventoryRequest
from app.services.inventory_normalize import (
    derive_platform_fields,
    derive_v4_security_fields,
)


def _body(**kw):
    return InventoryRequest.model_validate(kw)


def test_v4_linux_fields_extracted():
    body = _body(
        inventory_schema_version=4,
        agent={"platform": "linux", "version": "1.1.0", "package_type": "deb"},
        os={"platform": "linux", "distribution": "ubuntu", "distribution_version": "24.04"},
        security={
            "update": {"status": "updates-available", "pending_count": 12, "security_pending_count": 3},
            "remote_access": {"ssh_enabled": True, "remote_desktop_enabled": False},
            "disk_encryption": {"enabled": True, "technology": "luks"},
            "endpoint_protection": [{"name": "ClamAV"}],
            "privilege_control": {"sudo_installed": True, "root_account_locked": True},
        },
    )
    plat, ver = derive_platform_fields(body.agent, body.os)
    assert plat == "linux"
    assert ver == "1.1.0"
    sec = derive_v4_security_fields(body.security)
    assert sec["update_status"] == "updates-available"
    assert sec["updates_pending"] == 12
    assert sec["ssh_enabled"] is True
    assert sec["remote_desktop_enabled"] is False
    assert sec["disk_encryption_enabled"] is True
    assert sec["disk_encryption_technology"] == "luks"
    assert sec["endpoint_protection_enabled"] is True


def test_legacy_windows_fallback():
    body = _body(
        security={
            "windows_update_status": "up-to-date",
            "rdp_enabled": False,
            "bitlocker": "on",
            "antivirus": [{"name": "Defender"}],
        },
    )
    sec = derive_v4_security_fields(body.security)
    assert sec["update_status"] == "up-to-date"
    assert sec["remote_desktop_enabled"] is False
    assert sec["disk_encryption_enabled"] is True
    assert sec["disk_encryption_technology"] == "bitlocker"
    assert sec["endpoint_protection_enabled"] is True


def test_platform_falls_back_to_os():
    """Khi agent block missing, derive từ os block."""
    plat, ver = derive_platform_fields(
        agent_meta=None,
        os_meta={"platform": "linux", "distribution": "rocky"},
    )
    assert plat == "linux"
    assert ver is None


def test_empty_security_returns_nulls():
    body = _body(security={})
    sec = derive_v4_security_fields(body.security)
    assert sec["update_status"] is None
    assert sec["disk_encryption_enabled"] is None
    assert sec["endpoint_protection_enabled"] is None