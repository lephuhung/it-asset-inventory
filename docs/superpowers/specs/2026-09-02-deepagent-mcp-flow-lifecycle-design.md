# DeepAgent MCP Flow Lifecycle Design

## Status and relationship to Phase 1

This design implements Phase 2 from `2026-09-02-deepagent-mcp-reliability-design.md`. It supersedes only that document's high-level Phase 2 section. Phase 1's caller deadline remains enabled as the final safety boundary.

## Problem

The pinned `mcp-velociraptor` bridge runs every `windows_*` collection through `realtime_collection()`. That helper starts a Velociraptor flow and then blocks in `watch_monitoring(artifact='System.Flow.Completion')`. Consequently, a flow that never completes prevents an MCP response; Phase 1 can only record `mcp_call_deadline`, not the cause or the flow ID.

The bridge already has `start_collection()` and `get_collection_results()`, but its flow-status helper infers only `RUNNING` or `FINISHED` from flow logs. It cannot detect a terminal `ERROR`, bounds neither polling nor result reads, and is intentionally not reachable from the DeepAgent graph allowlist.

## Goals

1. Replace synchronous start-and-wait behavior for existing read-only `windows_*` MCP tools with a bounded flow lifecycle.
2. Return a stable, safe envelope that distinguishes known flow outcomes without using raw exception text.
3. Preserve the existing DeepAgent tool catalog and arguments: the model continues to select only existing named `windows_*` tools.
4. Preserve the caller deadline as a separate category, `mcp_call_deadline`.
5. Keep the bridge change reproducible from its pinned upstream commit via a tracked repository patch.

## Non-goals

- No automatic second `collect_client` invocation, including after any timeout or error.
- No cancellation/termination of Velociraptor flows.
- No bridge edit inside a running container.
- No raw VQL, YAML, API key, result body, prompt, report content, bridge exception text, or Velociraptor status text in operational error fields.
- No public API contract change for the portal or backend callback payload.

## Bridge lifecycle contract

The tracked patch changes the bridge's shared `_run_collection_tool()` path used by the existing read-only `windows_*` wrappers. It does not convert those tools into start-only tools.

For one collection invocation the bridge does exactly this:

1. Check the target's availability using `clients()` and the configured `last_seen_at` threshold. A missing client or a client last seen before the threshold returns `client_unavailable`; it does not start a flow.
2. Start one flow with `collect_client` and retain its `flow_id`.
3. Poll `flows(client_id=..., session_id=...)` until its state is `FINISHED`, `ERROR`, or the lifecycle deadline expires. `ERROR` returns `flow_error`; an unfinished flow at the deadline returns `collection_timeout`.
4. Once `FINISHED`, issue one bounded `source(client_id=..., flow_id=..., artifact=...)` read. A read deadline returns `result_read_timeout`.
5. Return result rows only on success.

Flow status is determined from `flows().state`, not from the existence of a `System.Flow.Completion` log record. A transient absent flow row is treated as non-terminal until the collection deadline; raw query/transport failures are returned as the generic safe `external_error` category.

### Safe envelope

Every read-only collection wrapper returns JSON in exactly one of these forms:

```json
{"ok": true, "data": [], "metadata": {"flow_id": "F.123"}}
```

```json
{"ok": false, "reason": "flow_error", "metadata": {"flow_id": "F.123"}}
```

`reason` is required only when `ok` is false and is one of:

- `client_unavailable`
- `collection_timeout`
- `flow_error`
- `result_read_timeout`
- `external_error`

`metadata` may contain only a validated `flow_id`; it never contains flow status text, VQL, exception text, or collection parameters. Bridge startup and unrelated non-collection tools keep their current envelopes; DeepAgent maps a missing or invalid reason to `external_error`.

## Deadline configuration

DeepAgent owns all deployment configuration and injects only numeric child-process values into the bridge environment:

| DeepAgent setting | Child bridge environment | Default | Valid range |
| --- | --- | ---: | ---: |
| `DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS` | n/a; Phase 1 caller deadline | 180 | 10–1800 |
| `DEEPAGENT_MCP_COLLECTION_TIMEOUT_SECONDS` | `MCP_COLLECTION_TIMEOUT_SECONDS` | 150 | 10–1790 |
| `DEEPAGENT_MCP_FLOW_POLL_SECONDS` | `MCP_FLOW_POLL_SECONDS` | 2 | 1–60 |
| `DEEPAGENT_MCP_RESULT_READ_TIMEOUT_SECONDS` | `MCP_RESULT_READ_TIMEOUT_SECONDS` | 20 | 1–300 |
| `DEEPAGENT_MCP_CLIENT_OFFLINE_AFTER_SECONDS` | `MCP_CLIENT_OFFLINE_AFTER_SECONDS` | 900 | 60–604800 |

The defaults reserve a ten-second response margin (`150 + 10 <= 180`). The existing Phase 1 caller range remains valid down to ten seconds, so a user-selected caller deadline is not rejected merely because it is shorter than the bridge lifecycle budget. In that configuration the outer caller can win and emits only `mcp_call_deadline`; operators must keep `collection + 10 <= caller` when they require a bridge-provided flow category.

Validation requires `mcp_result_read_timeout_seconds < mcp_collection_timeout_seconds`. Bridge collection polling uses a monotonic overall deadline; per-query gRPC timeouts never exceed remaining lifecycle time.

If the bridge fails to respond before the outer caller deadline, Phase 1 emits only `mcp_call_deadline`. It must not relabel that outcome as `collection_timeout`.

## DeepAgent evidence and observability contract

`EvidenceItem` gains safe lifecycle metadata:

- `failure_reason: Literal["mcp_call_deadline", "client_unavailable", "collection_timeout", "flow_error", "result_read_timeout", "external_error"] | None`
- `flow_id: str | None`, accepted only when it matches `^[A-Za-z0-9._-]{1,128}$`.

Existing `timeout: bool` remains for backwards-compatible `timed_out_tool_count` and is true only for `mcp_call_deadline`. Graph errors use fixed copy selected from the reason enum. The model receives these safe fields and is instructed to include failed collections as limitations.

`job_summary` keeps existing success/failed counts and `timed_out_tool_count`, and adds `failure_reason_counts`. The map has only known enum keys with positive counts. `mcp_tool_call` events log the safe reason and validated `flow_id` when available; no raw error value is logged.

## Tracked bridge delivery

The bridge remains pinned to `37375a0c1850a327818ccfee128229a995a9625b`. Store a git-format patch at:

`deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch`

The Dockerfile copies it before cloning, verifies it with `git apply --check`, and applies it immediately after detached checkout. The patch adds bridge-local standard-library `unittest` coverage for lifecycle state transitions; Docker validation runs that test from the built image. An apply conflict is a build failure, forcing review whenever the pinned bridge ref changes.

## Acceptance criteria

- A flow stuck in `RUNNING` yields a safe `collection_timeout` envelope before the 180-second caller deadline, retaining the flow ID.
- A `flows().state == ERROR` yields `flow_error`, never a raw status string.
- A bounded `source()` read yields `result_read_timeout`; no second flow is started.
- An offline/missing client yields `client_unavailable` before `collect_client`.
- A bridge/transport failure with no known lifecycle reason yields only `external_error`.
- An outer non-returning MCP call remains `mcp_call_deadline` and increments only `timed_out_tool_count`.
- Graph execution continues after every failure category; the assessment sees a safe limitation marker.
- Patch application, bridge lifecycle unit tests, DeepAgent tests, Ruff, Compose validation, and `git diff --check` all pass.
