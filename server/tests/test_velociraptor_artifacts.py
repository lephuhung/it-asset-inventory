"""Tests cho velociraptor_artifacts service + routes /api/admin/velociraptor/artifacts."""
from __future__ import annotations

import pytest

from app.services.velociraptor import VelociraptorError
from app.services.velociraptor_artifacts import (
    ArtifactPushError,
    ArtifactValidationError,
    list_server_artifacts,
    push_artifact,
    validate_artifact_definition,
)

VALID_YAML = """name: Custom.Inventory.Test
description: Test artifact
type: CLIENT
sources:
  - query: SELECT * FROM info()
"""


# ── Validation ──────────────────────────────────────────────────


def test_validate_accepts_minimal_custom_artifact() -> None:
    spec = validate_artifact_definition(VALID_YAML)
    assert spec.name == "Custom.Inventory.Test"
    assert spec.artifact_type == "CLIENT"
    assert len(spec.sha256) == 64


def test_validate_normalizes_type_case_and_queries_list() -> None:
    yaml_text = (
        "name: Custom.X\n"
        "type: client_event\n"
        "sources:\n"
        "  - queries:\n"
        "      - SELECT * FROM pslist()\n"
    )
    spec = validate_artifact_definition(yaml_text)
    assert spec.artifact_type == "CLIENT_EVENT"


def test_validate_rejects_invalid_yaml() -> None:
    with pytest.raises(ArtifactValidationError, match="parse"):
        validate_artifact_definition("name: [unclosed")


def test_validate_rejects_non_mapping() -> None:
    with pytest.raises(ArtifactValidationError, match="mapping"):
        validate_artifact_definition("- just\n- a\n- list\n")


def test_validate_rejects_missing_name() -> None:
    with pytest.raises(ArtifactValidationError, match="name"):
        validate_artifact_definition("sources:\n  - query: SELECT 1\n")


def test_validate_rejects_non_custom_namespace() -> None:
    with pytest.raises(ArtifactValidationError, match="Custom"):
        validate_artifact_definition(
            "name: Windows.System.Pslist\nsources:\n  - query: SELECT 1\n"
        )


def test_validate_rejects_bad_type() -> None:
    with pytest.raises(ArtifactValidationError, match="type"):
        validate_artifact_definition(
            "name: Custom.X\ntype: KERNEL\nsources:\n  - query: SELECT 1\n"
        )


def test_validate_rejects_tools_section() -> None:
    with pytest.raises(ArtifactValidationError, match="tools"):
        validate_artifact_definition(
            "name: Custom.X\n"
            "tools:\n"
            "  - name: evil\n    url: https://example.com/e.exe\n"
            "sources:\n  - query: SELECT 1\n"
        )


def test_validate_rejects_empty_sources() -> None:
    with pytest.raises(ArtifactValidationError, match="sources"):
        validate_artifact_definition("name: Custom.X\nsources: []\n")


def test_validate_rejects_source_without_query() -> None:
    with pytest.raises(ArtifactValidationError, match="query"):
        validate_artifact_definition("name: Custom.X\nsources:\n  - name: empty\n")


def test_validate_rejects_oversize() -> None:
    big = "name: Custom.X\nsources:\n  - query: SELECT 1\n# " + "A" * 300_000
    with pytest.raises(ArtifactValidationError, match="256KB"):
        validate_artifact_definition(big)


# ── Push (fake client) ──────────────────────────────────────────


