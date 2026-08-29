"""Test hệ thống tag máy: phân loại (cá nhân / công vụ / BMNN) + tag mục đích.

Các ràng buộc được kiểm chứng:
- Mỗi máy có ĐÚNG 1 tag classification; đổi loại = thay tag cũ.
- Máy cá nhân KHÔNG tính vào công vụ; BMNN là công vụ (official + bmnn).
- Tag mục đích (purpose) nhiều/máy, KHÔNG ảnh hưởng thống kê công vụ.
- Token sinh với loại máy + tag mục đích → áp cho máy khi enroll (mặc định công vụ).
- RBAC: chỉ admin được gán tag.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.db.models import Machine, MachineTag, Tag, TagKind, User, UserRole
from app.services.tags import ensure_system_tags


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _make_machine(session_factory, org_id, uuid_str, status="online"):
    async with session_factory() as s:
        m = Machine(
            org_id=org_id,
            machine_uuid=uuid_str,
            hostname=f"PC-{uuid_str[:6]}",
            status=status,
            fingerprint={"smbios_uuid": uuid_str},
            enrolled_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()
        return str(m.id)


async def _seed_tags(session_factory):
    """Seed 3 tag phân loại hệ thống + 1 tag mục đích (như app startup)."""
    async with session_factory() as s:
        await ensure_system_tags(s)
        exists = (
            await s.execute(select(Tag).where(Tag.key == "dich_vu_cong"))
        ).scalar_one_or_none()
        if exists is None:
            s.add(Tag(key="dich_vu_cong", label="Dịch vụ công", kind=TagKind.PURPOSE.value, is_system=False))
            await s.commit()


async def _tag_keys(session_factory, machine_id) -> tuple[str | None, list[str]]:
    """(classification key, purpose keys) của máy."""
    async with session_factory() as s:
        rows = (
            await s.execute(
                select(Tag.key, Tag.kind)
                .join(MachineTag, MachineTag.tag_id == Tag.id)
                .where(MachineTag.machine_id == uuid.UUID(machine_id))
            )
        ).all()
    cls = next((k for k, kind in rows if kind == "classification"), None)
    purpose = sorted(k for k, kind in rows if kind == "purpose")
    return cls, purpose


# ── Seed & list ────────────────────────────────────────────────


async def test_seed_classification_tags(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.get("/api/tags", headers=_auth(token))
    assert r.status_code == 200, r.text
    keys = {t["key"]: t for t in r.json()}
    assert {"personal", "official", "bmnn"} <= set(keys)
    for k in ("personal", "official", "bmnn"):
        assert keys[k]["kind"] == "classification"
        assert keys[k]["is_system"] is True


# ── Gán tag qua API (1 máy + bulk) ─────────────────────────────


async def test_set_classification_and_purpose(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    mid = await _make_machine(session_factory, uuid.UUID(seeded_env["org_id"]), "uuid-tag-01")

    # Gán personal + purpose
    r = await client.put(
        f"/api/machines/{mid}/tags",
        json={"classification": "personal", "purpose": ["dich_vu_cong"]},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    cls, purpose = await _tag_keys(session_factory, mid)
    assert cls == "personal"
    assert purpose == ["dich_vu_cong"]

    # Đổi classification → official: tag cũ personal phải bị THAY (không phải thêm)
    r = await client.put(
        f"/api/machines/{mid}/tags",
        json={"classification": "official"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    cls, purpose = await _tag_keys(session_factory, mid)
    assert cls == "official"
    assert purpose == ["dich_vu_cong"]  # purpose giữ nguyên (không đụng)

    # Classification không hợp lệ → 422
    r = await client.put(
        f"/api/machines/{mid}/tags",
        json={"classification": "to_may_bay"},
        headers=_auth(token),
    )
    assert r.status_code == 422

    # Đếm: chỉ có ĐÚNG 1 tag classification
    async with session_factory() as s:
        n = len(
            (
                await s.execute(
                    select(MachineTag).where(
                        MachineTag.machine_id == uuid.UUID(mid),
                        MachineTag.kind == "classification",
                    )
                )
            ).scalars().all()
        )
    assert n == 1


async def test_bulk_tag(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org = uuid.UUID(seeded_env["org_id"])
    mid1 = await _make_machine(session_factory, org, "uuid-bulk-1")
    mid2 = await _make_machine(session_factory, org, "uuid-bulk-2")

    r = await client.post(
        "/api/machines/tags/bulk",
        json={"machine_ids": [mid1, mid2], "classification": "bmnn", "purpose": ["dich_vu_cong"]},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    cls1, _ = await _tag_keys(session_factory, mid1)
    cls2, _ = await _tag_keys(session_factory, mid2)
    assert cls1 == "bmnn" and cls2 == "bmnn"


# ── Enroll: token mang loại máy → áp cho máy ───────────────────


async def _enroll_with_token(client, enroll_token, fp_uuid: str, fp_serial: str):
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "machine-tag")]))
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()
    r = await client.post(
        "/api/enroll",
        json={
            "token": enroll_token,
            "csr_pem": csr_pem,
            "fingerprint": {"smbios_uuid": fp_uuid, "mainboard_serial": fp_serial},
            "hostname": f"PC-{fp_uuid[:6]}",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["machine_id"]


async def test_enroll_applies_token_classification(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    # Token chọn loại "personal" + tag mục đích
    r = await client.post(
        "/api/tokens",
        json={"org_id": org_id, "classification": "personal", "purpose_tags": ["dich_vu_cong"], "ttl_hours": 72},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    mid = await _enroll_with_token(client, r.json()["token"], "ENROLL-ONE-AAAA-1111", "SERIAL-ONE")
    cls, purpose = await _tag_keys(session_factory, mid)
    assert cls == "personal"
    assert purpose == ["dich_vu_cong"]

    # Token KHÔNG chọn loại → mặc định công vụ (fingerprint khác hẳn — máy mới)
    r = await client.post(
        "/api/tokens",
        json={"org_id": org_id, "ttl_hours": 72},
        headers=_auth(token),
    )
    mid2 = await _enroll_with_token(client, r.json()["token"], "ENROLL-TWO-BBBB-2222", "SERIAL-TWO")
    cls2, purpose2 = await _tag_keys(session_factory, mid2)
    assert cls2 == "official"
    assert purpose2 == []


# ── Thống kê ───────────────────────────────────────────────────


async def test_stats_overview_classification(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org = uuid.UUID(seeded_env["org_id"])

    # 3 máy: 1 personal, 1 official, 1 bmnn (+ 1 máy có purpose tag)
    for u in ("uuid-st-1", "uuid-st-2", "uuid-st-3", "uuid-st-4"):
        await _make_machine(session_factory, org, u)
    # Gán tag qua API cho các máy vừa tạo (dùng uuid chính xác)
    async def _set(uuid_str, cls):
        async with session_factory() as s:
            m = (await s.execute(select(Machine).where(Machine.machine_uuid == uuid_str))).scalar_one()
            from app.services.tags import set_machine_classification, set_machine_purpose_tags

            await set_machine_classification(s, m.id, cls)
            if uuid_str == "uuid-st-4":
                await set_machine_purpose_tags(s, m.id, ["dich_vu_cong"])
            await s.commit()

    await _set("uuid-st-1", "personal")
    await _set("uuid-st-2", "official")
    await _set("uuid-st-3", "bmnn")
    await _set("uuid-st-4", "official")  # có purpose tag nhưng vẫn official

    r = await client.get("/api/stats/overview", headers=_auth(token))
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["personal"] == 1
    assert s["official"] == 2  # uuid-st-2 + uuid-st-4 (có purpose nhưng vẫn công vụ)
    assert s["bmnn"] == 1
    # Công vụ thực tế = official + bmnn; tag mục đích KHÔNG đổi số
    assert s["total_machines"] == 4

    # Thêm purpose tag cho máy personal → thống kê KHÔNG đổi
    await _set("uuid-st-1", "personal")
    async with session_factory() as s:
        m = (await s.execute(select(Machine).where(Machine.machine_uuid == "uuid-st-1"))).scalar_one()
        from app.services.tags import set_machine_purpose_tags

        await set_machine_purpose_tags(s, m.id, ["dich_vu_cong"])
        await s.commit()
    r = await client.get("/api/stats/overview", headers=_auth(token))
    s2 = r.json()
    assert s2["personal"] == 1 and s2["official"] == 2 and s2["bmnn"] == 1


async def test_org_machine_stats(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org = uuid.UUID(seeded_env["org_id"])

    for u in ("uuid-org-1", "uuid-org-2", "uuid-org-3"):
        await _make_machine(session_factory, org, u)
    async with session_factory() as s:
        for u, cls in [("uuid-org-1", "personal"), ("uuid-org-2", "official"), ("uuid-org-3", "bmnn")]:
            m = (await s.execute(select(Machine).where(Machine.machine_uuid == u))).scalar_one()
            from app.services.tags import set_machine_classification

            await set_machine_classification(s, m.id, cls)
        await s.commit()

    r = await client.get("/api/orgs/machine-stats", headers=_auth(token))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["items"] if str(x["org_id"]) == seeded_env["org_id"])
    assert row["personal"] == 1
    assert row["official"] == 1
    assert row["bmnn"] == 1
    assert row["total"] == 3


async def test_machines_list_tag_filter(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org = uuid.UUID(seeded_env["org_id"])
    for u in ("uuid-flt-1", "uuid-flt-2"):
        await _make_machine(session_factory, org, u)
    async with session_factory() as s:
        for u, cls in [("uuid-flt-1", "personal"), ("uuid-flt-2", "official")]:
            m = (await s.execute(select(Machine).where(Machine.machine_uuid == u))).scalar_one()
            from app.services.tags import set_machine_classification

            await set_machine_classification(s, m.id, cls)
        await s.commit()

    r = await client.get("/api/machines?tag=personal", headers=_auth(token))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["machine_uuid"] == "uuid-flt-1"
    # List trả kèm tags
    assert any(t["key"] == "personal" for t in items[0]["tags"])


# ── RBAC ───────────────────────────────────────────────────────


async def test_viewer_cannot_set_tags(client, session_factory, seeded_env):
    await _seed_tags(session_factory)
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    org = uuid.UUID(seeded_env["org_id"])
    mid = await _make_machine(session_factory, org, "uuid-rbac-1")

    # Tạo viewer (password hợp lệ để đăng nhập)
    from app.core.security import hash_password

    async with session_factory() as s:
        v = User(
            org_id=org,
            full_name="Viewer Test",
            email="viewer-tag@example.gov.vn",
            role=UserRole.VIEWER.value,
            password_hash=hash_password("viewer-pass-123"),
        )
        s.add(v)
        await s.commit()

    r = await client.post("/api/auth/login", json={"email": "viewer-tag@example.gov.vn", "password": "viewer-pass-123"})
    assert r.status_code == 200, r.text
    viewer_token = r.json()["access_token"]

    # Viewer đọc được tag
    r = await client.get("/api/tags", headers=_auth(viewer_token))
    assert r.status_code == 200

    # Viewer không gán được tag
    r = await client.put(
        f"/api/machines/{mid}/tags",
        json={"classification": "personal"},
        headers=_auth(viewer_token),
    )
    assert r.status_code == 403
