# Velociraptor Artifact Upload from Backend — Design

## Problem

Operators need to add custom Velociraptor artifact definitions (`Custom.*`) to the
Velociraptor server so hunts, collections, and DFIR workflows gain new data sources.
Today the only path is the Velociraptor GUI or CLI on the server host. The inventory
backend already holds the mTLS `api_client.yaml` (encrypted in `velociraptor_config`)
and runs server-side VQL over gRPC via `VelociraptorClient._vql_query`.

The pinned `pyvelociraptor>=0.1.11` generated bindings do **not** expose the
`SetArtifact` RPC (verified: `api_pb2_grpc.APIStub` has no artifact methods, no
`APIObject` message). The server-side VQL function `artifact_set(definition=...)`
is the supported fallback and requires no new dependency.

## Goals

1. Super Admin can push a validated custom artifact definition to the Velociraptor
   server from the existing DFIR page in the portal.
2. Every push is validated, size-bounded, restricted to the `Custom.*` namespace,
   persisted in PostgreSQL for re-push, and audit-logged.
3. Pushed artifacts are listed with their live on-server presence so operators can
   confirm Velociraptor actually loaded them.
4. No new external dependency; reuse `VelociraptorClient` mTLS plumbing.

## Non-goals

- No artifact deletion (neither server-side nor DB) in this iteration.
- No edit of non-`Custom.*` artifacts; built-ins are immutable through this surface.
- No artifact `tools:` section (external binary downloads) — rejected at validation.
- No DeepAgent/MCP catalog change; the LLM investigation path stays read-only and
  its tool catalog unchanged.
- No dynamic allowlist merge for hunts (`VELOCIRAPTOR_DEFAULT_ALLOWLIST` handling is
  a separate follow-up, phase 4a in the original proposal).

## Contract

### Validation (`validate_artifact_definition`)

Input: raw YAML text, 1–262144 bytes. Output: `ArtifactSpec(name, artifact_type,
definition_yaml, sha256)`.

Rules, in order; any violation raises `ArtifactValidationError` with a safe message:

1. YAML parses to a mapping.
2. `name` exists and matches `^Custom\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$`.
3. `type`, when present, is one of `CLIENT`, `CLIENT_EVENT`, `SERVER`,
   `SERVER_EVENT` (normalized to uppercase; default `CLIENT`).
4. `tools` key is absent.
5. `sources` is a non-empty list; every source that declares `queries` must use a
   list of query strings (a source-level `query` string is also accepted).

### Push (`push_artifact`)

1. Pre-check: VQL `artifact_definitions(name=...)` — if the name exists server-side
   and does not start with `Custom.`, reject (defense in depth; validation already
   restricts names).
2. Push: `SELECT artifact_set(definition=Definition) AS Name FROM scope()` with the
   YAML passed as a VQL environment binding (never interpolated into the query
   string).
3. Verify: re-query `artifact_definitions(name=...)`; absence raises
   `ArtifactPushError`.

### Persistence

Table `velociraptor_artifacts`:

| Column | Type | Note |
| --- | --- | --- |
| `id` | uuid PK | |
| `name` | varchar(255) unique | artifact name |
| `definition_yaml` | text | source of truth for re-push |
| `sha256` | varchar(64) | content hash |
| `artifact_type` | varchar(32) | CLIENT / CLIENT_EVENT / SERVER / SERVER_EVENT |
| `enabled` | boolean | default true |
| `last_push_status` | varchar(16) | `pushed` / `failed` / null |
| `last_push_error` | text | safe message only, never YAML |
| `created_by` | uuid FK users.id | |
| `created_at` / `updated_at` | timestamptz | |

### API (`/api/admin/velociraptor/artifacts`, super-admin only)

- `GET /artifacts` — DB rows joined with live server names (`on_server: bool`).
- `POST /artifacts` — body `{definition_yaml}`; validate → push → upsert DB → audit
  `velociraptor.artifact.push`. Returns the stored row. Push failure → 502 with safe
  detail, DB row records `last_push_status=failed`.
- `GET /artifacts/{name}` — single DB row including `definition_yaml`.
- `POST /artifacts/{name}/push` — re-push from the stored definition (server rebuild
  recovery).

### Portal

Embedded into the existing DFIR page (`portal/app/(portal)/dfir/page.tsx`) as a new
"Custom artifacts" card: list, upload modal (paste YAML or load a `.yaml` file into
the textarea), push/re-push actions, `on_server` badge, safe error display.

## Security

- Endpoints require `require_super_admin`, matching `/api/admin/velociraptor/*`.
- The YAML definition is never written to logs or audit targets; audit records only
  action, actor, artifact name, and client IP.
- `CLIENT_EVENT` artifacts change fleet-wide agent behavior; the portal UI shows an
  explicit warning when the parsed type is `CLIENT_EVENT`.
- VQL uses env bindings only; no YAML is interpolated into query text.

## Acceptance

1. Unit tests cover every validation rule and push error paths.
2. Route tests cover RBAC (non-admin → 403), invalid YAML → 422, successful push →
   200 + DB row + audit entry, re-push, and list merge.
3. Smoke against the dev Velociraptor stack: push `Custom.Inventory.Test`, confirm
   via `artifact_definitions`, confirm list endpoint reports `on_server=true`.
4. Backend test suite and `ruff` stay green; portal builds.