class FakeClient:
    """Mô phỏng VelociraptorClient.vql theo từng câu query cố định."""

    def __init__(self, *, set_fails: bool = False, verify_missing: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.set_fails = set_fails
        self.verify_missing = verify_missing

    async def vql(self, vql: str, env: dict | None = None) -> list[dict]:
        self.calls.append((vql, env or {}))
        if "artifact_set" in vql:
            if self.set_fails:
                raise VelociraptorError("rejected by server")
            return [{"Name": env["Definition"].split("name: ")[1].splitlines()[0]}]
        if "artifact_definitions() WHERE name = Name" in vql:
            # Pre-check: chưa tồn tại. Verify: tuỳ cờ verify_missing.
            is_verify = sum(1 for q, _ in self.calls if "artifact_definitions" in q) > 1
            if is_verify and self.verify_missing:
                return []
            if is_verify:
                return [{"name": env["Name"]}]
            return []
        return []


@pytest.mark.asyncio
async def test_push_artifact_uses_env_binding_and_verifies() -> None:
    spec = validate_artifact_definition(VALID_YAML)
    client = FakeClient()

    await push_artifact(client, spec)

    set_calls = [c for c in client.calls if "artifact_set" in c[0]]
    assert len(set_calls) == 1
    # YAML đi qua env binding, không nội suy vào query string
    assert set_calls[0][1]["Definition"] == VALID_YAML
    assert spec.name not in set_calls[0][0]
    # Có bước verify sau push
    assert any("artifact_definitions" in q for q, _ in client.calls)


@pytest.mark.asyncio
async def test_push_artifact_raises_on_server_reject() -> None:
    spec = validate_artifact_definition(VALID_YAML)
    with pytest.raises(ArtifactPushError, match="từ chối"):
        await push_artifact(FakeClient(set_fails=True), spec)


@pytest.mark.asyncio
async def test_push_artifact_raises_when_verify_fails() -> None:
    spec = validate_artifact_definition(VALID_YAML)
    with pytest.raises(ArtifactPushError, match="không nạp"):
        await push_artifact(FakeClient(verify_missing=True), spec)


@pytest.mark.asyncio
async def test_list_server_artifacts_filters_prefix() -> None:
    class ListClient:
        async def vql(self, vql: str, env: dict | None = None) -> list[dict]:
            assert env == {"Prefix": "^Custom."}
            return [{"name": "Custom.A"}, {"name": "Custom.B"}, {"bad": True}]

    names = await list_server_artifacts(ListClient())
    assert names == {"Custom.A", "Custom.B"}


# ── Routes /api/admin/velociraptor/artifacts ────────────────────

from sqlalchemy import select

from app.db.models import AuditLog, VelociraptorArtifact


async def _admin_headers(client, seeded_env) -> dict:
    response = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class FakeRouteClient:
    def __init__(self, *, fail_push: bool = False):
        self.fail_push = fail_push
        self.pushed: set[str] = set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def vql(self, vql: str, env: dict | None = None) -> list[dict]:
        env = env or {}
        if "artifact_set" in vql:
            if self.fail_push:
                raise VelociraptorError("server rejected definition")
            name = env["Definition"].split("name: ")[1].splitlines()[0].strip()
            self.pushed.add(name)
            return [{"Name": name}]
        if "artifact_definitions() WHERE name = Name" in vql:
            return [{"name": env["Name"]}] if env.get("Name") in self.pushed else []
        if "artifact_definitions()" in vql:
            return [{"name": n} for n in sorted(self.pushed)]
        return []


def _patch_client(monkeypatch, fake: FakeRouteClient) -> None:
    async def fake_build(_db):
        return fake, None

    monkeypatch.setattr(
        "app.api.routes.velociraptor_artifacts._build_velociraptor_client", fake_build
    )


@pytest.mark.asyncio
async def test_artifact_routes_require_auth(client) -> None:
    response = await client.get("/api/admin/velociraptor/artifacts")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_upload_rejects_invalid_yaml(client, seeded_env, monkeypatch) -> None:
    _patch_client(monkeypatch, FakeRouteClient())
    headers = await _admin_headers(client, seeded_env)
    response = await client.post(
        "/api/admin/velociraptor/artifacts",
        headers=headers,
        json={"definition_yaml": "name: Windows.System.Pslist\nsources:\n  - query: SELECT 1\n"},
    )
    assert response.status_code == 422
    assert "Custom" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_pushes_persists_and_audits(
    client, seeded_env, session_factory, monkeypatch
) -> None:
    fake = FakeRouteClient()
    _patch_client(monkeypatch, fake)
    headers = await _admin_headers(client, seeded_env)

    response = await client.post(
        "/api/admin/velociraptor/artifacts", headers=headers,
        json={"definition_yaml": VALID_YAML},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Custom.Inventory.Test"
    assert body["on_server"] is True
    assert body["last_push_status"] == "pushed"
    assert "Custom.Inventory.Test" in fake.pushed

    async with session_factory() as db:
        row = (
            await db.execute(
                select(VelociraptorArtifact).where(
                    VelociraptorArtifact.name == "Custom.Inventory.Test"
                )
            )
        ).scalar_one()
        assert row.sha256 == body["sha256"]
        audits = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "velociraptor.artifact.push")
            )
        ).scalars().all()
        assert any(a.target == "velociraptor_artifact:Custom.Inventory.Test" for a in audits)


