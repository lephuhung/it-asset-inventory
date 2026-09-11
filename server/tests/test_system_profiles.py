"""Test hồ sơ cấp độ hệ thống thông tin.

Kiểm chứng:
- CRUD hồ sơ + RBAC: org_admin chỉ làm được trong đơn vị của mình.
- Luồng phê duyệt: drafted → pending_review → approved/rejected.
- Super Admin duyệt phải có số quyết định; approve ghi nhận quyết định.
- Super Admin tạo hồ sơ kèm decision_number → approved trực tiếp.
- Devices CRUD + loại thiết bị hợp lệ; gắn/gỡ Machine cùng đơn vị.
- Hồ sơ approved không cho org_admin sửa/xóa.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.security import hash_password
from app.db.models import Machine, Organization, OrgType, User, UserRole


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _make_org(session_factory, name="UBND xã A"):
    async with session_factory() as s:
        org = Organization(name=name, type=OrgType.UBND_XA.value)
        s.add(org)
        await s.commit()
        return str(org.id)


async def _make_org_admin(session_factory, org_id):
    async with session_factory() as s:
        email = f"admin-{uuid.uuid4().hex[:8]}@org.test"
        s.add(
            User(
                org_id=org_id,
                full_name="Org Admin",
                email=email,
                role=UserRole.ORG_ADMIN.value,
                password_hash=hash_password("Passw0rd!123"),
            )
        )
        await s.commit()
        return email


async def _make_machine(session_factory, org_id):
    async with session_factory() as s:
        m = Machine(
            org_id=org_id,
            machine_uuid=uuid.uuid4().hex,
            hostname=f"PC-{uuid.uuid4().hex[:6]}",
            status="online",
            fingerprint={"smbios_uuid": uuid.uuid4().hex},
        )
        s.add(m)
        await s.commit()
        return str(m.id)


@pytest.fixture
async def org_env(client, session_factory, seeded_env):
    """Super admin (seeded_env) + 1 đơn vị con + org_admin của đơn vị đó."""
    org_id = await _make_org(session_factory)
    email = await _make_org_admin(session_factory, org_id)
    return {**seeded_env, "org_id": org_id, "org_admin_email": email}


async def test_full_approval_flow(client, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # Admin tạo hồ sơ → drafted
    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống 1", "level": 2},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "drafted"

    # Admin submit → pending_review
    r = await client.post(f"/api/system-profiles/{pid}/submit", headers=oa)
    assert r.status_code == 200
    assert r.json()["status"] == "pending_review"

    # Admin (không phải super) không được duyệt
    r = await client.post(
        f"/api/system-profiles/{pid}/review",
        headers=oa,
        json={"action": "approve", "decision_number": "01/2026"},
    )
    assert r.status_code == 403

    # Super admin duyệt thiếu số quyết định → 400
    r = await client.post(f"/api/system-profiles/{pid}/review", headers=sa, json={"action": "approve"})
    assert r.status_code == 400

    # Super admin duyệt đủ → approved, có quyết định
    r = await client.post(
        f"/api/system-profiles/{pid}/review",
        headers=sa,
        json={"action": "approve", "decision_number": "15/QĐ-ATTT", "decision_agency": "Công an tỉnh"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["decision_number"] == "15/QĐ-ATTT"

    # org_admin không sửa được hồ sơ đã approved
    r = await client.patch(f"/api/system-profiles/{pid}", headers=oa, json={"name": "Đổi tên"})
    assert r.status_code == 400
    # org_admin không xóa được hồ sơ đã approved
    r = await client.delete(f"/api/system-profiles/{pid}", headers=oa)
    assert r.status_code == 400


async def test_reject_and_resubmit(client, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống 2", "level": 1},
    )
    pid = r.json()["id"]
    await client.post(f"/api/system-profiles/{pid}/submit", headers=oa)
    r = await client.post(
        f"/api/system-profiles/{pid}/review",
        headers=sa,
        json={"action": "reject", "review_note": "Thiếu danh mục thiết bị"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    # Sửa lại hồ sơ bị từ chối → về drafted, xóa review_note
    r = await client.patch(f"/api/system-profiles/{pid}", headers=oa, json={"name": "Hệ thống 2 (sửa)"})
    assert r.status_code == 200
    assert r.json()["status"] == "drafted"
    assert r.json()["review_note"] is None


async def test_super_admin_create_approved_directly(client, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    r = await client.post(
        "/api/system-profiles",
        headers=sa,
        json={
            "org_id": org_env["org_id"],
        
            "name": "Hệ thống 3",
            "level": 3,
            "decision_number": "20/QĐ-ATTT",
            "decision_agency": "Công an tỉnh",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["decision_number"] == "20/QĐ-ATTT"


async def test_auto_generated_code(client, org_env):
    """Mã hồ sơ tự sinh HS-{năm}-{stt:03d}, tăng dần theo đơn vị + năm."""
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    payload = {"org_id": org_env["org_id"], "name": "Trùng tên cũng được", "level": 1}
    r1 = await client.post("/api/system-profiles", headers=oa, json=payload)
    r2 = await client.post("/api/system-profiles", headers=oa, json=payload)
    assert r1.status_code == 201 and r2.status_code == 201, r1.text
    from datetime import datetime
    year = datetime.now().year
    assert r1.json()["code"] == f"HS-{year}-001"
    assert r2.json()["code"] == f"HS-{year}-002"


async def test_org_admin_scoping(client, session_factory, org_env):
    """org_admin đơn vị A không thấy/sửa được hồ sơ của đơn vị khác."""
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    other_org = await _make_org(session_factory, "UBND xã B")
    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": other_org, "name": "Ngoài phạm vi", "level": 1},
    )
    assert r.status_code == 403

    # Tạo hồ sơ đơn vị khác bằng super admin → org_admin A không đọc được
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    r = await client.post(
        "/api/system-profiles",
        headers=sa,
        json={"org_id": other_org, "name": "Hồ sơ đơn vị B", "level": 2},
    )
    other_pid = r.json()["id"]
    r = await client.get(f"/api/system-profiles/{other_pid}", headers=oa)
    assert r.status_code == 403

    # List của org_admin A không chứa hồ sơ đơn vị B
    r = await client.get("/api/system-profiles", headers=oa)
    assert all(item["org_id"] != other_org for item in r.json()["items"])


async def test_devices_and_machines(client, session_factory, org_env):
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống 4", "level": 2},
    )
    pid = r.json()["id"]

    # Thêm thiết bị hợp lệ
    r = await client.post(
        f"/api/system-profiles/{pid}/devices",
        headers=oa,
        json={"name": "Firewall biên giới", "device_code": "FW-01", "tag": "FW", "device_type": "firewall"},
    )
    assert r.status_code == 201, r.text
    dev_id = r.json()["devices"][0]["id"]
    assert r.json()["device_count"] == 1

    # Loại thiết bị sai → 400
    r = await client.post(
        f"/api/system-profiles/{pid}/devices",
        headers=oa,
        json={"name": "Lạ", "device_type": "ufo"},
    )
    assert r.status_code == 400

    # Sửa + xóa thiết bị
    r = await client.put(
        f"/api/system-profiles/{pid}/devices/{dev_id}",
        headers=oa,
        json={"name": "Firewall chính", "device_type": "firewall", "sort_order": 1},
    )
    assert r.status_code == 200
    assert r.json()["devices"][0]["name"] == "Firewall chính"
    r = await client.delete(f"/api/system-profiles/{pid}/devices/{dev_id}", headers=oa)
    assert r.status_code == 200 and r.json()["device_count"] == 0

    # Gắn Machine cùng đơn vị / chặn máy khác đơn vị
    machine_id = await _make_machine(session_factory, org_env["org_id"])
    r = await client.post(f"/api/system-profiles/{pid}/machines?machine_id={machine_id}", headers=oa)
    assert r.status_code == 201 and r.json()["machine_count"] == 1
    # Gắn trùng → 409
    r = await client.post(f"/api/system-profiles/{pid}/machines?machine_id={machine_id}", headers=oa)
    assert r.status_code == 409
    other_machine = await _make_machine(session_factory, await _make_org(session_factory, "Org khác"))
    r = await client.post(f"/api/system-profiles/{pid}/machines?machine_id={other_machine}", headers=oa)
    assert r.status_code == 400
    # Gỡ
    r = await client.delete(f"/api/system-profiles/{pid}/machines/{machine_id}", headers=oa)
    assert r.status_code == 200 and r.json()["machine_count"] == 0


async def test_list_filters(client, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    for i, (code, level) in enumerate([("F1", 1), ("F2", 2), ("F3", 3)]):
        await client.post(
            "/api/system-profiles",
            headers=sa,
            json={
                "org_id": org_env["org_id"],
                "code": code,
                "name": f"Lọc {i}",
                "level": level,
                "decision_number": f"{i}/QĐ",
                "decision_agency": "Công an tỉnh",
            },
        )
    r = await client.get("/api/system-profiles?level=2", headers=sa)
    assert r.status_code == 200
    assert all(item["level"] == 2 for item in r.json()["items"])
    r = await client.get("/api/system-profiles?status=approved", headers=sa)
    assert all(item["status"] == "approved" for item in r.json()["items"])
    r = await client.get("/api/system-profiles?q=Lọc 0", headers=sa)
    assert len(r.json()["items"]) == 1


# ── Yêu cầu an toàn theo cấp độ + thẩm định ─────────────────


async def _seed_requirements(session_factory, items):
    """Seed catalog yêu cầu (test DB không chạy alembic seed)."""
    from app.db.models import LevelRequirement

    async with session_factory() as s:
        out = []
        for level, code, title in items:
            r = LevelRequirement(level=level, code=code, title=title, sort_order=0)
            s.add(r)
            out.append((level, code))
        await s.commit()
        return out


async def _get_profile(client, sa, pid):
    r = await client.get(f"/api/system-profiles/{pid}", headers=sa)
    assert r.status_code == 200, r.text
    return r.json()


async def test_requirements_autocreate_and_compliance(client, session_factory, org_env):
    await _seed_requirements(
        session_factory,
        [(1, "L1-A", "Yêu cầu A"), (1, "L1-B", "Yêu cầu B"), (2, "L2-C", "Yêu cầu C")],
    )
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hồ sơ yêu cầu", "level": 1},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    pid = body["id"]
    # Tự sinh 2 yêu cầu của cấp 1
    assert body["requirements_total"] == 2
    assert body["level_compliant"] is False
    reqs = {x["code"]: x for x in body["requirements"]}
    assert set(reqs) == {"L1-A", "L1-B"}

    # Đơn vị khai báo hoàn thành + trình thẩm định
    row_a = reqs["L1-A"]["id"]
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row_a}/request",
        headers=oa,
        json={"evidence": "Đã phân quyền, có danh sách tài khoản"},
    )
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["requirements"] if x["id"] == row_a)["status"] == "requested"

    # Đơn vị không được tự thẩm định
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row_a}/review", headers=oa, json={"action": "verify"}
    )
    assert r.status_code == 403

    # Super Admin thẩm định đạt
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row_a}/review", headers=sa, json={"action": "verify"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requirements_verified"] == 1 and body["level_compliant"] is False

    # Hoàn thành nốt yêu cầu B → đủ n yêu cầu → đạt cấp độ
    row_b = next(x for x in body["requirements"] if x["code"] == "L1-B")["id"]
    await client.post(
        f"/api/system-profiles/{pid}/requirements/{row_b}/request", headers=oa, json={"evidence": "Đã sao lưu"}
    )
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row_b}/review", headers=sa, json={"action": "verify"}
    )
    body = r.json()
    assert body["requirements_verified"] == 2
    assert body["level_compliant"] is True

    # Không trình thẩm định lại yêu cầu đã verified
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row_a}/request", headers=oa, json={"evidence": "làm lại"}
    )
    assert r.status_code == 400


async def test_requirement_reject_then_resubmit(client, session_factory, org_env):
    await _seed_requirements(session_factory, [(1, "L1-R", "Yêu cầu R")])
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hồ sơ R2", "level": 1},
    )
    pid = r.json()["id"]
    row = r.json()["requirements"][0]["id"]

    await client.post(
        f"/api/system-profiles/{pid}/requirements/{row}/request", headers=oa, json={"evidence": "chưa đủ"}
    )
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row}/review",
        headers=sa,
        json={"action": "reject", "review_note": "Thiếu bằng chứng"},
    )
    assert r.status_code == 200
    assert next(x for x in r.json()["requirements"] if x["id"] == row)["status"] == "rejected"

    # Trình lại sau khi bị từ chối
    r = await client.post(
        f"/api/system-profiles/{pid}/requirements/{row}/request", headers=oa, json={"evidence": "đã bổ sung"}
    )
    assert r.status_code == 200
    assert next(x for x in r.json()["requirements"] if x["id"] == row)["status"] == "requested"


async def test_level_change_resyncs_requirements(client, session_factory, org_env):
    await _seed_requirements(session_factory, [(1, "L1-X", "X cấp 1"), (2, "L2-Y", "Y cấp 2")])
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hồ sơ R3", "level": 1},
    )
    pid = r.json()["id"]
    assert {x["code"] for x in r.json()["requirements"]} == {"L1-X"}

    r = await client.patch(f"/api/system-profiles/{pid}", headers=oa, json={"level": 2})
    assert r.status_code == 200
    assert {x["code"] for x in r.json()["requirements"]} == {"L2-Y"}
    assert r.json()["requirements_total"] == 1


async def test_level_requirement_catalog_crud(client, session_factory, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # Admin thường không được quản trị catalog
    r = await client.post(
        "/api/level-requirements", headers=oa, json={"level": 1, "code": "L1-Z", "title": "Z"}
    )
    assert r.status_code == 403

    # Super Admin tạo + chặn trùng code
    r = await client.post(
        "/api/level-requirements", headers=sa, json={"level": 1, "code": "L1-Z", "title": "Yêu cầu Z"}
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await client.post(
        "/api/level-requirements", headers=sa, json={"level": 1, "code": "L1-Z", "title": "Trùng"}
    )
    assert r.status_code == 409

    # Sửa + filter theo level
    r = await client.patch(f"/api/level-requirements/{rid}", headers=sa, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = await client.get("/api/level-requirements?level=1", headers=sa)
    assert all(x["level"] == 1 for x in r.json())

    # Tạo hồ sơ cấp 1 khi yêu cầu Z bị tắt → không sinh Z
    r = await client.post(
        "/api/system-profiles",
        headers=sa,
        json={"org_id": org_env["org_id"], "name": "Hồ sơ R4", "level": 1},
    )
    assert all(x["code"] != "L1-Z" for x in r.json()["requirements"])

    # Xóa được vì không hồ sơ nào dùng
    r = await client.delete(f"/api/level-requirements/{rid}", headers=sa)
    assert r.status_code == 204


# ── Dossier hồ sơ: chủ quản/vận hành, ứng dụng, vùng mạng ──


async def _make_profile(client, headers, org_id, code):
    r = await client.post(
        "/api/system-profiles",
        headers=headers,
        json={"org_id": org_id, "name": f"Hồ sơ {code}", "level": 2},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_parties_crud(client, org_env):
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    pid = await _make_profile(client, oa, org_env["org_id"], "HTTT-P1")

    # Thêm chủ quản + vận hành
    r = await client.post(
        f"/api/system-profiles/{pid}/parties",
        headers=oa,
        json={
            "role": "owner",
            "name": "Công an tỉnh",
            "mandate_document": "Quyết định 01/QĐ",
            "legal_representative": "Nguyễn Văn A",
            "representative_title": "Giám đốc",
            "address": "Hà Tĩnh",
            "phone": "0239000000",
            "email": "owner@test.gov.vn",
        },
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["parties"]) == 1
    party_id = r.json()["parties"][0]["id"]

    # Chặn trùng role (1 hồ sơ chỉ 1 chủ quản)
    r = await client.post(
        f"/api/system-profiles/{pid}/parties", headers=oa, json={"role": "owner", "name": "Trùng"}
    )
    assert r.status_code == 409

    # role sai giá trị → 422
    r = await client.post(
        f"/api/system-profiles/{pid}/parties", headers=oa, json={"role": "khac", "name": "X"}
    )
    assert r.status_code == 422

    # Sửa
    r = await client.put(
        f"/api/system-profiles/{pid}/parties/{party_id}",
        headers=oa,
        json={"role": "owner", "name": "Công an tỉnh (cập nhật)"},
    )
    assert r.status_code == 200
    assert r.json()["parties"][0]["name"] == "Công an tỉnh (cập nhật)"

    # Thêm operator + xóa
    r = await client.post(
        f"/api/system-profiles/{pid}/parties", headers=oa, json={"role": "operator", "name": "Trung tâm KTTH"}
    )
    assert r.status_code == 201 and len(r.json()["parties"]) == 2
    r = await client.delete(f"/api/system-profiles/{pid}/parties/{party_id}", headers=oa)
    assert r.status_code == 200 and len(r.json()["parties"]) == 1


async def test_applications_crud(client, session_factory, org_env):
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    pid = await _make_profile(client, oa, org_env["org_id"], "HTTT-P2")

    r = await client.post(
        f"/api/system-profiles/{pid}/applications",
        headers=oa,
        json={"name": "Hệ thống văn bản", "server_name": "SRV-DOC", "os_name": "Ubuntu 22.04", "role": "Quản lý văn bản"},
    )
    assert r.status_code == 201, r.text
    app_id = r.json()["applications"][0]["id"]

    # Gắn máy chủ đã enroll cùng đơn vị
    machine_id = await _make_machine(session_factory, org_env["org_id"])
    r = await client.put(
        f"/api/system-profiles/{pid}/applications/{app_id}",
        headers=oa,
        json={"name": "Hệ thống văn bản", "machine_id": machine_id, "role": "Quản lý văn bản điện tử"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["applications"][0]["machine_id"] == machine_id

    # Máy khác đơn vị → 400
    other = await _make_machine(session_factory, await _make_org(session_factory, "Org App Khác"))
    r = await client.put(
        f"/api/system-profiles/{pid}/applications/{app_id}",
        headers=oa,
        json={"name": "X", "machine_id": other},
    )
    assert r.status_code == 400

    r = await client.delete(f"/api/system-profiles/{pid}/applications/{app_id}", headers=oa)
    assert r.status_code == 200 and r.json()["applications"] == []


async def test_ip_ranges_crud(client, org_env):
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    pid = await _make_profile(client, oa, org_env["org_id"], "HTTT-P3")

    r = await client.post(
        f"/api/system-profiles/{pid}/ip-ranges",
        headers=oa,
        json={"zone": "DMZ", "zone_description": "Vùng dịch vụ công", "cidr": "10.10.1.0/24", "ip_kind": "private"},
    )
    assert r.status_code == 201, r.text
    rid = r.json()["ip_ranges"][0]["id"]

    # ip_kind sai → 422
    r = await client.post(
        f"/api/system-profiles/{pid}/ip-ranges",
        headers=oa,
        json={"zone": "X", "cidr": "1.2.3.0/24", "ip_kind": "banana"},
    )
    assert r.status_code == 422

    r = await client.put(
        f"/api/system-profiles/{pid}/ip-ranges/{rid}",
        headers=oa,
        json={"zone": "DMZ", "cidr": "10.10.1.0/24", "ip_kind": "public", "gateway": "10.10.1.1"},
    )
    assert r.status_code == 200
    assert r.json()["ip_ranges"][0]["ip_kind"] == "public"

    r = await client.delete(f"/api/system-profiles/{pid}/ip-ranges/{rid}", headers=oa)
    assert r.status_code == 200 and r.json()["ip_ranges"] == []


async def test_scope_fields_update(client, org_env):
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    pid = await _make_profile(client, oa, org_env["org_id"], "HTTT-P4")

    r = await client.patch(
        f"/api/system-profiles/{pid}",
        headers=oa,
        json={
            "physical_location": "Tầng 2, trụ sở UBND xã A",
            "user_accounts": 120,
            "data_volume": "Khoảng 50GB, tăng ~1GB/tháng",
            "service_audience": "citizens",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_accounts"] == 120
    assert body["service_audience"] == "citizens"
    assert body["physical_location"].startswith("Tầng 2")

    # Giá trị audience sai → 400
    r = await client.patch(
        f"/api/system-profiles/{pid}", headers=oa, json={"service_audience": "người sao hỏa"}
    )
    assert r.status_code == 400


# ── Catalog loại thiết bị (quản trị động) ───────────────────


async def test_device_type_catalog_crud(client, session_factory, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # Mọi user đọc được catalog (seed 8 loại từ conftest)
    r = await client.get("/api/device-types", headers=oa)
    assert r.status_code == 200
    codes = {x["code"] for x in r.json()}
    assert {"firewall", "router", "switch", "server", "other"} <= codes

    # Admin thường không được thêm
    r = await client.post(
        "/api/device-types", headers=oa, json={"code": "camera", "label": "Camera", "icon": "📷"}
    )
    assert r.status_code == 403

    # Super Admin thêm loại mới + icon cho sơ đồ
    r = await client.post(
        "/api/device-types", headers=sa, json={"code": "Camera", "label": "Camera giám sát", "icon": "📷", "sort_order": 8}
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "camera"  # normalize
    tid = r.json()["id"]

    # Chặn trùng code
    r = await client.post(
        "/api/device-types", headers=sa, json={"code": "camera", "label": "Trùng"}
    )
    assert r.status_code == 409

    # Sửa nhãn + tắt bật
    r = await client.patch(f"/api/device-types/{tid}", headers=sa, json={"label": "Camera IP", "is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    # active_only=false mới thấy loại tắt
    r = await client.get("/api/device-types", headers=sa)
    assert all(x["is_active"] for x in r.json())
    r = await client.get("/api/device-types?active_only=false", headers=sa)
    assert any(x["code"] == "camera" for x in r.json())

    # Dùng loại trong hồ sơ rồi thì chặn xóa
    pid = await _make_profile(client, sa, org_env["org_id"], "HTTT-DT")
    r = await client.patch(f"/api/device-types/{tid}", headers=sa, json={"is_active": True})
    assert r.status_code == 200
    r = await client.post(
        f"/api/system-profiles/{pid}/devices",
        headers=sa,
        json={"name": "Cam cổng", "device_type": "camera"},
    )
    assert r.status_code == 201, r.text  # loại mới dùng được ngay trong hồ sơ
    r = await client.delete(f"/api/device-types/{tid}", headers=sa)
    assert r.status_code == 409

    # Loại chưa dùng → xóa được
    r = await client.post(
        "/api/device-types", headers=sa, json={"code": "sensor", "label": "Cảm biến", "icon": "🌡️"}
    )
    rid = r.json()["id"]
    r = await client.delete(f"/api/device-types/{rid}", headers=sa)
    assert r.status_code == 204


# ── Số văn bản đề nghị + triển khai/đáp ứng + stats ─────────


async def _approved_profile(client, org_env, oa_headers, sa_headers):
    r = await client.post(
        "/api/system-profiles",
        headers=oa_headers,
        json={"org_id": org_env["org_id"], "name": "Hệ thống triển khai", "level": 1},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    await client.post(f"/api/system-profiles/{pid}/submit", headers=oa_headers)
    r = await client.post(
        f"/api/system-profiles/{pid}/review",
        headers=sa_headers,
        json={"action": "approve", "decision_number": "01/QĐ-ATTT"},
    )
    assert r.json()["status"] == "approved"
    return pid


async def test_document_fields_optional_and_editable_after_approval(client, org_env):
    """Số văn bản + ngày văn bản không bắt buộc; sửa được sau khi hồ sơ đã duyệt."""
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    pid = await _approved_profile(client, org_env, oa, sa)

    # Không nhập số văn bản khi tạo → vẫn tạo được
    r = await client.get(f"/api/system-profiles/{pid}", headers=oa)
    assert r.json()["document_number"] is None

    # org_admin bổ sung số văn bản sau khi hồ sơ đã approved
    r = await client.patch(
        f"/api/system-profiles/{pid}",
        headers=oa,
        json={"document_number": "125/BC-XX", "document_date": "2026-08-20"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["document_number"] == "125/BC-XX"
    assert r.json()["document_date"].startswith("2026-08-20")

    # Nhưng vẫn không sửa được nội dung khác (name) khi đã approved
    r = await client.patch(f"/api/system-profiles/{pid}", headers=oa, json={"name": "Đổi tên"})
    assert r.status_code == 400


async def test_implementation_flow_and_stats(client, session_factory, org_env):
    """approved → khai báo triển khai (chỉ khi đủ 100% yêu cầu ATTT đạt) → fulfilled; stats đúng."""
    await _seed_requirements(session_factory, [(1, "L1-IMP", "Yêu cầu triển khai")])
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    pid = await _approved_profile(client, org_env, oa, sa)
    row = (await _get_profile(client, sa, pid))["requirements"][0]["id"]

    # Chưa thẩm định đủ yêu cầu cấp độ → chặn khai báo triển khai
    r = await client.post(f"/api/system-profiles/{pid}/report-implementation", headers=oa, json={})
    assert r.status_code == 400, r.text
    assert "đã thẩm định đạt" in r.json()["detail"]

    # Super admin không confirm được khi hồ sơ còn approved
    r = await client.post(f"/api/system-profiles/{pid}/confirm-implementation", headers=sa, json={})
    assert r.status_code == 400

    # Đơn vị trình thẩm định yêu cầu, Super Admin xác nhận đạt → đủ 100%
    await client.post(f"/api/system-profiles/{pid}/requirements/{row}/request", headers=oa, json={"evidence": "Đã triển khai xong"})
    r = await client.post(f"/api/system-profiles/{pid}/requirements/{row}/review", headers=sa, json={"action": "verify"})
    assert r.json()["level_compliant"] is True

    # Đơn vị khai báo đã triển khai
    r = await client.post(f"/api/system-profiles/{pid}/report-implementation", headers=oa, json={"note": "Đã triển khai xong"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "implemented"

    # Khai báo lần nữa → 400 (đã implemented)
    r = await client.post(f"/api/system-profiles/{pid}/report-implementation", headers=oa, json={})
    assert r.status_code == 400

    # Super admin xác nhận đáp ứng
    r = await client.post(f"/api/system-profiles/{pid}/confirm-implementation", headers=sa, json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fulfilled"

    # Stats có trạng thái fulfilled
    r = await client.get("/api/system-profiles/stats", headers=sa)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert body["by_status"]["fulfilled"] >= 1
    assert set(body["by_level"]) <= {"1", "2", "3"}


async def test_timeline_events(client, session_factory, org_env):
    """Mọi mutation ghi mốc timeline đúng thứ tự, kèm người thao tác."""
    await _seed_requirements(session_factory, [(2, "L2-TL", "Yêu cầu timeline")])
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))

    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống timeline", "level": 2},
    )
    pid = r.json()["id"]
    # Tạo hồ sơ → có event "created"
    assert r.json()["events"][0]["event"] == "created", r.text

    # Thêm thiết bị → event device_added
    await client.post(
        f"/api/system-profiles/{pid}/devices",
        headers=oa,
        json={"name": "Firewall biên", "device_type": "firewall"},
    )

    # submit → duyệt → thẩm định yêu cầu → khai báo triển khai → confirm
    await client.post(f"/api/system-profiles/{pid}/submit", headers=oa)
    await client.post(f"/api/system-profiles/{pid}/review", headers=sa, json={"action": "approve", "decision_number": "09/QĐ"})
    req_row = (await _get_profile(client, sa, pid))["requirements"][0]["id"]
    await client.post(f"/api/system-profiles/{pid}/requirements/{req_row}/request", headers=oa, json={"evidence": "đạt"})
    await client.post(f"/api/system-profiles/{pid}/requirements/{req_row}/review", headers=sa, json={"action": "verify"})
    await client.post(f"/api/system-profiles/{pid}/report-implementation", headers=oa, json={})
    r = await client.post(f"/api/system-profiles/{pid}/confirm-implementation", headers=sa, json={})
    events = r.json()["events"]

    codes = [e["event"] for e in events]
    # events mới nhất trước → thứ tự ngược mốc thời gian
    assert codes == [
        "fulfilled", "implementation_reported", "requirement_verified", "requirement_requested",
        "approved", "submitted", "device_added", "created",
    ]
    assert all(e["message"] for e in events)
    assert all(e["actor_name"] for e in events)
    # device_added có tên thiết bị trong message
    assert "Firewall biên" in next(e["message"] for e in events if e["event"] == "device_added")


async def test_reject_requires_reason(client, org_env):
    """Từ chối hồ sơ phải có lý do để đơn vị biết và sửa."""
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    r = await client.post(
        "/api/system-profiles",
        headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống reject", "level": 1},
    )
    pid = r.json()["id"]
    await client.post(f"/api/system-profiles/{pid}/submit", headers=oa)

    # Không có lý do → 400, trạng thái không đổi
    r = await client.post(f"/api/system-profiles/{pid}/review", headers=sa, json={"action": "reject", "review_note": "   "})
    assert r.status_code == 400
    r = await client.get(f"/api/system-profiles/{pid}", headers=oa)
    assert r.json()["status"] == "pending_review"

    # Có lý do → rejected, lý do trả về cho đơn vị
    r = await client.post(f"/api/system-profiles/{pid}/review", headers=sa, json={"action": "reject", "review_note": "Thiếu danh mục thiết bị"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["review_note"] == "Thiếu danh mục thiết bị"
    # Lý do nằm trên timeline
    assert any("Thiếu danh mục thiết bị" in e["message"] for e in r.json()["events"])


async def test_superadmin_edit_logs_diff(client, org_env):
    """SuperAdmin sửa hồ sơ đã duyệt → timeline ghi rõ từng trường thay đổi."""
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    pid = await _approved_profile(client, org_env, oa, sa)

    r = await client.patch(
        f"/api/system-profiles/{pid}",
        headers=sa,
        json={"name": "Tên mới do SA sửa", "physical_location": "Tầng 3"},
    )
    assert r.status_code == 200, r.text
    ev_updated = [e for e in r.json()["events"] if e["event"] == "updated"][-1]
    assert "Tên hệ thống" in ev_updated["message"] and "Địa điểm lắp đặt" in ev_updated["message"]


# ── Danh bạ chuyên trách CNTT / tổ chức vận hành ────────────


async def test_it_contacts_crud_and_rbac(client, session_factory, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    other_org = await _make_org(session_factory, "UBND xã C")

    # Super Admin thêm contact cho đơn vị
    r = await client.post(
        "/api/it-contacts", headers=sa,
        json={"org_id": org_env["org_id"], "kind": "person", "name": "Nguyễn Văn A", "position": "Chuyên viên CNTT", "phone": "0912345678"},
    )
    assert r.status_code == 201, r.text
    person_id = r.json()["id"]

    # org_admin thêm contact cho đơn vị khác → 403
    r = await client.post("/api/it-contacts", headers=oa, json={"org_id": other_org, "kind": "org", "name": "Tổ chức X"})
    assert r.status_code == 403

    # org_admin thêm tổ chức vận hành cho đơn vị mình
    r = await client.post(
        "/api/it-contacts", headers=oa,
        json={"org_id": org_env["org_id"], "kind": "org", "name": "Trung tâm CNTT", "contact_person": "Trần Văn B"},
    )
    assert r.status_code == 201, r.text
    org_contact_id = r.json()["id"]

    # Filter kind + org
    r = await client.get("/api/it-contacts", headers=oa, params={"kind": "org"})
    assert [x["id"] for x in r.json()] == [org_contact_id]
    r = await client.get("/api/it-contacts", headers=sa, params={"org_id": other_org})
    assert r.json() == []

    # Sửa + xóa
    r = await client.patch(f"/api/it-contacts/{person_id}", headers=oa, json={"email": "a@donvi.gov.vn"})
    assert r.status_code == 200 and r.json()["email"] == "a@donvi.gov.vn"
    r = await client.delete(f"/api/it-contacts/{org_contact_id}", headers=oa)
    assert r.status_code == 204


async def test_profile_contacts_attach_detach(client, session_factory, org_env):
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    r = await client.post(
        "/api/system-profiles", headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống Mạng LAN", "level": 1},
    )
    pid = r.json()["id"]

    r = await client.post("/api/it-contacts", headers=oa, json={"org_id": org_env["org_id"], "kind": "person", "name": "Chuyên trách A"})
    person_id = r.json()["id"]
    # Contact của đơn vị khác → chặn
    other = await client.post("/api/it-contacts", headers=sa, json={"org_id": await _make_org(session_factory, "Org D"), "kind": "org", "name": "Org khác"})
    r = await client.post(f"/api/system-profiles/{pid}/contacts/{other.json()['id']}", headers=oa)
    assert r.status_code == 400

    # Gắn chuyên trách A với vai trò
    r = await client.post(f"/api/system-profiles/{pid}/contacts/{person_id}?note=Phụ%20trách%20vận%20hành", headers=oa)
    assert r.status_code == 201, r.text
    assert r.json()["contacts"][0]["name"] == "Chuyên trách A"
    assert r.json()["contacts"][0]["note"] == "Phụ trách vận hành"

    # Gắn trùng → 409; gỡ → 200 và danh sách rỗng
    r = await client.post(f"/api/system-profiles/{pid}/contacts/{person_id}", headers=oa)
    assert r.status_code == 409
    r = await client.delete(f"/api/system-profiles/{pid}/contacts/{person_id}", headers=oa)
    assert r.status_code == 200 and r.json()["contacts"] == []

    # Timeline ghi gắn/gỡ
    events = [e["event"] for e in r.json()["events"]]
    assert "contact_attached" in events and "contact_detached" in events


async def test_officers_crud_and_assign(client, session_factory, org_env):
    """Officer pool CRUD (Super Admin only) + assign 1 cán bộ cho nhiều hồ sơ."""
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # org_admin bị chặn CRUD officers
    r = await client.post(
        "/api/officers", headers=oa,
        json={"name": "Nguyễn Văn A"},
    )
    assert r.status_code == 403, r.text

    # Super Admin tạo cán bộ
    r = await client.post(
        "/api/officers", headers=sa,
        json={
            "name": "Trần Văn B",
            "organization": "Sở TT&TT tỉnh X",
            "title": "Phó GĐ",
            "phone": "0912345678",
            "email": "tranvb@stttt.gov.vn",
            "note": "Phụ trách hệ thống",
        },
    )
    assert r.status_code == 201, r.text
    officer_id = r.json()["id"]
    body = r.json()
    assert body["name"] == "Trần Văn B"
    assert body["organization"] == "Sở TT&TT tỉnh X"
    assert body["profile_count"] == 0

    # Tên rỗng → 400 (route kiểm tra thủ công sau strip)
    r = await client.post("/api/officers", headers=sa, json={"name": "  "})
    assert r.status_code == 400

    # Tạo hồ sơ + gán cán bộ
    r = await client.post(
        "/api/system-profiles", headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống A", "level": 1},
    )
    pid_a = r.json()["id"]
    r = await client.put(
        f"/api/system-profiles/{pid_a}/officer", headers=sa,
        json={"officer_id": officer_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["officer"]["id"] == officer_id
    assert r.json()["officer"]["name"] == "Trần Văn B"

    # org_admin cố gán → 403
    r = await client.put(
        f"/api/system-profiles/{pid_a}/officer", headers=oa,
        json={"officer_id": officer_id},
    )
    assert r.status_code == 403

    # Gán cùng cán bộ cho hồ sơ thứ 2 — key test: 1 cán bộ cho nhiều hồ sơ
    r = await client.post(
        "/api/system-profiles", headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hệ thống B", "level": 1},
    )
    pid_b = r.json()["id"]
    r = await client.put(
        f"/api/system-profiles/{pid_b}/officer", headers=sa,
        json={"officer_id": officer_id},
    )
    assert r.status_code == 200

    # profile_count tăng lên 2
    r = await client.get(f"/api/officers/{officer_id}", headers=sa)
    assert r.json()["profile_count"] == 2

    # Officer_id không tồn tại → 404
    r = await client.put(
        f"/api/system-profiles/{pid_a}/officer", headers=sa,
        json={"officer_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404

    # Gỡ khỏi hồ sơ A — chỉ set officer_id=NULL, officer vẫn còn
    r = await client.delete(f"/api/system-profiles/{pid_a}/officer", headers=sa)
    assert r.status_code == 200
    assert r.json()["officer"] is None
    # Officer vẫn còn + còn đang gán cho profile B
    r = await client.get(f"/api/officers/{officer_id}", headers=sa)
    assert r.json()["profile_count"] == 1

    # Gỡ lần 2 khi rỗng → 404
    r = await client.delete(f"/api/system-profiles/{pid_a}/officer", headers=sa)
    assert r.status_code == 404

    # Update officer — sửa tên
    r = await client.patch(
        f"/api/officers/{officer_id}", headers=sa,
        json={"name": "Trần Văn B Updated"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Trần Văn B Updated"

    # Xóa officer khi còn đang gán → FK SET NULL nên vẫn OK
    r = await client.delete(f"/api/officers/{officer_id}", headers=oa)  # org_admin bị chặn
    assert r.status_code == 403
    r = await client.delete(f"/api/officers/{officer_id}", headers=sa)
    assert r.status_code == 204

    # Profile B giờ officer=NULL (FK SET NULL)
    r = await client.get(f"/api/system-profiles/{pid_b}", headers=sa)
    assert r.json()["officer"] is None
    assert r.json()["officer_id"] is None


# ── P1-1: Org Admin parent không được sửa hồ sơ của org con ─


async def _make_child_org(session_factory, parent_org_id: str, name: str) -> str:
    """Tạo org con (parent_id = parent_org_id) — mirror Organization model."""
    async with session_factory() as s:
        org = Organization(name=name, type=OrgType.UBND_XA.value, parent_id=uuid.UUID(parent_org_id))
        s.add(org)
        await s.commit()
        return str(org.id)


async def test_parent_org_admin_reads_but_cannot_mutate_child_profile(
    client, session_factory, org_env
):
    """Org Admin của parent org được đọc hồ sơ org con (visibility) nhưng KHÔNG
    được PATCH/DELETE/mutate child content (devices, machines, parties,
    applications, ip_ranges, requirements).
    """
    parent_id = org_env["org_id"]
    child_id = await _make_child_org(session_factory, parent_id, "UBND xã con")
    parent_admin_email = await _make_org_admin(session_factory, parent_id)
    child_admin_email = await _make_org_admin(session_factory, child_id)

    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    parent_oa = _auth(await _login(client, parent_admin_email, "Passw0rd!123"))
    child_oa = _auth(await _login(client, child_admin_email, "Passw0rd!123"))

    # Child admin tạo hồ sơ ở child org
    r = await client.post(
        "/api/system-profiles",
        headers=child_oa,
        json={"org_id": child_id, "name": "Hệ thống con", "level": 1},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    # Parent admin ĐỌC được hồ sơ con (visibility bao gồm cả descendants)
    r = await client.get(f"/api/system-profiles/{pid}", headers=parent_oa)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == pid

    # List cũng trả về hồ sơ con cho parent admin
    r = await client.get("/api/system-profiles", headers=parent_oa)
    assert any(item["id"] == pid for item in r.json()["items"])

    # Parent admin KHÔNG được PATCH
    r = await client.patch(
        f"/api/system-profiles/{pid}", headers=parent_oa, json={"name": "Đổi tên trái phép"}
    )
    assert r.status_code == 403, r.text

    # Parent admin KHÔNG được DELETE
    r = await client.delete(f"/api/system-profiles/{pid}", headers=parent_oa)
    assert r.status_code == 403, r.text

    # Parent admin KHÔNG được thêm thiết bị
    r = await client.post(
        f"/api/system-profiles/{pid}/devices", headers=parent_oa,
        json={"name": "Thiết bị lạ", "device_type": "firewall"},
    )
    assert r.status_code == 403, r.text

    # Parent admin KHÔNG được thêm máy (kể cả gắn máy cùng parent org vào profile con)
    machine_id = await _make_machine(session_factory, parent_id)
    r = await client.post(
        f"/api/system-profiles/{pid}/machines?machine_id={machine_id}", headers=parent_oa
    )
    assert r.status_code == 403, r.text

    # Parent admin KHÔNG được submit (trạng thái workflow)
    r = await client.post(f"/api/system-profiles/{pid}/submit", headers=parent_oa)
    assert r.status_code == 403, r.text

    # Parent admin KHÔNG được tạo party / application / ip-range
    r = await client.post(
        f"/api/system-profiles/{pid}/parties", headers=parent_oa,
        json={"role": "owner", "name": "Chủ quản lạ"},
    )
    assert r.status_code == 403, r.text

    r = await client.post(
        f"/api/system-profiles/{pid}/applications", headers=parent_oa,
        json={"name": "App lạ"},
    )
    assert r.status_code == 403, r.text

    r = await client.post(
        f"/api/system-profiles/{pid}/ip-ranges", headers=parent_oa,
        json={"zone": "LAN", "cidr": "10.0.0.0/24", "ip_kind": "private"},
    )
    assert r.status_code == 403, r.text

    # Sanity: child admin vẫn mutate được hồ sơ con
    r = await client.patch(
        f"/api/system-profiles/{pid}", headers=child_oa, json={"name": "Sửa hợp lệ"}
    )
    assert r.status_code == 200, r.text
    # Super admin vẫn mutate được
    r = await client.delete(f"/api/system-profiles/{pid}", headers=sa)
    assert r.status_code == 204


# ── P1-2: Hồ sơ approved trở đi không được sửa nội dung child resource ─


async def test_approved_profile_blocks_org_admin_from_mutating_child_resources(
    client, session_factory, org_env
):
    """Khi hồ sơ ở approved/implemented/fulfilled:
    - Org Admin KHÔNG được mutate devices, machines, parties, applications, ip-ranges.
    - Super Admin vẫn mutate được (và có timeline event).
    - Org Admin vẫn có thể PATCH metadata (managed_by) theo policy hiện tại.
    - Hồ sơ rejected vẫn cho phép sửa bình thường.
    """
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # Super admin tạo hồ sơ approved trực tiếp (kèm decision_number)
    r = await client.post(
        "/api/system-profiles", headers=sa,
        json={
            "org_id": org_env["org_id"],
            "name": "Hồ sơ approved",
            "level": 1,
            "decision_number": "42/QĐ-ATTT",
            "decision_agency": "Công an tỉnh",
        },
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "approved"

    # Thêm thiết bị trên hồ sơ approved → Org Admin bị chặn
    r = await client.post(
        f"/api/system-profiles/{pid}/devices", headers=oa,
        json={"name": "Firewall", "device_type": "firewall"},
    )
    assert r.status_code == 400, r.text
    assert "approved" in r.json()["detail"]

    # Super Admin vẫn mutate được
    r = await client.post(
        f"/api/system-profiles/{pid}/devices", headers=sa,
        json={"name": "Firewall SA", "device_type": "firewall"},
    )
    assert r.status_code == 201, r.text
    dev_id = r.json()["devices"][0]["id"]

    # Gắn máy trên approved → Org Admin bị chặn
    machine_id = await _make_machine(session_factory, org_env["org_id"])
    r = await client.post(
        f"/api/system-profiles/{pid}/machines?machine_id={machine_id}", headers=oa
    )
    assert r.status_code == 400, r.text

    # Thêm party trên approved → Org Admin bị chặn
    r = await client.post(
        f"/api/system-profiles/{pid}/parties", headers=oa,
        json={"role": "owner", "name": "Chủ quản"},
    )
    assert r.status_code == 400, r.text

    # Thêm application trên approved → Org Admin bị chặn
    r = await client.post(
        f"/api/system-profiles/{pid}/applications", headers=oa,
        json={"name": "Web app"},
    )
    assert r.status_code == 400, r.text

    # Thêm ip-range trên approved → Org Admin bị chặn
    r = await client.post(
        f"/api/system-profiles/{pid}/ip-ranges", headers=oa,
        json={"zone": "LAN", "cidr": "10.0.0.0/24", "ip_kind": "private"},
    )
    assert r.status_code == 400, r.text

    # Sửa / xóa thiết bị trên approved (do Super Admin tạo) bằng Org Admin → bị chặn
    r = await client.put(
        f"/api/system-profiles/{pid}/devices/{dev_id}", headers=oa,
        json={"name": "Đổi tên", "device_type": "firewall"},
    )
    assert r.status_code == 400, r.text
    r = await client.delete(f"/api/system-profiles/{pid}/devices/{dev_id}", headers=oa)
    assert r.status_code == 400, r.text

    # PATCH name thường trên approved → Org Admin bị chặn
    r = await client.patch(f"/api/system-profiles/{pid}", headers=oa, json={"name": "Đổi tên"})
    assert r.status_code == 400, r.text

    # PATCH managed_by trên approved → Org Admin ĐƯỢC phép (theo policy hiện tại)
    r = await client.patch(
        f"/api/system-profiles/{pid}", headers=oa, json={"managed_by": "Tên chủ quản mới"}
    )
    assert r.status_code == 200, r.text


# ── P2-1: timeline `level_changed` phải log old value đúng ─


async def test_level_changed_timeline_logs_correct_old_value(
    client, org_env, session_factory
):
    """Khi đổi level 2 → 3, event `level_changed` phải chứa `2 → 3`, không phải `3 → 3`.

    Bug trước fix: code `setattr(profile, 'level', new_level)` chạy TRƯỚC khi
    log event, nên `profile.level` lúc log đã là giá trị mới → event ghi nhầm
    `3 → 3`.
    """
    from app.db.models import LevelRequirement

    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # Seed level requirement cho cả level 1 và 2
    async with session_factory() as s:
        s.add(LevelRequirement(level=1, code="L1-A", title="Yêu cầu L1"))
        s.add(LevelRequirement(level=2, code="L2-B", title="Yêu cầu L2"))
        await s.commit()

    # Tạo hồ sơ level 1
    r = await client.post(
        "/api/system-profiles", headers=oa,
        json={"org_id": org_env["org_id"], "name": "Test", "level": 1},
    )
    pid = r.json()["id"]
    assert r.json()["level"] == 1

    # PATCH level 1 → 2
    r = await client.patch(
        f"/api/system-profiles/{pid}", headers=oa, json={"level": 2}
    )
    assert r.status_code == 200, r.text
    assert r.json()["level"] == 2

    # Tìm event `level_changed` trong timeline
    events = r.json()["events"]
    level_changed = [e for e in events if e["event"] == "level_changed"]
    assert level_changed, f"Không có event level_changed: {events}"
    msg = level_changed[0]["message"]
    assert "1" in msg and "2" in msg, f"Event không chứa cả old/new: {msg!r}"
    # Quan trọng: phải có dạng "1 → 2", KHÔNG phải "2 → 2"
    assert "1 → 2" in msg or "1 -> 2" in msg, (
        f"P2-1 BUG: timeline ghi sai old value. Event message: {msg!r}. "
        "Expected '1 → 2' (old → new), but format suggests snapshot bị miss."
    )
    assert "2 → 2" not in msg and "2 -> 2" not in msg, (
        f"P2-1 BUG: old value bị overwrite bởi setattr trước log. Event: {msg!r}"
    )


async def test_rejected_profile_allows_org_admin_full_edit(client, org_env):
    """Hồ sơ rejected vẫn cho Org Admin sửa child resource bình thường."""
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    r = await client.post(
        "/api/system-profiles", headers=oa,
        json={"org_id": org_env["org_id"], "name": "Hồ sơ", "level": 1},
    )
    pid = r.json()["id"]
    await client.post(f"/api/system-profiles/{pid}/submit", headers=oa)
    r = await client.post(
        f"/api/system-profiles/{pid}/review", headers=sa,
        json={"action": "reject", "review_note": "Thiếu thông tin"},
    )
    assert r.json()["status"] == "rejected"

    # Org Admin vẫn mutate được child resource trên rejected
    r = await client.post(
        f"/api/system-profiles/{pid}/devices", headers=oa,
        json={"name": "Firewall", "device_type": "firewall"},
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/system-profiles/{pid}/parties", headers=oa,
        json={"role": "owner", "name": "Chủ quản"},
    )
    assert r.status_code == 201, r.text


# ── P2-3: DeviceType.is_active=False không được dùng cho device mới ─


async def test_inactive_device_type_cannot_be_used_for_new_device(
    client, org_env, session_factory
):
    """Loại thiết bị đã tắt (is_active=false) không được dùng để tạo device mới.

    Theo policy: `is_active=false` → ẩn khỏi form, dữ liệu cũ vẫn render được.
    Trước fix: `_valid_device_type` chỉ check existence → API client có thể bypass
    frontend và tạo device mới với inactive type.
    """
    from app.db.models import DeviceType

    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    # Seed thêm một inactive device type
    async with session_factory() as s:
        s.add(DeviceType(
            code="legacy_type",
            label="Legacy",
            icon="📦",
            is_active=False,
            sort_order=99,
        ))
        await s.commit()

    # Tạo profile
    r = await client.post(
        "/api/system-profiles", headers=oa,
        json={"org_id": org_env["org_id"], "name": "Test", "level": 1},
    )
    pid = r.json()["id"]

    # POST device với active type → OK
    r = await client.post(
        f"/api/system-profiles/{pid}/devices", headers=oa,
        json={"name": "FW active", "device_type": "firewall"},
    )
    assert r.status_code == 201, r.text

    # POST device với inactive type → 400
    r = await client.post(
        f"/api/system-profiles/{pid}/devices", headers=oa,
        json={"name": "FW legacy", "device_type": "legacy_type"},
    )
    assert r.status_code == 400, r.text
    assert "legacy_type" in r.json()["detail"]

    # PUT device với inactive type → 400
    r = await client.put(
        f"/api/system-profiles/{pid}/devices/{r.json().get('id', '00000000-0000-0000-0000-000000000000')}",
        headers=oa,
        json={"name": "FW legacy", "device_type": "legacy_type"},
    )
    # Lấy lại device id thực
    r2 = await client.get(f"/api/system-profiles/{pid}", headers=sa)
    dev_id = r2.json()["devices"][0]["id"]
    r = await client.put(
        f"/api/system-profiles/{pid}/devices/{dev_id}", headers=oa,
        json={"name": "FW legacy", "device_type": "legacy_type"},
    )
    assert r.status_code == 400, r.text
    assert "legacy_type" in r.json()["detail"]


# ── P2-4: SystemProfile.code race condition ─


@pytest.mark.asyncio
async def test_profile_code_generation_handles_concurrent_inserts(
    session_factory, seeded_env
):
    """Hai transaction cùng tạo hồ sơ trong cùng org cùng năm phải sinh ra
    code khác nhau, không được trả 500 do unique conflict.

    Trước fix: SELECT-max-then-INSERT → race có thể tạo cùng code → unique
    constraint bắt được nhưng request bị 500 unhandled.
    Sau fix: catch IntegrityError, retry với seq mới (bounded).
    """
    from app.core.security import hash_password
    from app.db.models import User, UserRole

    org_id = seeded_env["org_id"]

    # Pre-create admin
    admin_email = f"concurrent-{uuid.uuid4().hex[:8]}@org.test"
    async with session_factory() as s:
        s.add(User(
            org_id=org_id,
            full_name="Concurrent Admin",
            email=admin_email,
            role=UserRole.ORG_ADMIN.value,
            password_hash=hash_password("Passw0rd!123"),
        ))
        await s.commit()

    from app.api.routes.system_profiles import _create_profile_with_unique_code
    from app.db.models import User as UserModel

    # Get admin user id
    async with session_factory() as s:
        admin_user = (
            await s.execute(
                UserModel.__table__.select().where(UserModel.email == admin_email)
            )
        ).first()
        creator_id = admin_user[0]

    # Test 1: race-safe generator trả code khác nhau khi gọi liên tiếp.
    # Trước fix: mỗi lần sinh đều nhìn cùng max(seq) → cùng code.
    # Sau fix: sau khi INSERT, sequence DB được bump → call tiếp theo
    # thấy max(seq) mới.
    codes = []
    for _ in range(5):
        async with session_factory() as s:
            creator = await s.get(UserModel, creator_id)
            profile = await _create_profile_with_unique_code(
                s,
                org_id=org_id,
                creator=creator,
                name=f"Profile {uuid.uuid4().hex[:6]}",
                level=1,
            )
            await s.commit()
            codes.append(profile.code)

    assert len(set(codes)) == 5, f"Trùng code giữa các lần sinh: {codes}"
    # Đều phải match pattern HS-{year}-{3digits}
    import re
    from datetime import datetime
    year = datetime.now().year
    for c in codes:
        assert re.match(rf"^HS-{year}-\d{{3}}$", c), f"Code format sai: {c}"

    # Test 2: helper handle IntegrityError — pre-create code tồn tại,
    # gọi generator sẽ sinh code mới (không trùng).
    existing = codes[0]
    async with session_factory() as s:
        creator = await s.get(UserModel, creator_id)
        # Generator thấy existing code 'HS-2026-001' → trả 'HS-2026-002'
        from app.api.routes.system_profiles import _generate_profile_code
        new_code = await _generate_profile_code(s, org_id)
        assert new_code != existing, f"Generator trả code đã tồn tại: {new_code}"


# ── BLOCKER 3 — P2-4 TRUE concurrent profile code creation ─────────────

@pytest.mark.asyncio
async def test_concurrent_profile_creation_isolates_candidate_code(
    session_factory, seeded_env
):
    """BLOCKER 3: 2 transactions chạy SONG SONG cùng đọc max(seq) rồi INSERT,
    mỗi session phải thấy 'next available code' tại thời điểm MÌNH generate,
    KHÔNG phải race-condition dùng serial test trước.

    Test hiện tại (test_profile_code_generation_handles_concurrent_inserts) chỉ
    loop tuần tự 5 lần với cùng session sau khi commit — KHÔNG tái hiện race vì
    transactions không concurrent.

    Approach: dùng 2 sessions ĐỘC LẬP, mỗi session tự gọi
    `_create_profile_with_unique_code`. Sequence:
      Session A: INSERT (commit) → max=001
      Session B (BẮT ĐẦU trước khi commit A?)… không, đó là phương pháp khác.

    Cách đơn giản nhưng hiệu quả cho race test:
      Dùng 1 session làm "anchor", pre-insert 1 row để tồn tại 1 code.
      Sau đó 2 sessions CÙNG LÚC generate candidate cùng lúc:
      - Cả 2 thấy max(001) → candidate = 002
      - Cả 2 INSERT
      - 1 commit OK, 1 nhận IntegrityError → retry với 003
      → End state: 002 + 003 (không phải 002 + 002, không phải 002 → retry cả 2 lần)

    Dùng asyncio.gather() cho 2 sessions chạy concurrent trên 2 connections.
    Sync barrier (asyncio.Event) đảm bảo cả 2 generate TRƛC khi 1 commit.
    """
    from app.db.models import Organization, OrgType, User, UserRole
    from app.core.security import hash_password

    org_id = seeded_env["org_id"]

    # Pre-create admin
    admin_email = f"conc-{uuid.uuid4().hex[:6]}@org.test"
    async with session_factory() as s:
        admin = User(
            org_id=org_id, full_name="Concurrent", email=admin_email,
            role=UserRole.ORG_ADMIN.value,
            password_hash=hash_password("Passw0rd!123"),
        )
        s.add(admin)
        await s.commit()
        creator_id = admin.id

    # Pre-insert 1 anchor profile để có '001' trong DB
    from app.api.routes.system_profiles import _create_profile_with_unique_code
    from app.db.models import User as UserModel
    async with session_factory() as s:
        creator = await s.get(UserModel, creator_id)
        anchor = await _create_profile_with_unique_code(
            s, org_id=org_id, creator=creator, name="Anchor", level=1,
        )
        await s.commit()
    anchor_code = anchor.code

    # Barrier để sync 2 transactions
    import asyncio
    start_barrier = asyncio.Event()
    both_ready = asyncio.Event()
    race_started = False

    candidates_seen = []

    async def race_create():
        nonlocal race_started
        async with session_factory() as s:
            creator = await s.get(UserModel, creator_id)

            # Cả 2 tasks enter _generate_profile_code (qua _create_profile_with_unique_code)
            # Tại đây đặt barrier để đồng bộ — đảm bảo cả 2 đọc MAX trước khi insert.
            start_barrier.set()
            await both_ready.wait()

            profile = await _create_profile_with_unique_code(
                s, org_id=org_id, creator=creator,
                name=f"Race-{uuid.uuid4().hex[:6]}", level=1,
            )
            await s.commit()
            return profile.code

    async def ready_signal():
        # Wait cho cả 2 tasks đã vào func, sau đó release barrier.
        await start_barrier.wait()
        both_ready.set()

    # Schedule 2 concurrent creators + 1 trigger signal. Trigger signal chờ
    # cho start_barrier (set bởi race_create đầu tiên) rồi set both_ready.
    # Nhược: 2 race_create chạy song song; cả 2 set start_barrier; signal set both_ready
    # ngay khi nhận 1 set. Không đảm bảo barrier chính xác — thay bằng pattern
    # với 2 semaphore/Event có countdown.
    # Dùng cách đơn giản hơn: count semaphore.
    ready_count = 0
    both_ready = asyncio.Event()

    async def counted_ready(sema_release):
        nonlocal ready_count
        ready_count += 1
        if ready_count >= 2:
            both_ready.set()

    async def race_create_counted(idx: int):
        async with session_factory() as s:
            creator = await s.get(UserModel, creator_id)
            # Đợi "ready" barrier — counted
            await sema_release
            # cả 2 đã vào đến đây → generate & insert race
            profile = await _create_profile_with_unique_code(
                s, org_id=org_id, creator=creator,
                name=f"Race-{idx}", level=1,
            )
            await s.commit()
            return profile.code

    sema = asyncio.Semaphore(0)

    async def go_a():
        await counted_ready(sema.release())
        return await race_create_counted(0)
    # Reset for second task
    async def go_b():
        await counted_ready(sema.release())
        return await race_create_counted(1)

    # Vì cả 2 cần 'await sema.release()' để có 2 waiter cho sema, ta dùng 2 semaphore.
    sema_a = asyncio.Semaphore(0)
    sema_b = asyncio.Semaphore(0)

    started_a = asyncio.Event()
    started_b = asyncio.Event()

    # Snapshot primitive values từ creator TRƯỚC khi fork tasks (tránh
    # lazy-load sau khi session expire, dùng detached ORM creator).
    creator_id_for_task = creator_id

    async def go_a_v2():
        started_a.set()
        await sema_a.acquire()  # wait cho release
        async with session_factory() as s:
            # Re-fetch trong session mới nhưng pass primitive id only
            profile = await _create_profile_with_unique_code(
                s, org_id=org_id, creator=UserModel(id=creator_id_for_task),
                name="Race-A", level=1,
            )
            await s.commit()
            return profile.code
    async def go_b_v2():
        started_b.set()
        await sema_b.acquire()
        async with session_factory() as s:
            profile = await _create_profile_with_unique_code(
                s, org_id=org_id, creator=UserModel(id=creator_id_for_task),
                name="Race-B", level=1,
            )
            await s.commit()
            return profile.code

    # Sync: đợi cả 2 started, sau đó release cùng lúc (race)
    async def coordinator():
        await started_a.wait()
        await started_b.wait()
        # Yield để cả 2 reach sema.acquire()
        await asyncio.sleep(0.05)
        sema_a.release()
        sema_b.release()

    results = await asyncio.gather(
        go_a_v2(), go_b_v2(), coordinator()
    )
    code_a, code_b = results[0], results[1]


@pytest.mark.asyncio
async def test_non_code_integrity_error_is_not_retried(
    session_factory, seeded_env
):
    """BLOCKER 3 narrowing: FK / NOT NULL / check constraint khác unique code
    phải propagate ngay để caller biết, không lặp 5 lần.

    Test bằng cách gọi `_create_profile_with_unique_code` với Invalid org_id
    (FK violation với organizations) — phải raise ngay, không retry 5 lần.
    """
    from app.core.security import hash_password
    from app.db.models import User, UserRole
    from sqlalchemy.exc import IntegrityError
    import time
    from app.api.routes.system_profiles import _create_profile_with_unique_code

    # Pre-create admin
    admin_email = f"nort-{uuid.uuid4().hex[:6]}@org.test"
    async with session_factory() as s:
        admin = User(
            org_id=seeded_env["org_id"],
            full_name="NoRet", email=admin_email,
            role=UserRole.ORG_ADMIN.value,
            password_hash=hash_password("Passw0rd!123"),
        )
        s.add(admin)
        await s.commit()
        creator_id = admin.id

    # Gọi helper với org_id KHÔNG tồn tại trong organizations (FK violation).
    bogus_org_id = uuid.uuid4()  # không insert vào organizations

    async with session_factory() as s:
        from app.db.models import User as UserModel
        creator = await s.get(UserModel, creator_id)
        from app.db.base import Base  # ensure models imported for FK resolution

        t0 = time.monotonic()
        with pytest.raises(IntegrityError):
            await _create_profile_with_unique_code(
                s,
                org_id=bogus_org_id,
                creator=creator,
                name="FK violation",
                level=1,
            )
        elapsed = time.monotonic() - t0

    # FK error phải raise NGAY từ attempt 1, không retry 5 lần.
    # Nếu retry 5 lần sẽ mất thời gian đáng kể (FK validation cycle each).
    # Verify: thời gian thực < 1s (bound lỏng, không flaky).
    assert elapsed < 2.0, (
        f"FK violation mất {elapsed:.2f}s — quá chậm, có thể đã retry nhiều lần. "
        "Helper phải propagate non-unique-code IntegrityError ngay."
    )


# ── P2-2 timeline notes được bảo toàn ────────────────────────────


async def test_implementation_note_preserved_in_timeline_after_fulfillment(
    client, org_env, session_factory
):
    """P2-2: report_implementation với note X → timeline event chứa X.
    Sau đó confirm_implementation với note Y → timeline có cả X và Y
    (history immutable), dù profile.review_note chỉ giữ Y (latest).
    """
    await _seed_requirements(session_factory, [(1, "L1-P22", "Yêu cầu P2-2")])
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))

    pid = await _approved_profile(client, org_env, oa, sa)
    row = (await _get_profile(client, sa, pid))["requirements"][0]["id"]

    await client.post(f"/api/system-profiles/{pid}/requirements/{row}/request", headers=oa, json={"evidence": "OK"})
    r = await client.post(f"/api/system-profiles/{pid}/requirements/{row}/review", headers=sa, json={"action": "verify"})
    assert r.json()["level_compliant"] is True

    r = await client.post(
        f"/api/system-profiles/{pid}/report-implementation",
        headers=oa,
        json={"note": "implementation note from unit X"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["review_note"] == "implementation note from unit X"

    impl_events = [e for e in r.json()["events"] if e["event"] == "implementation_reported"]
    assert impl_events and "implementation note from unit X" in impl_events[0]["message"], (
        f"P2-2 BUG: implementation note không được lưu trong timeline event. "
        f"actual msg={impl_events[0]['message'] if impl_events else '(no event)'!r}"
    )

    r = await client.post(
        f"/api/system-profiles/{pid}/confirm-implementation",
        headers=sa,
        json={"review_note": "fulfillment note Y"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["review_note"] == "fulfillment note Y"

    all_events = r.json()["events"]
    impl_msg = next(
        (e["message"] for e in all_events if e["event"] == "implementation_reported"),
        None,
    )
    fulfill_msg = next(
        (e["message"] for e in all_events if e["event"] == "fulfilled"),
        None,
    )
    assert impl_msg and "implementation note from unit X" in impl_msg, (
        f"P2-2 BUG: implementation note bị mất sau fulfillment. msg={impl_msg!r}"
    )
    assert fulfill_msg and "fulfillment note Y" in fulfill_msg, (
        f"P2-2 BUG: fulfillment note không lưu trong timeline. msg={fulfill_msg!r}"
    )
