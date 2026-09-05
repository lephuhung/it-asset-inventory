from __future__ import annotations

import re

import yaml
from sqlalchemy import func, select

from app.db.models import VelociraptorArtifact
from app.services.dfir_investigation import _load_custom_artifact_refs


class SeedPushClient:
    """Only the external Velociraptor boundary is replaced; DB and loader stay real."""

    def __init__(self) -> None:
        self.pushed: set[str] = set()

    async def vql(self, vql: str, env: dict | None = None) -> list[dict]:
        env = env or {}
        if "artifact_set" in vql:
            definition = env["Definition"]
            name = definition.split("name: ", 1)[1].splitlines()[0].strip()
            self.pushed.add(name)
            return [{"Name": name}]
        if "artifact_definitions() WHERE name = Name" in vql:
            return [{"name": env["Name"]}] if env.get("Name") in self.pushed else []
        return []


def test_bundled_seed_loads_six_valid_client_wrappers() -> None:
    from app.services.velociraptor_artifact_seed import load_bundled_artifacts

    artifacts = load_bundled_artifacts()

    assert [item.spec.name for item in artifacts] == [
        "Custom.DFIR.Linux.Persistence",
        "Custom.DFIR.Linux.SSH",
        "Custom.DFIR.Linux.Triage",
        "Custom.DFIR.Windows.Execution",
        "Custom.DFIR.Windows.Persistence",
        "Custom.DFIR.Windows.Triage",
    ]
    assert all(item.spec.artifact_type == "CLIENT" for item in artifacts)
    # The current MCP custom-artifact bridge reads the base artifact result.
    # Named/multiple sources are stored under suffixed result names and would
    # therefore look like a successful collection with zero returned rows.
    assert all(
        len(yaml.safe_load(item.spec.definition_yaml)["sources"]) == 1
        and "name" not in yaml.safe_load(item.spec.definition_yaml)["sources"][0]
        for item in artifacts
    )
    bounded_queries = [
        yaml.safe_load(item.spec.definition_yaml)["sources"][0]["query"]
        for item in artifacts
    ]
    assert all(
        sum(map(int, re.findall(r"LIMIT (\d+)", query))) <= 30
        for query in bounded_queries
    )
    assert all(item.enabled for item in artifacts)
    assert all("Tier" in item.description for item in artifacts)


async def test_seed_is_idempotent_and_preserves_active_catalog_policy(db) -> None:
    from app.services.velociraptor_artifact_seed import (
        load_bundled_artifacts,
        seed_velociraptor_artifacts,
    )

    artifacts = load_bundled_artifacts()
    client = SeedPushClient()

    first = await seed_velociraptor_artifacts(db, client, artifacts)
    second = await seed_velociraptor_artifacts(db, client, artifacts)

    count = await db.scalar(select(func.count()).select_from(VelociraptorArtifact))
    assert count == 6
    assert first == second == [item.spec.name for item in artifacts]
    assert client.pushed == set(first)

    windows = await _load_custom_artifact_refs(db, "windows")
    linux = await _load_custom_artifact_refs(db, "linux")
    macos = await _load_custom_artifact_refs(db, "macos")
    assert [item["name"] for item in windows] == [
        "Custom.DFIR.Windows.Triage",
        "Custom.DFIR.Windows.Execution",
        "Custom.DFIR.Windows.Persistence",
    ]
    assert [item["name"] for item in linux] == [
        "Custom.DFIR.Linux.Triage",
        "Custom.DFIR.Linux.Persistence",
        "Custom.DFIR.Linux.SSH",
    ]
    assert macos == []

    rows = (await db.execute(select(VelociraptorArtifact))).scalars().all()
    assert all(row.last_push_status == "pushed" for row in rows)