@pytest.mark.asyncio
async def test_upload_push_failure_returns_502_and_marks_row(
    client, seeded_env, session_factory, monkeypatch
) -> None:
    _patch_client(monkeypatch, FakeRouteClient(fail_push=True))
    headers = await _admin_headers(client, seeded_env)
    response = await client.post(
        "/api/admin/velociraptor/artifacts", headers=headers,
        json={"definition_yaml": VALID_YAML},
    )
    assert response.status_code == 502

    async with session_factory() as db:
        row = (
            await db.execute(
                select(VelociraptorArtifact).where(
                    VelociraptorArtifact.name == "Custom.Inventory.Test"
                )
            )
        ).scalar_one()
        assert row.last_push_status == "failed"
        assert "rejected" in (row.last_push_error or "")
        # YAML không lọt vào trường lỗi
        assert "SELECT" not in row.last_push_error


@pytest.mark.asyncio
async def test_list_and_repush(client, seeded_env, session_factory, monkeypatch) -> None:
    fake = FakeRouteClient()
    _patch_client(monkeypatch, fake)
    headers = await _admin_headers(client, seeded_env)

    created = await client.post(
        "/api/admin/velociraptor/artifacts", headers=headers,
        json={"definition_yaml": VALID_YAML},
    )
    assert created.status_code == 200

    listed = await client.get("/api/admin/velociraptor/artifacts", headers=headers)
    assert listed.status_code == 200
    items = listed.json()
    assert any(i["name"] == "Custom.Inventory.Test" and i["on_server"] for i in items)

    repushed = await client.post(
        "/api/admin/velociraptor/artifacts/Custom.Inventory.Test/push", headers=headers
    )
    assert repushed.status_code == 200
    assert repushed.json()["last_push_status"] == "pushed"

    detail = await client.get(
        "/api/admin/velociraptor/artifacts/Custom.Inventory.Test", headers=headers
    )
    assert detail.status_code == 200
    assert "artifact_set" not in detail.json()["definition_yaml"]  # trả YAML gốc
    assert "SELECT * FROM info()" in detail.json()["definition_yaml"]

    missing = await client.post(
        "/api/admin/velociraptor/artifacts/Custom.DoesNotExist/push", headers=headers
    )
    assert missing.status_code == 404


# ── DeepAgent payload builder ───────────────────────────────────


@pytest.mark.asyncio
async def test_custom_artifact_refs_only_enabled_client_and_capped(session_factory) -> None:
    """Payload DeepAgent chỉ chứa artifact CLIENT + enabled, description ≤300 ký tự."""
    from app.services.dfir_investigation import _load_custom_artifact_refs

    async with session_factory() as db:
        db.add_all([
            VelociraptorArtifact(
                name="Custom.Test.Enabled",
                definition_yaml="name: Custom.Test.Enabled\ndescription: Mô tả ngắn\nsources:\n  - query: SELECT 1\n",
                sha256="a" * 64,
                artifact_type="CLIENT",
                enabled=True,
            ),
            VelociraptorArtifact(
                name="Custom.Test.Disabled",
                definition_yaml="name: Custom.Test.Disabled\nsources:\n  - query: SELECT 1\n",
                sha256="b" * 64,
                artifact_type="CLIENT",
                enabled=False,
            ),
            VelociraptorArtifact(
                name="Custom.Test.ServerType",
                definition_yaml="name: Custom.Test.ServerType\nsources:\n  - query: SELECT 1\n",
                sha256="c" * 64,
                artifact_type="SERVER",
                enabled=True,
            ),
            VelociraptorArtifact(
                name="Custom.Test.LongDesc",
                definition_yaml="name: Custom.Test.LongDesc\ndescription: " + "x" * 500 + "\nsources:\n  - query: SELECT 1\n",
                sha256="d" * 64,
                artifact_type="CLIENT",
                enabled=True,
            ),
        ])
        await db.commit()

        refs = await _load_custom_artifact_refs(db)

    names = [r["name"] for r in refs]
    assert "Custom.Test.Enabled" in names
    assert "Custom.Test.Disabled" not in names
    assert "Custom.Test.ServerType" not in names
    long_ref = next(r for r in refs if r["name"] == "Custom.Test.LongDesc")
    assert len(long_ref["description"]) == 300
