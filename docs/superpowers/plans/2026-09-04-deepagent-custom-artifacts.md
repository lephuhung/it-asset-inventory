# DeepAgent Custom Artifact Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Newly uploaded `Custom.*` CLIENT artifacts become selectable read-only tools for DeepAgent investigations, selected by name only from the signed internal request payload and collected through a new typed, paginated MCP bridge tool.

**Architecture:** Backend reads enabled CLIENT rows from `velociraptor_artifacts` and embeds `{name, description}` into the investigation request. DeepAgent renders them as `custom:<name>` tools in the planner prompt, sanitizes against the payload set, and collects via the new `collect_custom_artifact` bridge tool with locked arguments. The bridge enforces namespace + artifact type at call time.

**Tech Stack:** FastMCP bridge (user-owned repo), FastAPI, SQLAlchemy, LangGraph, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-deepagent-custom-artifacts-design.md`

## Global Constraints

- Names must match `^Custom\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$` at both layers.
- Only `type: CLIENT` artifacts; no parameters, no field selection, no raw VQL.
- `custom_artifacts` max 20 entries; description ≤ 300 chars; optional field,
  schema stays `dfir.deepagent.request/1.1`.
- `custom:` steps count against `max_steps` and `max_evidence_chars`.
- No description or artifact YAML in operational logs.

---

## File Structure

- Modify `/tmp/mcp-velociraptor-upstream/mcp_velociraptor_bridge.py` (repo `lephuhung/mcp-velociraptor`) — new `collect_custom_artifact` tool; push and pin.
- Modify `deepagent/Dockerfile` — new pinned MCP commit.
- Modify `deepagent/deepagent/models.py` — `CustomArtifactRef`, `custom_artifacts` field.
- Modify `deepagent/deepagent/catalog.py` — dynamic catalog section + custom tool helpers.
- Modify `deepagent/deepagent/analysis_model.py` — planner prompt + sanitize custom steps.
- Modify `deepagent/deepagent/mcp_client.py` — `custom:` collection branch.
- Modify `deepagent/deepagent/graph.py` — pass custom names through plan/collect.
- Modify `deepagent/tests/test_mcp_client.py`, `deepagent/tests/test_graph.py` — coverage.
- Modify `server/app/services/dfir_investigation.py` — payload builder.
- Modify `server/tests/test_llm_deepagent.py` or new test — payload coverage.

## Task 1: MCP bridge tool

**Files:** `/tmp/mcp-velociraptor-upstream/mcp_velociraptor_bridge.py`

- [x] Step 1: implement `collect_custom_artifact` (regex check → existence/type check via `artifact_definitions() WHERE name = ...` → `_run_collection_tool` with `parameters=None`, `fields="*"`, limit/offset).
- [x] Step 2: `py_compile` + live smoke against dev Velociraptor: collect `Custom.Inventory.SmokeTest`, reject `Windows.System.Pslist`, reject a `SERVER`-type custom artifact.
- [x] Step 3: commit + push to `lephuhung/mcp-velociraptor`; record commit SHA.
- [x] Step 4: pin `deepagent/Dockerfile` `MCP_VELOCIRAPTOR_REF` to the new SHA.

## Task 2: DeepAgent dynamic catalog

**Files:** `deepagent/deepagent/{models,catalog,analysis_model,mcp_client,graph}.py`

- [x] Step 1: `CustomArtifactRef` + `InvestigationRequest.custom_artifacts` (≤20).
- [x] Step 2: `catalog.custom_tool_names(request)`, `catalog_prompt(custom)` second section, `sanitize_plan(plan, max_steps, custom_names)`.
- [x] Step 3: `VelociraptorMCP.collect(..., custom_names)` — resolve `custom:` prefix, membership check, locked args `limit=50, offset=0`.
- [x] Step 4: graph threads `custom_names` into sanitize + collect.
- [x] Step 5: tests — model validation, planner sanitize keep/drop, collect locked args + rejection.

## Task 3: Backend payload

**Files:** `server/app/services/dfir_investigation.py`, test

- [x] Step 1: load enabled CLIENT artifacts, parse `description` from stored YAML (cap 300), build `custom_artifacts` in `request_body`.
- [x] Step 2: test — payload contains only enabled CLIENT artifacts, description capped.

## Task 4: Verification

- [x] Step 1: server + deepagent `pytest` and `ruff` green.
- [x] Step 2: end-to-end smoke — bridge tool collects rows from the dev server for the previously pushed smoke artifact; DeepAgent `VelociraptorMCP.collect("custom:...")` over real MCP stdio returns rows + pagination.
