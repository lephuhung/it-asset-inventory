"""Inventory — payload mới của agent Windows (schema đầy đủ: cpu, disks+partitions,
gpu, mainboard, bios, network mở rộng, installed_software, security).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

# ── Payload đúng cấu trúc agent sẽ push (xem docs/API_CONTRACT.md) ────────────

NEW_AGENT_PAYLOAD = {
    "os_name": "Windows 11 Pro 25H2",
    "os_version": "10.0.26200",
    "os_build": "26200",
    "os_arch": "X64",
    "os_installed_at": "2024-05-15T08:30:00Z",
    "activation_status": "Licensed",
    "is_vm": False,
    "logged_user": "DESKTOP-EATRCNQ\\LPH",
    "config_hash": "a1b2c3d4e5f6deadbeef",
    "cpu": {
        "model": "13th Gen Intel(R) Core(TM) i7-13700H",
        "cores": 14,
        "threads": 20,
        "clock_mhz": 2400,
        "virtualization_enabled": True,
    },
    "ram_gb": 31.7,
    "disks": [
        {
            "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00",
            "size_bytes": 1024209543168,
            "bus_type": "NVMe",
            "media_type": "SSD",
            "smart_health": "OK",
            "partitions": [
                {"drive_letter": "C:", "total_bytes": 511000000000, "free_bytes": 320000000000, "file_system": "NTFS"}
            ],
        }
    ],
    "gpu": {"model": "NVIDIA GeForce RTX 4060 Laptop GPU", "driver_version": "31.0.15.5123", "memory_mb": 8192},
    "mainboard": {"manufacturer": "Dell Inc.", "product": "0K5R1T", "serial": "/ABC1234/CN123456789/", "version": "A00"},
    "bios": {"vendor": "Dell Inc.", "version": "1.14.0", "release_date": "2024-01-10", "smbios_version": "3.5"},
    "network": [
        {
            "name": "Wi-Fi (Intel(R) Wi-Fi 6E AX211 160MHz)",
            "ip": "10.10.0.253",
            "mac": "00:1A:2B:3C:4D:5E",
            "is_dual_homed": False,
            "gateway": "10.10.0.1",
            "dhcp_enabled": True,
            "dns_servers": ["10.10.0.1", "8.8.8.8"],
            "speed_mbps": 1200,
        }
    ],
    "installed_software": [
        {
            "display_name": "Google Chrome",
            "version": "127.0.6533.100",
            "publisher": "Google LLC",
            "install_date": "2024-08-10",
            "uninstall_string": '"C:\\Program Files\\Google\\Chrome\\..."',
            "is_per_user": False,
        },
        {
            "display_name": "Microsoft Visual Studio Code",
            "version": "1.92.2",
            "publisher": "Microsoft Corporation",
            "install_date": "2024-08-15",
            "uninstall_string": '"C:\\Users\\LPH\\AppData\\Local\\..."',
            "is_per_user": True,
        },
    ],
    "security": {
        "antivirus": [{"displayName": "Windows Defender", "enabled": True, "upToDate": True}],
        "windows_update_status": "up-to-date",
        "bitlocker": "on",
        "rdp_enabled": False,
        "local_accounts": [
            {"username": "Administrator", "full_name": "Quản trị hệ thống", "disabled": True, "has_password": True, "is_admin": True}
        ],
        "smarts": [{"device": "PhysicalDrive0", "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00", "health": "OK"}],
    },
}

# ── Payload v3: thêm trường legacy/alias + nhóm bảo mật mở rộng ───────────────
NEW_AGENT_PAYLOAD_V3 = {
    "os_name": "Microsoft Windows 11 Pro 25H2",
    "os_version": "10.0.26200",
    "os_build": "26200",
    "os_arch": "x64",
    "os_installed_at": "2024-03-15T08:30:00Z",
    "activation_status": "Licensed",
    "is_vm": False,
    "logged_user": "DESKTOP-EATRCNQ\\LPH",
    "config_hash": "a1b2c3d4e5f6...",
    "cpu": {"model": "13th Gen Intel(R) Core(TM) i7-13700H", "cores": 14},
    "ram_gb": 31.7,
    "disks": [
        {
            "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00",
            "serial": "S677NF0W123456",
            "size_bytes": 1024209543168,
            "size": 1024209543168,
            "size_gb": 954,
            "type": "NVMe",
        }
    ],
    "gpu": {"model": "NVIDIA GeForce RTX 4060 Laptop GPU"},
    "mainboard": {"model": "0K3X7G", "serial": "/9ABCDE3/CN123456789/"},
    "bios": {"version": "1.14.0"},
    "network": [
        {"name": "Wi-Fi", "ip": "10.10.0.253", "mac": "E4:54:E8:2B:1A:0C", "is_dual_homed": False},
        {"name": "vEthernet (WSL)", "ip": "172.26.0.1", "mac": "00:15:5D:8A:9B:01", "is_dual_homed": False},
    ],
    "installed_software": [
        {
            "display_name": "Google Chrome",
            "name": "Google Chrome",
            "version": "128.0.6613.85",
            "publisher": "Google LLC",
            "install_date": "2024-08-20",
            "uninstall_string": '"C:\\Program Files\\Google\\Chrome\\Application\\128.0.6613.85\\Installer\\setup.exe" --uninstall',
            "is_per_user": False,
        },
        {
            "display_name": "Microsoft Visual Studio Code",
            "name": "Microsoft Visual Studio Code",
            "version": "1.92.2",
            "publisher": "Microsoft Corporation",
            "install_date": "2024-08-15",
            "uninstall_string": '"C:\\Users\\LPH\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe" --uninstall',
            "is_per_user": True,
        },
        {
            "display_name": "Docker Desktop",
            "name": "Docker Desktop",
            "version": "4.33.1",
            "publisher": "Docker Inc.",
            "install_date": "2024-07-20",
            "uninstall_string": None,
            "is_per_user": False,
        },
    ],
    "security": {
        "antivirus": [
            {
                "displayName": "Windows Defender",
                "name": "Windows Defender",
                "status": "enabled",
                "enabled": True,
                "upToDate": True,
            }
        ],
        "windows_update_status": "up-to-date",
        "bitlocker": "off",
        "firewall_enabled": True,
        "uac_enabled": True,
        "secure_boot_enabled": True,
        "usb_storage_blocked": False,
        "rdp_enabled": False,
        "weak_protocols": {"smbv1_disabled": True, "tls10_disabled": True, "tls11_disabled": True, "ssl3_disabled": True},
        "listening_ports": [
            {"port": 135, "protocol": "TCP", "address": "0.0.0.0"},
            {"port": 445, "protocol": "TCP", "address": "0.0.0.0"},
            {"port": 8000, "protocol": "TCP", "address": "127.0.0.1"},
        ],
        "startup_programs": [
            {"name": "SecurityHealth", "command": "%windir%\\system32\\SecurityHealthSystray.exe", "location": "HKLM_Run"},
            {"name": "OneDrive", "command": '"C:\\Program Files\\Microsoft OneDrive\\OneDrive.exe" /background', "location": "HKCU_Run"},
            {"name": "UniKey", "command": '"C:\\Program Files\\UniKey\\UniKeyNT.exe"', "location": "HKCU_Run"},
            {"name": "Docker Desktop", "command": '"C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"', "location": "HKCU_Run"},
        ],
        "local_accounts": [
            {"username": "Administrator", "name": "Administrator", "full_name": "Quản trị hệ thống", "disabled": True, "has_password": True, "is_admin": True},
            {"username": "LPH", "name": "LPH", "full_name": "Le Phu Hung", "disabled": False, "has_password": True, "is_admin": True},
        ],
        "smarts": [{"device": "PhysicalDrive0", "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00", "health": "OK"}],
    },
}


async def _enroll_machine(client, admin_token, org_id) -> str:
    """Enroll 1 máy → trả machine_id (CN của client cert mTLS)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    tok = await _create_token(client, admin_token, org_id)
    enroll_token = tok["token"]

    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "machine-new-payload")]))
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

    r = await client.post(
        "/api/enroll",
        json={
            "token": enroll_token,
            "csr_pem": csr_pem,
            "fingerprint": {"smbios_uuid": "UUID-NEW-PAYLOAD", "machine_guid": "G-NEW", "mainboard_serial": "SN-NEW"},
            "hostname": "PC-NEW-PAYLOAD",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["machine_id"]


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _create_token(client, token, org_id):
    r = await client.post(
        "/api/tokens",
        json={"org_id": org_id, "full_name": "Nguyễn Văn B", "email": "b@test.gov.vn"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_inventory_new_payload_accepted_and_stored(client, seeded_env, session_factory):
    """POST payload mới → 200; mọi trường được lưu đủ vào machine_specs."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json=NEW_AGENT_PAYLOAD,
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_changed"] is True

    from sqlalchemy import select

    from app.db.models import MachineSpec

    async with session_factory() as s:
        spec = (
            await s.execute(
                select(MachineSpec).where(MachineSpec.machine_id == machine_id)
            )
        ).scalar_one()

    # ── OS ──
    assert spec.os_name == "Windows 11 Pro 25H2"
    assert spec.os_version == "10.0.26200"
    assert spec.os_build == "26200"
    assert spec.os_arch == "X64"
    assert spec.os_installed_at == datetime(2024, 5, 15, 8, 30, tzinfo=UTC)
    assert spec.activation_status == "Licensed"

    # ── CPU ──
    assert spec.cpu["model"] == "13th Gen Intel(R) Core(TM) i7-13700H"
    assert spec.cpu["cores"] == 14
    assert spec.cpu["threads"] == 20
    assert spec.cpu["clock_mhz"] == 2400
    assert spec.cpu["virtualization_enabled"] is True

    # ── RAM / disks (kèm partitions) ──
    assert spec.ram_gb == 31.7
    disk = spec.disks[0]
    assert disk["model"].startswith("NVMe SAMSUNG")
    assert disk["size_bytes"] == 1024209543168
    assert disk["bus_type"] == "NVMe"
    assert disk["media_type"] == "SSD"
    assert disk["smart_health"] == "OK"
    assert disk["partitions"][0]["drive_letter"] == "C:"
    assert disk["partitions"][0]["file_system"] == "NTFS"

    # ── GPU / mainboard / BIOS ──
    assert spec.gpu["model"].startswith("NVIDIA GeForce RTX 4060")
    assert spec.gpu["driver_version"] == "31.0.15.5123"
    assert spec.gpu["memory_mb"] == 8192
    assert spec.mainboard["manufacturer"] == "Dell Inc."
    assert spec.mainboard["serial"] == "/ABC1234/CN123456789/"
    assert spec.bios["version"] == "1.14.0"
    assert spec.bios["release_date"] == "2024-01-10"
    assert spec.bios["smbios_version"] == "3.5"

    # ── Network (các trường mới không bị rớt) ──
    net = spec.network[0]
    assert net["ip"] == "10.10.0.253"
    assert net["gateway"] == "10.10.0.1"
    assert net["dhcp_enabled"] is True
    assert net["dns_servers"] == ["10.10.0.1", "8.8.8.8"]
    assert net["speed_mbps"] == 1200

    # ── Installed software ──
    sw = {s["display_name"]: s for s in spec.installed_software}
    assert sw["Google Chrome"]["version"] == "127.0.6533.100"
    assert sw["Google Chrome"]["is_per_user"] is False
    assert sw["Microsoft Visual Studio Code"]["publisher"] == "Microsoft Corporation"
    assert sw["Microsoft Visual Studio Code"]["is_per_user"] is True

    # ── Security ──
    assert spec.security["antivirus"][0]["displayName"] == "Windows Defender"
    assert spec.security["antivirus"][0]["enabled"] is True
    assert spec.security["antivirus"][0]["upToDate"] is True
    assert spec.security["windows_update_status"] == "up-to-date"
    assert spec.security["bitlocker"] == "on"
    assert spec.security["rdp_enabled"] is False
    acct = spec.security["local_accounts"][0]
    assert acct["username"] == "Administrator"
    assert acct["is_admin"] is True
    assert spec.security["smarts"][0]["device"] == "PhysicalDrive0"
    assert spec.security["smarts"][0]["health"] == "OK"


async def test_inventory_dedupe_and_detail(client, seeded_env):
    """Gửi lại cùng config_hash → không lưu trùng; machine detail trả đủ trường mới."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json=NEW_AGENT_PAYLOAD,
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_changed"] is True

    # Lần 2 cùng hash → config_changed=False (không tạo snapshot trùng)
    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json=NEW_AGENT_PAYLOAD,
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_changed"] is False

    r = await client.get(
        f"/api/machines/{machine_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 200, r.text
    latest = r.json()["latest_spec"]
    assert latest["os_installed_at"] is not None
    assert latest["activation_status"] == "Licensed"
    assert latest["mainboard"]["manufacturer"] == "Dell Inc."
    assert latest["bios"]["smbios_version"] == "3.5"
    assert latest["network"][0]["speed_mbps"] == 1200
    assert len(latest["installed_software"]) == 2
    assert latest["security"]["antivirus"][0]["displayName"] == "Windows Defender"
    assert latest["config_hash"] == "a1b2c3d4e5f6deadbeef"


async def test_inventory_backward_compat_old_payload(client, seeded_env):
    """Payload cũ (cpu model/cores, disk capacity_gb, security list[dict]) vẫn chấp nhận."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json={
            "os_name": "Windows 10",
            "os_version": "22H2",
            "os_build": "19045",
            "cpu": {"model": "Intel i5", "cores": 4},
            "ram_gb": 16.0,
            "disks": [{"model": "SSD", "capacity_gb": 512}],
            "security": {"antivirus": [{"name": "Defender", "status": "enabled"}]},
            "is_vm": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_changed"] is True


async def test_inventory_v3_full_security_payload(client, seeded_env, session_factory):
    """Payload v3 (alias fields + bảo mật mở rộng) → 200 và lưu đủ mọi trường."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"])

    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json=NEW_AGENT_PAYLOAD_V3,
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_changed"] is True

    from sqlalchemy import select

    from app.db.models import MachineSpec

    async with session_factory() as s:
        spec = (
            await s.execute(select(MachineSpec).where(MachineSpec.machine_id == machine_id))
        ).scalar_one()

    # ── Legacy/alias fields ──
    assert spec.os_name == "Microsoft Windows 11 Pro 25H2"
    disk = spec.disks[0]
    assert disk["serial"] == "S677NF0W123456"
    assert disk["size"] == 1024209543168
    assert disk["size_gb"] == 954
    assert disk["type"] == "NVMe"
    assert spec.mainboard["model"] == "0K3X7G"
    assert spec.mainboard["serial"] == "/9ABCDE3/CN123456789/"
    sw = {s["display_name"]: s for s in spec.installed_software}
    assert sw["Google Chrome"]["name"] == "Google Chrome"
    assert sw["Docker Desktop"]["uninstall_string"] is None
    assert len(spec.installed_software) == 3

    # ── Security mở rộng ──
    sec = spec.security
    av = sec["antivirus"][0]
    assert av["displayName"] == "Windows Defender"
    assert av["name"] == "Windows Defender"
    assert av["status"] == "enabled"
    assert av["enabled"] is True
    assert av["upToDate"] is True
    assert sec["firewall_enabled"] is True
    assert sec["uac_enabled"] is True
    assert sec["secure_boot_enabled"] is True
    assert sec["usb_storage_blocked"] is False
    assert sec["weak_protocols"] == {
        "smbv1_disabled": True, "tls10_disabled": True, "tls11_disabled": True, "ssl3_disabled": True,
    }
    ports = {p["port"]: p for p in sec["listening_ports"]}
    assert ports[135]["protocol"] == "TCP"
    assert ports[8000]["address"] == "127.0.0.1"
    startups = {p["name"]: p for p in sec["startup_programs"]}
    assert startups["SecurityHealth"]["location"] == "HKLM_Run"
    assert startups["Docker Desktop"]["command"].startswith('"C:\\Program Files\\Docker')
    acct = {a["username"]: a for a in sec["local_accounts"]}
    assert acct["LPH"]["name"] == "LPH"
    assert acct["LPH"]["full_name"] == "Le Phu Hung"
    assert acct["LPH"]["is_admin"] is True
    assert sec["smarts"][0]["health"] == "OK"


async def test_inventory_rejects_bad_types(client, seeded_env):
    """Trường sai kiểu (vd threads là chuỗi) → 422 — không lưu dữ liệu hỏng."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"])

    bad = json.loads(json.dumps(NEW_AGENT_PAYLOAD))
    bad["cpu"]["threads"] = "hai mươi"
    r = await client.post(
        "/api/inventory",
        headers={"X-SSL-Client-CN": machine_id},
        json=bad,
    )
    assert r.status_code == 422, r.text
