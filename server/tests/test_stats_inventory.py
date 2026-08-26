"""Thống kê inventory — bảng `machine_current` + `machine_software` (refactor schema thống kê).

- `POST /api/inventory` upsert `machine_current` + `machine_software` cùng transaction
  với insert `machine_specs`; payload agent v1/v2/v3 KHÔNG đổi (backward-compat).
- `GET /api/stats/inventory` trả nhóm đếm (os_family, firewall, update, antivirus, top app).
- RBAC theo cây tổ chức; `org_id` ngoài phạm vi → 403.
"""
from __future__ import annotations

import json

from sqlalchemy import func, select

from app.db.models import MachineCurrent, MachineSoftware, MachineSpec
from tests.test_inventory_new_payload import NEW_AGENT_PAYLOAD, NEW_AGENT_PAYLOAD_V3

# ── Helpers (giống test_inventory_new_payload.py) ──────────────────────────


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _create_token(client, token, org_id):
    r = await client.post(
        "/api/tokens",
        json={"org_id": org_id, "full_name": "Nguyễn Văn B", "email": "b@test.gov.vn"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _enroll_machine(client, admin_token, org_id, tag="default"):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    tok = await _create_token(client, admin_token, org_id)
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"machine-{tag}")]))
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

    r = await client.post(
        "/api/enroll",
        json={
            "token": tok["token"],
            "csr_pem": csr_pem,
            "fingerprint": {
                "smbios_uuid": f"UUID-{tag}",
                "machine_guid": f"G-{tag}",
                "mainboard_serial": f"SN-{tag}",
            },
            "hostname": f"PC-{tag}",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["machine_id"]


async def _post_inventory(client, machine_id, payload):
    r = await client.post("/api/inventory", headers={"X-SSL-Client-CN": machine_id}, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ── Upsert machine_current + machine_software ──────────────────────────────


async def test_inventory_upserts_current_and_software(client, seeded_env, session_factory):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"], tag="upsert")

    r = await _post_inventory(client, machine_id, NEW_AGENT_PAYLOAD)
    assert r["config_changed"] is True

    async with session_factory() as s:
        spec = (
            await s.execute(select(MachineSpec).where(MachineSpec.machine_id == machine_id))
        ).scalar_one()
        cur = (
            await s.execute(select(MachineCurrent).where(MachineCurrent.machine_id == machine_id))
        ).scalar_one()
        sw_rows = (
            await s.execute(select(MachineSoftware).where(MachineSoftware.machine_id == machine_id))
        ).scalars().all()

    # spec lịch sử có cột OS chuẩn hóa (server derive — agent không gửi)
    assert spec.os_product == "Windows 11 Pro"
    assert spec.os_release == "25H2"
    assert spec.os_family == "windows_11"

    # machine_current: OS chuẩn hóa
    assert cur.os_name == "Windows 11 Pro 25H2"
    assert cur.os_product == "Windows 11 Pro"
    assert cur.os_release == "25H2"
    assert cur.os_family == "windows_11"
    assert cur.os_build == "26200"
    assert cur.ram_gb == 31.7
    assert cur.logged_user == "DESKTOP-EATRCNQ\\LPH"
    assert cur.config_hash == "a1b2c3d4e5f6deadbeef"

    # machine_current: security thành cột có kiểu
    assert cur.windows_update_status == "up-to-date"
    assert cur.windows_update_enabled is True  # suy từ "up-to-date"
    assert cur.bitlocker == "on"
    assert cur.firewall_enabled is None  # payload v2 không gửi → unknown
    assert cur.antivirus_enabled is True
    assert cur.antivirus_up_to_date is True
    assert cur.antivirus[0]["displayName"] == "Windows Defender"

    # machine_software: 1 dòng/app
    names = sorted(r.name for r in sw_rows)
    assert names == ["Google Chrome", "Microsoft Visual Studio Code"]
    assert all(str(r.machine_id) == machine_id for r in sw_rows)


async def test_inventory_dedupe_no_software_duplication(client, seeded_env, session_factory):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"], tag="dedupe")

    await _post_inventory(client, machine_id, NEW_AGENT_PAYLOAD)
    r2 = await _post_inventory(client, machine_id, NEW_AGENT_PAYLOAD)
    assert r2["config_changed"] is False  # cùng hash → không lưu trùng

    async with session_factory() as s:
        n_specs = (
            await s.execute(
                select(func.count()).select_from(MachineSpec).where(MachineSpec.machine_id == machine_id)
            )
        ).scalar_one()
        n_sw = (
            await s.execute(
                select(func.count()).select_from(MachineSoftware).where(MachineSoftware.machine_id == machine_id)
            )
        ).scalar_one()
    assert n_specs == 1
    assert n_sw == 2  # không nhân đôi software


async def test_inventory_software_replace_on_change(client, seeded_env, session_factory):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    machine_id = await _enroll_machine(client, admin_token, seeded_env["org_id"], tag="replace")

    await _post_inventory(client, machine_id, NEW_AGENT_PAYLOAD)

    changed = json.loads(json.dumps(NEW_AGENT_PAYLOAD))
    changed["config_hash"] = "replaced-hash-0001"
    changed["installed_software"] = [
        {"display_name": "Google Chrome", "version": "128.0.0.1", "publisher": "Google LLC"}
    ]
    r = await _post_inventory(client, machine_id, changed)
    assert r["config_changed"] is True

    async with session_factory() as s:
        cur = (
            await s.execute(select(MachineCurrent).where(MachineCurrent.machine_id == machine_id))
        ).scalar_one()
        sw_rows = (
            await s.execute(select(MachineSoftware).where(MachineSoftware.machine_id == machine_id))
        ).scalars().all()

    assert cur.config_hash == "replaced-hash-0001"
    assert [x.name for x in sw_rows] == ["Google Chrome"]  # replace, không append
    assert sw_rows[0].version == "128.0.0.1"


# ── GET /api/stats/inventory ────────────────────────────────────────────────


async def test_stats_inventory_counts_and_top_software(client, seeded_env):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    # Máy A: Windows 11 + firewall bật + update up-to-date + 3 app
    # (tag khác hẳn nhau — fingerprint fuzzy-match theo SequenceMatcher, tag trùng
    #  tiền tố dài sẽ bị coi là CÙNG máy)
    ma = await _enroll_machine(client, admin_token, org_id, tag="a7f3c9")
    await _post_inventory(client, ma, NEW_AGENT_PAYLOAD_V3)

    # Máy B: Windows 10 (payload cũ v1, không security mở rộng) + Chrome
    mb = await _enroll_machine(client, admin_token, org_id, tag="b2e8d4")
    payload_b = {
        "os_name": "Windows 10 Pro 22H2",
        "os_version": "10.0.19045",
        "os_build": "19045",
        "cpu": {"model": "Intel i5", "cores": 4},
        "ram_gb": 16.0,
        "installed_software": [{"name": "Google Chrome", "version": "128.0.6613.85"}],
        "security": {"antivirus": [{"name": "Defender", "status": "enabled"}]},
    }
    await _post_inventory(client, mb, payload_b)

    r = await client.get("/api/stats/inventory", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["total_machines"] == 2
    os_family = {b["key"]: b["count"] for b in data["by_os_family"]}
    assert os_family == {"windows_11": 1, "windows_10": 1}

    firewall = {b["key"]: b["count"] for b in data["by_firewall"]}
    assert firewall == {"true": 1, "unknown": 1}

    upd_status = {b["key"]: b["count"] for b in data["by_windows_update_status"]}
    assert upd_status == {"up-to-date": 1, "unknown": 1}
    upd_enabled = {b["key"]: b["count"] for b in data["by_windows_update_enabled"]}
    assert upd_enabled == {"true": 1, "unknown": 1}

    antivirus = {b["key"]: b["count"] for b in data["by_antivirus"]}
    assert antivirus == {"true": 2}  # cả 2 máy có AV enabled (v1 status + v3 enabled)

    # Bucket RAM — máy A: 31.7 GB → "16–32 GB" (vì < 32); máy B: 16 GB → "16–32 GB"
    # (ranh giới trên là mở — "32+ GB" chỉ chứa ≥ 32 GB)
    ram = {b["key"]: b["count"] for b in data["by_ram_gb"]}
    assert ram == {"16–32 GB": 2}

    top = {t["name"]: t["machines"] for t in data["top_software"]}
    assert top["Google Chrome"] == 2  # cài trên cả 2 máy
    assert top["Docker Desktop"] == 1
    assert top["Microsoft Visual Studio Code"] == 1

    # Lọc theo org_id (trong phạm vi) → cùng kết quả
    r2 = await client.get(
        f"/api/stats/inventory?org_id={org_id}", headers=_auth(admin_token)
    )
    assert r2.status_code == 200
    assert r2.json()["total_machines"] == 2


async def test_stats_inventory_ram_buckets(client, seeded_env):
    """Bucket RAM — kiểm tra ranh giới <4 / 4–8 / 8–16 / 16–32 / 32+ GB + unknown."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    # Enroll 5 máy, mỗi máy 1 bucket. Tag phải đủ khác biệt để fuzzy-match
    # SequenceMatcher (threshold 0.8) không gộp thành 1 máy.
    cases = [
        ("alpharam1", 2.0),    # <4 GB
        ("betaramb", 6.0),     # 4–8 GB
        ("gammaram", 12.0),    # 8–16 GB
        ("deltaram", 24.0),    # 16–32 GB
        ("epsilonr", 64.0),    # 32+ GB
    ]
    for tag, ram in cases:
        mid = await _enroll_machine(client, admin_token, org_id, tag=tag)
        await _post_inventory(
            client,
            mid,
            {
                "os_name": "Windows 11 Pro 23H2",
                "os_version": "10.0.22631",
                "os_build": "22631",
                "cpu": {"model": "Intel", "cores": 4},
                "ram_gb": ram,
            },
        )

    r = await client.get("/api/stats/inventory", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()

    ram = {b["key"]: b["count"] for b in data["by_ram_gb"]}
    # 5 máy mới phân bố đúng 5 bucket (máy cũ ở test trước nằm test khác nên DB có thể đã reset)
    assert ram["<4 GB"] == 1
    assert ram["4–8 GB"] == 1
    assert ram["8–16 GB"] == 1
    assert ram["16–32 GB"] == 1
    assert ram["32+ GB"] == 1


async def test_stats_inventory_rbac_scope(client, seeded_env):
    """Admin org khác không thấy máy ngoài org; org_id ngoài phạm vi → 403."""
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    root_org = seeded_env["org_id"]

    ma = await _enroll_machine(client, admin_token, root_org, tag="rbac-a")
    await _post_inventory(client, ma, NEW_AGENT_PAYLOAD_V3)

    # Tạo org con + user org_admin
    r = await client.post(
        "/api/orgs",
        json={"name": "Phòng CNTT", "type": "phong", "parent_id": root_org},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    child_org = r.json()["id"]

    r = await client.post(
        "/api/users",
        json={
            "email": "cntt@test.gov.vn",
            "full_name": "Quản trị CNTT",
            "role": "org_admin",
            "org_id": child_org,
            "password": "secret12345",
        },
        headers=_auth(admin_token),
    )
    assert r.status_code == 201, r.text

    child_token = await _login(client, "cntt@test.gov.vn", "secret12345")

    # Org admin con chỉ thấy máy trong phạm vi (0 máy) — không thấy máy của root
    r = await client.get("/api/stats/inventory", headers=_auth(child_token))
    assert r.status_code == 200
    assert r.json()["total_machines"] == 0

    # Hỏi org_id ngoài phạm vi → 403
    r = await client.get(
        f"/api/stats/inventory?org_id={root_org}", headers=_auth(child_token)
    )
    assert r.status_code == 403
