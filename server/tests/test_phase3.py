"""Test Phase 3: lifecycle, pending approval, fingerprint drift, rescan, offline import."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.db.models import (
    FingerprintDrift,
    Machine,
)


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _make_machine(session_factory, org_id, uuid_str, status="pending", fingerprint=None):
    async with session_factory() as s:
        m = Machine(
            org_id=org_id,
            machine_uuid=uuid_str,
            hostname=f"PC-{uuid_str[:4]}",
            status=status,
            fingerprint=fingerprint or {"smbios_uuid": uuid_str},
            enrolled_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()
        return str(m.id)


# ── Lifecycle & approval ───────────────────────────────────────


async def test_lifecycle_and_approve(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])
    mid = await _make_machine(session_factory, org_id, "uuid-life-1", status="pending")

    r = await client.patch(
        f"/api/machines/{mid}/lifecycle",
        json={"lifecycle": "in_repair", "note": "Thay nguồn"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle"] == "in_repair"

    # Approve máy pending → in_use + online (last_seen mới)
    r = await client.post(f"/api/machines/{mid}/approve", json={}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "online"
    async with session_factory() as s:
        m = (await s.execute(select(Machine).where(Machine.id == uuid.UUID(mid)))).scalar_one()
        assert m.lifecycle == "in_use"

    # Approve lần nữa → 400
    r = await client.post(f"/api/machines/{mid}/approve", json={}, headers=_auth(token))
    assert r.status_code == 400

    # Reject máy pending khác → decommissioned
    mid2 = await _make_machine(session_factory, org_id, "uuid-life-2", status="pending")
    r = await client.post(f"/api/machines/{mid2}/reject", json={"note": "Máy lạ"}, headers=_auth(token))
    assert r.status_code == 200
    async with session_factory() as s:
        m = (await s.execute(select(Machine).where(Machine.id == uuid.UUID(mid2)))).scalar_one()
        assert m.status == "decommissioned"


# ── Fingerprint drift ──────────────────────────────────────────


async def test_fingerprint_drift_approve(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])
    mid = await _make_machine(
        session_factory, org_id, "uuid-drift-old",
        fingerprint={"smbios_uuid": "OLD-111", "machine_guid": "M1"},
    )

    async with session_factory() as s:
        s.add(
            FingerprintDrift(
                machine_id=uuid.UUID(mid),
                old_fingerprint={"smbios_uuid": "OLD-111"},
                new_fingerprint={"smbios_uuid": "NEW-222", "machine_guid": "M2"},
                reason="os_reinstall",
            )
        )
        await s.commit()

    r = await client.get("/api/drifts", headers=_auth(token))
    assert r.status_code == 200
    assert len(r.json()) == 1
    drift_id = r.json()[0]["id"]

    r = await client.post(f"/api/drifts/{drift_id}/approve", json={}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    async with session_factory() as s:
        m = (await s.execute(select(Machine).where(Machine.id == uuid.UUID(mid)))).scalar_one()
        assert m.fingerprint["smbios_uuid"] == "NEW-222"
        assert m.machine_uuid != "uuid-drift-old"

    # Approve lần 2 → 400 (đã xử lý)
    r = await client.post(f"/api/drifts/{drift_id}/approve", json={}, headers=_auth(token))
    assert r.status_code == 400


# ── On-demand rescan ───────────────────────────────────────────


async def test_request_rescan(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])
    mid = await _make_machine(session_factory, org_id, "uuid-scan-1", status="offline")
    r = await client.post(f"/api/machines/{mid}/rescan", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert "rescan" in r.json()["message"].lower() or "thu thập" in r.json()["message"]


# ── Offline import (máy cách ly) ───────────────────────────────


def _sign_payload(payload: dict, private_key) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    sig = private_key.sign(hashlib.sha256(canonical).digest(), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()


async def test_offline_import_verified(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    payload = {
        "machine_uuid": "offline-uuid-1",
        "hostname": "PC-ISOLATED",
        "org_id": seeded_env["org_id"],
        "fingerprint": {"smbios_uuid": "OFF-1", "machine_guid": "OFF-G"},
        "spec": {
            "os_name": "Windows 10",
            "os_build": "19045",
            "cpu": {"model": "Core i5"},
            "ram_gb": 8,
        },
        "exported_at": datetime.now(UTC).isoformat(),
    }
    r = await client.post(
        "/api/offline/import",
        json={
            "payload": payload,
            "signature_b64": _sign_payload(payload, private_key),
            "public_key_pem": public_key_pem,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_new"] is True and data["verified"] is True

    # File bị sửa sau khi ký → từ chối (400)
    tampered = dict(payload)
    tampered["hostname"] = "PC-HACKED"
    r = await client.post(
        "/api/offline/import",
        json={
            "payload": tampered,
            "signature_b64": _sign_payload(payload, private_key),
            "public_key_pem": public_key_pem,
        },
        headers=_auth(token),
    )
    assert r.status_code == 400