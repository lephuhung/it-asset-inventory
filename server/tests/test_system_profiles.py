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


async def test_implementation_flow_and_stats(client, org_env):
    """approved → (đơn vị khai báo) implemented → (super admin) fulfilled; stats đúng."""
    oa = _auth(await _login(client, org_env["org_admin_email"], "Passw0rd!123"))
    sa = _auth(await _login(client, org_env["email"], org_env["password"]))
    pid = await _approved_profile(client, org_env, oa, sa)

    # Super admin không confirm được khi hồ sơ còn approved
    r = await client.post(f"/api/system-profiles/{pid}/confirm-implementation", headers=sa, json={})
    assert r.status_code == 400

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
