# DeepAgent MCP Collection Reliability Design

## Goal
Prevent a single Velociraptor collection from blocking a DFIR investigation indefinitely, while preserving safe structured observability and making timeout causes actionable.

## Evidence
For investigation `4095f6d5-f31e-49c1-8d01-34fc6c1a2da2`, DeepAgent successfully completed MCP initialization, client verification, and planning. Velociraptor accepted the first collection flow, but the MCP bridge did not return after waiting for flow completion. `VelociraptorMCP._invoke_tool()` currently awaits `tool.ainvoke()` without a deadline.

## Scope
1. Add a DeepAgent-configurable deadline around every MCP tool invocation.
2. Treat a timed-out collection as failed evidence and continue the graph with later allowed tools.
3. Emit safe JSON metadata that distinguishes a DeepAgent call deadline from an MCP exception; never include raw VQL, bridge error bodies, YAML, prompts, evidence, or report content.
4. Preserve successful/failed summary counts and add an explicit timeout count.
5. Prepare the MCP bridge integration for durable flow-level diagnosis. The bridge is cloned from a pinned external commit at Docker build, so any bridge change must be a tracked local patch or a pinned maintained fork, never an in-container edit.

## Design
### Phase 1: DeepAgent deadline and graceful degradation
- `Settings.mcp_tool_timeout_seconds` is configured through `DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS`; default 180 seconds, valid range 10–1800 seconds.
- `VelociraptorMCP._invoke_tool()` wraps `tool.ainvoke(arguments)` with `asyncio.wait_for()`.
- On `asyncio.TimeoutError`, it emits `mcp_tool_call` with `outcome=failed`, tool name, duration, `error_type=MCPToolTimeout`, and a constant safe message; it raises a dedicated `MCPToolTimeout` exception without copying raw tool input/output.
- Graph collection converts all tool failures, including `MCPToolTimeout`, to safe failed `EvidenceItem`s and continues. Raw exception strings are not propagated into evidence, model prompts, reports, callbacks, or logs.
- `job_summary` includes `timed_out_tool_count`; existing successful and failed counts remain compatible.

### Phase 2: flow-level diagnosis ownership
- Do not pretend a DeepAgent caller deadline identifies the failing component. It only proves the MCP call did not complete before the deadline.
- Replace the external bridge's synchronous start-and-wait collection behavior with a tracked lifecycle: start returns flow ID; bounded status polling returns `finished`, `flow_error`, `client_unavailable`, `collection_timeout`, or `result_read_timeout`.
- Persist the bridge change as either a patch applied by the DeepAgent Dockerfile after the pinned clone or a pinned maintained fork. Include flow ID, artifact/tool name, terminal category, and elapsed time only in structured logs/evidence metadata.
- No automatic duplicate collection retry. After a timeout, poll the same flow if its ID exists; only an explicit operator action creates a new flow.

## Security and operational constraints
- Read-only MCP tool allowlist remains unchanged.
- No API key, prompt, Velociraptor YAML/VQL, raw evidence, raw result, report content, or raw external error body is logged or returned in operational error fields.
- A timed-out job continues unless every planned tool fails; assessment must receive limitations from failed evidence.
- Existing active investigations must not be restarted merely to apply timeout configuration.

## Acceptance criteria
- A never-returning MCP call terminates by the configured deadline.
- The graph continues to a subsequent successful collection and reaches assessment/rendering.
- JSON logs have a bounded timeout event and job summary timeout count, with no sensitive fixture content.
- A normal MCP result remains unchanged.
- Unit tests cover timeout, graph continuation, safe redaction, summary counts, validation, and default configuration.
