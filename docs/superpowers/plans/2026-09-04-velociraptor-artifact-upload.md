# Velociraptor Artifact Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Super Admin can push validated `Custom.*` artifact definitions to the Velociraptor server from the existing DFIR page, with PostgreSQL persistence for re-push and full audit.

**Architecture:** Backend talks to Velociraptor directly via the existing `VelociraptorClient` gRPC/mTLS channel. Push uses the server-side VQL function `artifact_set(definition=...)` because the pinned `pyvelociraptor` bindings lack `SetArtifact`. Portal embeds the manager into `portal/app/(portal)/dfir/page.tsx` — no new page.

**Tech Stack:** FastAPI, SQLAlchemy async/PostgreSQL, Alembic, PyYAML, gRPC/pyvelociraptor, pytest, TypeScript/Next.js.

**Spec:** `docs/superpowers/specs/2026-09-04-velociraptor-artifact-upload-design.md`

## Global Constraints

- Only `Custom.*` artifact names; built-in artifacts are immutable through this surface.
- Definition YAML is 1–262144 bytes, never logged, never placed in audit targets, never interpolated into VQL (env bindings only).
- Artifact `tools:` sections are rejected.
- All endpoints require `require_super_admin`.
- No deletion, no DeepAgent/MCP change, no allowlist change in this iteration.
- Audit actions: `velociraptor.artifact.push`, `velociraptor.artifact.repush`.

---

## File Structure

- Create `server/app/services/velociraptor_artifacts.py` — validation, list, push, verify.
- Modify `server/app/services/velociraptor.py` — public `vql()` wrapper around `_vql_query`.
- Modify `server/app/db/models.py` — `VelociraptorArtifact` model.
- Create `server/alembic/versions/x2y3z4a5b6c7_velociraptor_artifacts.py` — table migration.
- Modify `server/app/schemas/__init__.py` — `VelociraptorArtifactUpload`, `VelociraptorArtifactOut`.
- Create `server/app/api/routes/velociraptor_artifacts.py` — router `/api/admin/velociraptor/artifacts`.
- Modify `server/app/main.py` — include the new router.
- Create `server/tests/test_velociraptor_artifacts.py` — validation + route tests.
- Modify `portal/lib/types.ts` — `VelociraptorArtifact` type.
- Modify `portal/app/(portal)/dfir/page.tsx` — embedded artifact manager card.

## Task 1: Artifact service (validation + push)

**Files:**
- Create: `server/app/services/velociraptor_artifacts.py`
- Modify: `server/app/services/velociraptor.py`
- Test: `server/tests/test_velociraptor_artifacts.py`

**Interfaces:**
- `ArtifactSpec` dataclass: `name: str`, `artifact_type: str`, `definition_yaml: str`, `sha256: str`.
- `validate_artifact_definition(text: str) -> ArtifactSpec` raises `ArtifactValidationError`.
- `list_server_artifacts(client, prefix="Custom.") -> set[str]`.
- `push_artifact(client, spec: ArtifactSpec) -> None` raises `ArtifactPushError`.
- `VelociraptorClient.vql(vql, env=None)` public wrapper.

- [x] Step 1: write failing validation tests (bad YAML, non-mapping, missing name, non-Custom name, bad type, tools section, empty sources, oversize).
- [x] Step 2: implement `validate_artifact_definition` and `ArtifactSpec`.
- [x] Step 3: add `VelociraptorClient.vql` public wrapper.
- [x] Step 4: implement `list_server_artifacts` + `push_artifact` (pre-check, `artifact_set`, verify) with fake-client tests.

## Task 2: DB model + migration

**Files:**
- Modify: `server/app/db/models.py`
- Create: `server/alembic/versions/x2y3z4a5b6c7_velociraptor_artifacts.py`

- [x] Step 1: add `VelociraptorArtifact` model per spec table.
- [x] Step 2: migration `x2y3z4a5b6c7`, `down_revision = "w1x2y3z4a5b6"`, `create_table` + unique constraint on `name`; downgrade drops the table.
- [x] Step 3: `test_migration_graph.py` stays green (single head).

## Task 3: Routes + schemas + audit

**Files:**
- Create: `server/app/api/routes/velociraptor_artifacts.py`
- Modify: `server/app/schemas/__init__.py`
- Modify: `server/app/main.py`
- Test: `server/tests/test_velociraptor_artifacts.py`

**Interfaces:**
- `VelociraptorArtifactUpload { definition_yaml: str }` (1..262144).
- `VelociraptorArtifactOut { id, name, sha256, artifact_type, enabled, on_server, last_push_status, last_push_error, updated_at }`.
- Routes reuse `_build_velociraptor_client` from `app.api.routes.velociraptor`.

- [x] Step 1: failing route tests — 403 non-admin, 422 invalid YAML, 200 push with DB + audit, list merge, re-push.
- [x] Step 2: implement schemas.
- [x] Step 3: implement router (GET list, POST create, GET one, POST re-push), wire `main.py`.

## Task 4: Portal embedding into DFIR page

**Files:**
- Modify: `portal/lib/types.ts`
- Modify: `portal/app/(portal)/dfir/page.tsx`

- [x] Step 1: add `VelociraptorArtifact` type.
- [x] Step 2: add "Custom artifacts" card on the DFIR page: list + `on_server` badge, upload modal (textarea + file load), re-push button, CLIENT_EVENT warning, safe errors.
- [x] Step 3: portal lint/build passes.

## Task 5: Verification

- [x] Step 1: `ruff check app tests` and `pytest -q` green in `server/`.
- [x] Step 2: smoke against dev Velociraptor: push `Custom.Inventory.SmokeTest`, verify `artifact_definitions`, verify list shows `on_server=true`.
- [ ] Step 3: update `README.md` feature list if the team wants it documented (optional).
