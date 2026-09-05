"""Load and seed the curated Custom.DFIR.* artifact bundle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VelociraptorArtifact
from app.services.velociraptor import VelociraptorClient
from app.services.velociraptor_artifacts import (
    ArtifactSpec,
    push_artifact,
    validate_artifact_definition,
)

_BUNDLE_DIR = Path(__file__).resolve().parents[1] / "velociraptor_artifact_seeds"
_VALID_PLATFORMS = {"windows", "linux", "macos"}


@dataclass(frozen=True)
class SeedArtifact:
    spec: ArtifactSpec
    description: str
    supported_platforms: list[str]
    selection_priority: int
    enabled: bool


def load_bundled_artifacts(bundle_dir: Path = _BUNDLE_DIR) -> list[SeedArtifact]:
    """Read the manifest and validate every bundled definition through the upload policy."""
    manifest = yaml.safe_load((bundle_dir / "manifest.yaml").read_text(encoding="utf-8"))
    entries = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("Artifact seed manifest must contain a non-empty artifacts list")

    artifacts: list[SeedArtifact] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("Each artifact seed manifest entry must be a mapping")
        filename = entry.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("Artifact seed file must be a plain filename")
        definition = (bundle_dir / filename).read_text(encoding="utf-8")
        spec = validate_artifact_definition(definition)
        if spec.name in seen:
            raise ValueError(f"Duplicate artifact seed name: {spec.name}")
        seen.add(spec.name)
        if spec.artifact_type != "CLIENT":
            raise ValueError(f"Seed artifact must be CLIENT: {spec.name}")

        doc = yaml.safe_load(definition)
        description = str(doc.get("description") or "").strip()
        platforms = entry.get("supported_platforms")
        if (
            not isinstance(platforms, list)
            or not platforms
            or not all(isinstance(item, str) and item in _VALID_PLATFORMS for item in platforms)
        ):
            raise ValueError(f"Invalid supported platforms for {spec.name}")
        priority = entry.get("selection_priority")
        if not isinstance(priority, int) or not 0 <= priority <= 1000:
            raise ValueError(f"Invalid selection priority for {spec.name}")
        enabled = entry.get("enabled")
        if not isinstance(enabled, bool):
            raise TypeError(f"Invalid enabled flag for {spec.name}")
        artifacts.append(
            SeedArtifact(
                spec=spec,
                description=description,
                supported_platforms=list(dict.fromkeys(platforms)),
                selection_priority=priority,
                enabled=enabled,
            )
        )
    return sorted(artifacts, key=lambda item: item.spec.name)


async def seed_velociraptor_artifacts(
    db: AsyncSession,
    client: VelociraptorClient,
    artifacts: list[SeedArtifact] | None = None,
) -> list[str]:
    """Idempotently upsert the curated bundle and verify every definition on Velociraptor."""
    seeded: list[str] = []
    for item in artifacts or load_bundled_artifacts():
        row = await db.scalar(
            select(VelociraptorArtifact).where(VelociraptorArtifact.name == item.spec.name)
        )
        if row is None:
            row = VelociraptorArtifact(
                name=item.spec.name,
                definition_yaml=item.spec.definition_yaml,
                sha256=item.spec.sha256,
                artifact_type=item.spec.artifact_type,
                enabled=item.enabled,
                supported_platforms=item.supported_platforms,
                selection_priority=item.selection_priority,
            )
            db.add(row)
        else:
            row.definition_yaml = item.spec.definition_yaml
            row.sha256 = item.spec.sha256
            row.artifact_type = item.spec.artifact_type
            row.enabled = item.enabled
            row.supported_platforms = item.supported_platforms
            row.selection_priority = item.selection_priority

        try:
            await push_artifact(client, item.spec)
        except Exception as exc:
            row.last_push_status = "failed"
            row.last_push_error = f"{type(exc).__name__}: seed push failed"[:500]
            row.updated_at = datetime.now(UTC)
            await db.commit()
            raise
        row.last_push_status = "pushed"
        row.last_push_error = None
        row.updated_at = datetime.now(UTC)
        seeded.append(item.spec.name)
    await db.commit()
    return seeded
