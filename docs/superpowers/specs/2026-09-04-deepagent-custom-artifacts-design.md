# DeepAgent Custom Artifact Catalog — Design

## Problem

Super Admin can push `Custom.*` artifacts to Velociraptor (feature
`2026-09-04-velociraptor-artifact-upload`), but DeepAgent cannot use them: its
planner catalog (`WINDOWS_TOOL_POLICIES`) is static, `sanitize_plan` drops unknown
tools, and `VelociraptorMCP.collect()` rejects non-allowlisted names.

Upstream `collect_artifact` is unsuitable for the investigation graph: it only
**starts** a flow (`_start_collection_tool`) and returns flow metadata, while
DeepAgent's collect step needs result rows synchronously.

## Goals

1. Newly uploaded, enabled `Custom.*` artifacts of type `CLIENT` appear as
   selectable read-only tools in the DeepAgent planner prompt for every new
   investigation.
2. The model can only select names carried in the signed internal request payload;
   it cannot supply artifact parameters, fields, VQL, or pagination values.
3. Result rows flow through the existing evidence pipeline (timeout, char budget,
   safe logging) unchanged.
4. Defense in depth: the MCP bridge itself rejects non-`Custom.*` names and
   non-CLIENT artifacts for this tool.

## Non-goals

- No artifact parameters (defaults only), no `CLIENT_EVENT`/`SERVER` types.
- No change to the static 15-tool catalog semantics or event-log typed flow.
- No portal changes (catalog derives from the upload feature's DB table).
- Request schema stays `dfir.deepagent.request/1.1` — `custom_artifacts` is
  optional and old peers ignore/accept it (pydantic extra fields are ignored).

## Contract

### Backend → DeepAgent payload

`InvestigationRequest.custom_artifacts: list[CustomArtifactRef]` (max 20):

```json
{"name": "Custom.Inventory.SmokeTest", "description": "…≤300 chars…"}
```

Backend builds this from `velociraptor_artifacts` rows where `enabled=true` and
`artifact_type='CLIENT'`; `description` is parsed from the stored YAML and capped.

### DeepAgent planner

- Synthetic tool name: `custom:<name>` (e.g. `custom:Custom.Inventory.SmokeTest`).
- `catalog_prompt()` renders a second section listing each custom tool with its
  description wrapped as untrusted operator data.
- `sanitize_plan()` keeps a custom step only when the name is in the request's
  `custom_artifacts` set; duplicates and unknown names are dropped as before.

### MCP bridge tool (`collect_custom_artifact`)

```python
async def collect_custom_artifact(
    client_id: str, artifact: str, org_id: str = "",
    limit: int = 100, offset: int = 0,
) -> str
```

1. Reject names not matching `^Custom\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$`.
2. Verify the artifact exists server-side and its `type` is `client`
   (`artifact_definitions() WHERE name = ...`).
3. Collect with `_run_collection_tool(client_id, artifact, None, "*", "", org_id,
   limit, offset)` — parameters always default, standard pagination envelope.

### DeepAgent collection path

`VelociraptorMCP.collect()` gains a `custom_names: set[str]` parameter. A
`custom:` step resolves the artifact name, requires membership in `custom_names`,
and invokes `collect_custom_artifact` with locked arguments (`limit=50`,
`offset=0`). Pagination metadata is preserved in `EvidenceItem.pagination` like
other paginated tools.

## Security

- The custom catalog crosses the trust boundary only via the service-token-
  authenticated internal request; the model can never extend it.
- Descriptions are length-capped and rendered as untrusted context.
- The bridge tool rejects `tools:`-bearing artifacts indirectly: push validation
  (upload feature) already forbids `tools:`; bridge additionally enforces
  namespace + type at call time.
- `custom:` tools count against `max_steps` and the aggregate evidence budget.

## Acceptance

1. MCP tool unit-verified against the dev Velociraptor server (envelope, rows,
   rejection of `Windows.*` and non-CLIENT artifacts).
2. DeepAgent tests: plan sanitization keeps/drops custom tools correctly;
   `collect()` calls the bridge with locked args and rejects unlisted names.
3. Backend test: dispatch payload contains only enabled CLIENT artifacts with
   capped descriptions.
4. All server + deepagent suites and ruff pass; MCP repo pushed and Dockerfile
   pinned to the new commit.
