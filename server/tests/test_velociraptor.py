"""Test Velociraptor API wrapper + sync logic + routes.

Mock toàn bộ HTTP sang Velociraptor (httpx.MockTransport) — không cần server thật.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select

# ── Unit tests cho VelociraptorClient + helpers ──────────────────


SAMPLE_CLIENTS = [
    {
        "client_id": "C.aaa111",
        "os_info": {"hostname": "DESKTOP-AAA", "system": "windows", "release": "10"},
        "last_seen_at": "2026-08-01T10:00:00Z",
    },
    {
        "client_id": "C.bbb222",
        "os_info": {"hostname": "desktop-bbb.local", "system": "windows"},
        "last_seen_at": "2026-08-02T10:00:00Z",
    },
    {
        "client_id": "C.ccc333",
        "os_info": {"hostname": "DESKTOP-CCC", "system": "windows"},
        "last_seen_at": "2026-08-03T10:00:00Z",
    },
    # Hostname trống — bỏ qua khi sync
    {"client_id": "C.xxx999", "os_info": {"hostname": ""}, "last_seen_at": "2026-08-01T00:00:00Z"},
    # Hostname trùng DESKTOP-AAA, last_seen mới hơn → phải được chọn
    {
        "client_id": "C.aaa999",
        "os_info": {"hostname": "DESKTOP-AAA", "system": "windows"},
        "last_seen_at": "2026-08-05T10:00:00Z",
    },
]


def _build_mock_transport(handler):
    """httpx.MockTransport — handler(request) trả về Response."""

    async def _h(req: httpx.Request) -> httpx.Response:
        body = handler(req)
        if isinstance(body, tuple):
            status_code, payload = body
        else:
            status_code, payload = 200, body
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(_h)


def test_normalize_hostname_strips_fqdn_lowercases() -> None:
    from app.services.velociraptor import normalize_hostname

    assert normalize_hostname("DESKTOP-ABC.local") == "desktop-abc"
    assert normalize_hostname("  PC-DEF  ") == "pc-def"
    assert normalize_hostname(None) == ""
    assert normalize_hostname("") == ""
    assert normalize_hostname("justahost") == "justahost"


def test_hostname_from_velociraptor_client() -> None:
    from app.services.velociraptor import hostname_from_velociraptor_client

    assert hostname_from_velociraptor_client(SAMPLE_CLIENTS[0]) == "desktop-aaa"
    assert hostname_from_velociraptor_client({"client_id": "X"}) == ""


def test_velociraptor_client_rejects_bad_url() -> None:
    from app.services.velociraptor import VelociraptorClient

    with pytest.raises(ValueError, match="http://"):
        VelociraptorClient("veloci.example.gov.vn", username="admin", password="tok")


def test_velociraptor_client_test_connection_ok() -> None:
    from app.services.velociraptor import VelociraptorClient

    def handler(req: httpx.Request) -> Any:
        assert req.headers["Authorization"] == "Basic YWRtaW46c2VjcmV0LXRva2Vu"
        assert req.url.path == "/api/v1/SearchClients"
        return {"clients": SAMPLE_CLIENTS[:1]}

    transport = _build_mock_transport(handler)
    client = VelociraptorClient(
        "https://veloci.test", username="admin", password="secret-token", transport=transport
    )

    async def run() -> dict:
        async with client as c:
            return await c.test_connection()

    import asyncio

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["ok"] is True


def test_velociraptor_client_test_connection_http_error() -> None:
    from app.services.velociraptor import VelociraptorClient

    def handler(req: httpx.Request) -> Any:
        return (401, {"error": "bad token"})

    transport = _build_mock_transport(handler)
    client = VelociraptorClient("https://veloci.test", username="admin", password="bad", transport=transport)

    async def run() -> dict:
        async with client as c:
            return await c.test_connection()

    import asyncio

    result = asyncio.run(run())
    assert result["ok"] is False
    assert "401" in result["error"]


def test_velociraptor_client_collect_artifact_returns_flow_id() -> None:
    from app.services.velociraptor import VelociraptorClient

    def handler(req: httpx.Request) -> Any:
        assert req.url.path == "/api/v1/CollectArtifact"
        body = json.loads(req.content)
        assert body["client_id"] == "C.aaa111"
        assert body["artifacts"] == ["Generic.Client.Info"]
        return {"flow_id": "F.1234567890"}

    transport = _build_mock_transport(handler)
    client = VelociraptorClient("https://veloci.test", username="admin", password="tok", transport=transport)

    async def run() -> str:
        async with client as c:
            return await c.collect_artifact("C.aaa111", ["Generic.Client.Info"])

    import asyncio

    flow = asyncio.run(run())
    assert flow == "F.1234567890"


def test_velociraptor_client_create_hunt_with_modify() -> None:
    from app.services.velociraptor import VelociraptorClient

    def handler(req: httpx.Request) -> Any:
        if req.url.path == "/api/v1/CreateHunt":
            return {"hunt_id": "H.987"}
        if req.url.path == "/api/v1/ModifyHunt":
            body = json.loads(req.content)
            assert body["hunt_id"] == "H.987"
            assert body["add_client_ids"] == ["C.aaa111", "C.bbb222"]
            assert body["start"] is True
            return {"status": "ok"}
        raise AssertionError(f"unexpected path: {req.url.path}")

    transport = _build_mock_transport(handler)
    client = VelociraptorClient("https://veloci.test", username="admin", password="tok", transport=transport)

    async def run() -> tuple[str, dict]:
        async with client as c:
            hunt_id = await c.create_hunt("My Hunt", ["Generic.Client.Info"])
            res = await c.modify_hunt(hunt_id, add_client_ids=["C.aaa111", "C.bbb222"], start=True)
            return hunt_id, res

    import asyncio

    hid, res = asyncio.run(run())
    assert hid == "H.987"
    assert res["status"] == "ok"


# ── Integration tests với DB (mock Velociraptor transport) ──────


async def _setup_machine(session_factory, hostname: str) -> Any:
    """Helper: tạo 1 Organization + 1 Machine với hostname. Trả machine.id."""
    import uuid

    from app.db.models import Machine, MachineStatus, Organization, OrgType

    async with session_factory() as db:
        org = Organization(name="Org-Test", type=OrgType.DON_VI.value)
        db.add(org)
        await db.flush()
        m = Machine(
            org_id=org.id,
            machine_uuid=str(uuid.uuid4()),
            hostname=hostname,
            status=MachineStatus.ONLINE.value,
        )
        db.add(m)
        await db.commit()
        return m.id


async def _setup_velociraptor_config(session_factory) -> None:
    """Tạo VelociraptorConfig đã bật + token giả (encrypted)."""
    from app.core.security import encrypt_aes_gcm
    from app.db.models import VelociraptorConfig

    async with session_factory() as db:
        cfg = VelociraptorConfig(
            id=1,
            enabled=True,
            server_url="https://veloci.test",
            basic_auth_encrypted=encrypt_aes_gcm('{"username":"admin","password":"test-token-xyz"}'),
            allowlist=["Generic.Client.Info", "Windows.System.Services"],
            last_sync_at=None,
        )
        db.add(cfg)
        await db.commit()


async def test_sync_links_matches_by_normalized_hostname(client, session_factory):
    """Background sync: hostname DESKTOP-AAA ↔ Velociraptor client.aaa999 (last_seen mới nhất)."""
    from app.services.velociraptor_sync import sync_velociraptor_links

    await _setup_velociraptor_config(session_factory)
    await _setup_machine(session_factory, "DESKTOP-AAA")  # uppercase, khớp lowercase chuẩn hoá
    await _setup_machine(session_factory, "desktop-bbb.local")  # FQDN — strip phần sau dấu chấm
    await _setup_machine(session_factory, "DESKTOP-CCC")
    # Machine không có trong Velociraptor — không được link
    await _setup_machine(session_factory, "DESKTOP-NOT-IN-VELO")

    async def run() -> dict:
        # Patch search_clients để trả về SAMPLE_CLIENTS (mock REST API)
        from app.services import velociraptor as vmod

        orig_search = vmod.VelociraptorClient.search_clients

        async def patched_search(self, query="", limit=1000, offset=0):
            return SAMPLE_CLIENTS

        vmod.VelociraptorClient.search_clients = patched_search
        try:
            return await sync_velociraptor_links()
        finally:
            vmod.VelociraptorClient.search_clients = orig_search

    result = await run()
    assert result["linked"] == 3, result  # DESKTOP-AAA, DESKTOP-BBB, DESKTOP-CCC
    assert result["total_clients"] == len(SAMPLE_CLIENTS)

    # Verify DB
    async with session_factory() as db:

        links = (await db.execute(select_velociraptor_links(db))).scalars().all()
        by_machine = {l.machine_id: l for l in links}
        assert len(by_machine) == 3
        # DESKTOP-AAA phải link với C.aaa999 (last_seen mới hơn C.aaa111)
        # Tìm machine DESKTOP-AAA
        from app.db.models import Machine

        m_aaa = (
            await db.execute(select(Machine).where(Machine.hostname == "DESKTOP-AAA"))
        ).scalar_one_or_none()
        link_aaa = by_machine[m_aaa.id]
        assert link_aaa.client_id == "C.aaa999"


def select_velociraptor_links(db):
    """Helper: SQLAlchemy select wrapped async."""
    from sqlalchemy import select

    from app.db.models import VelociraptorLink

    return select(VelociraptorLink)


async def test_sync_skips_when_disabled(client, session_factory):
    """Sync bỏ qua nếu VelociraptorConfig.enabled=False."""
    from app.services.velociraptor_sync import sync_velociraptor_links

    # Không setup config (sẽ trả None → skipped)
    result = await sync_velociraptor_links()
    assert result.get("skipped") is True


async def test_sync_records_last_sync(client, session_factory):
    """Sync thành công → cập nhật last_sync_at, last_sync_linked, last_sync_total."""
    from app.services.velociraptor_sync import sync_velociraptor_links

    await _setup_velociraptor_config(session_factory)
    await _setup_machine(session_factory, "DESKTOP-AAA")

    async def run() -> dict:
        from app.services import velociraptor as vmod

        orig_search = vmod.VelociraptorClient.search_clients

        async def patched_search(self, query="", limit=1000, offset=0):
            return SAMPLE_CLIENTS[:3]  # chỉ 3 client, 1 match

        vmod.VelociraptorClient.search_clients = patched_search
        try:
            return await sync_velociraptor_links()
        finally:
            vmod.VelociraptorClient.search_clients = orig_search

    result = await run()
    assert result["linked"] == 1

    # Verify last_sync_* updated
    async with session_factory() as db:
        from app.db.models import VelociraptorConfig

        cfg = (
            await db.execute(select(VelociraptorConfig).where(VelociraptorConfig.id == 1))
        ).scalar_one_or_none()
        assert cfg.last_sync_at is not None
        assert cfg.last_sync_linked == 1
        assert cfg.last_sync_total == 3
        assert cfg.last_sync_error is None


# ── API route tests ──────────────────────────────────────────────


async def test_get_velociraptor_config_default(client, seeded_env):
    """GET /api/admin/velociraptor/config — trả default khi chưa cấu hình."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]

    r = await client.get(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is False
    assert data["basic_auth_set"] is False
    assert "Generic.Client.Info" in data["defaults_allowlist"]


async def test_update_velociraptor_config_encrypts_token(client, seeded_env):
    """PUT cấu hình — token plaintext phải được mã hoá trước khi lưu."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]

    r = await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "enabled": True,
            "server_url": "https://veloci.example.gov.vn:8889",
            "username": "admin",
            "password": "plaintext-secret-token",
            "allowlist": ["Generic.Client.Info", "Windows.System.Services"],
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is True
    assert data["server_url"] == "https://veloci.example.gov.vn:8889"
    assert data["basic_auth_set"] is True  # basic auth đã lưu
    assert "plaintext-secret-token" not in str(data)  # KHÔNG lộ plaintext ra response


async def test_update_velociraptor_config_invalid_url(client, seeded_env):
    """server_url không bắt đầu bằng http(s):// → 422."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]
    r = await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={"server_url": "veloci.example.gov.vn"},  # thiếu scheme
    )
    assert r.status_code == 422


async def test_create_hunt_rejects_non_allowlisted_artifact(client, seeded_env):
    """Hunt artifact không trong allowlist → 403 (chống lạm quyền)."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]

    # Setup Velociraptor enabled + token
    await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "enabled": True,
            "server_url": "https://veloci.test",
            "username": "admin",
            "password": "tok",
            "allowlist": ["Generic.Client.Info"],
        },
    )

    # Hunt với artifact NGOÀI allowlist → 403
    r = await client.post(
        "/api/admin/velociraptor/hunt",
        headers={"Authorization": f"Bearer {tok}"},
        json={"artifact": "Windows.NTFS.MFT", "scope": "all"},
    )
    assert r.status_code == 403
    assert "allowlist" in r.json()["detail"].lower()
