# DeepAgent MCP Collection Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound every DeepAgent MCP call, continue investigation after a timed-out tool, and record safe timeout telemetry.

**Architecture:** The immediate reliability boundary is DeepAgent's `VelociraptorMCP._invoke_tool()`: it receives a configurable caller deadline and raises a dedicated safe timeout exception. Graph collection converts all external failures to safe failed evidence and keeps executing later steps. Phase 2 flow-level cause classification requires a tracked patch/fork for the external MCP bridge and is deliberately not simulated by parsing error text.

**Tech Stack:** Python 3.12, asyncio, Pydantic settings, LangGraph, pytest, Ruff, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-02-deepagent-mcp-reliability-design.md`

## Global Constraints

- Default `DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS` is 180; accepted range is 10–1800.
- Never log or propagate raw MCP error bodies, VQL, YAML, prompts, evidence, results, or reports.
- The read-only allowlist and tool arguments remain unchanged.
- No duplicate collection retry is introduced.
- Apply no untracked bridge modification inside a running container.

---

### Task 1: Bound MCP invocation and preserve safe diagnostics

**Files:**
- Modify: `deepagent/deepagent/config.py`
- Modify: `deepagent/deepagent/mcp_client.py`
- Modify: `deepagent/tests/test_mcp_client.py`

**Interfaces:**
- Produces `Settings.mcp_tool_timeout_seconds: int` from `DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS`.
- Produces `MCPToolTimeout`, raised by `_invoke_tool()` after the configured deadline.
- Produces a `mcp_tool_call` failed event with `error_type="MCPToolTimeout"` and constant safe message.

- [ ] **Step 1: Write failing timeout test**

```python
@pytest.mark.asyncio
async def test_mcp_tool_timeout_emits_safe_metadata(capsys):
    class HangingTool:
        async def ainvoke(self, _arguments):
            await asyncio.Event().wait()

    client = VelociraptorMCP.__new__(VelociraptorMCP)
    client.settings = Settings(mcp_tool_timeout_seconds=0.01)
    with pytest.raises(MCPToolTimeout):
        await client._invoke_tool(
            tool=HangingTool(), tool_name="windows_pslist", arguments={}
        )
    event = json.loads(capsys.readouterr().out)
    assert event["error_type"] == "MCPToolTimeout"
    assert event["error_message"] == "MCP tool call exceeded its configured deadline."
```

- [ ] **Step 2: Run the focused test and verify it fails because no deadline/exception exists**

Run: `cd deepagent && .venv/bin/python -m pytest -q tests/test_mcp_client.py::test_mcp_tool_timeout_emits_safe_metadata`

- [ ] **Step 3: Implement the minimal deadline contract**

```python
class MCPToolTimeout(TimeoutError):
    """A bounded caller deadline expired before an MCP tool returned."""

raw = await asyncio.wait_for(
    tool.ainvoke(arguments), timeout=self.settings.mcp_tool_timeout_seconds
)
```

Catch `asyncio.TimeoutError`, log the constant safe metadata, and raise `MCPToolTimeout(tool_name)` with no raw message.

- [ ] **Step 4: Add settings validation test and implementation**

```python
assert Settings(mcp_tool_timeout_seconds=10).mcp_tool_timeout_seconds == 10
with pytest.raises(ValidationError):
    Settings(mcp_tool_timeout_seconds=9)
```

Use `Field(default=180, ge=10, le=1800)`.

- [ ] **Step 5: Run focused tests and Ruff**

Run: `cd deepagent && .venv/bin/python -m pytest -q tests/test_mcp_client.py && .venv/bin/ruff check deepagent/config.py deepagent/mcp_client.py tests/test_mcp_client.py`

### Task 2: Continue LangGraph safely after external tool failures

**Files:**
- Modify: `deepagent/deepagent/graph.py`
- Modify: `deepagent/deepagent/runner.py`
- Modify: `deepagent/tests/test_graph.py`
- Modify: `deepagent/tests/test_runner.py`

**Interfaces:**
- Consumes `MCPToolTimeout` or another collection exception.
- Produces `EvidenceItem(ok=False, error="MCP collection failed: <safe exception type>.")` without exception body.
- Produces `job_summary.timed_out_tool_count: int`.

- [ ] **Step 1: Write failing graph continuation test**

```python
async def collect(self, *, tool_name, **_kwargs):
    if tool_name == "windows_pslist":
        raise MCPToolTimeout(tool_name)
    return {"ok": True, "data": [{"safe": "metadata"}]}

result = await graph.ainvoke({"request": request()})
assert [item.ok for item in result["evidence"]] == [False, True]
assert "raw-evidence-should-never-appear" not in result["evidence"][0].error
```

- [ ] **Step 2: Run focused graph test and verify it fails if raw errors are retained or graph stops**

Run: `cd deepagent && .venv/bin/python -m pytest -q tests/test_graph.py::test_graph_continues_after_a_timed_out_collection`

- [ ] **Step 3: Implement safe evidence error mapping**

```python
def _safe_collection_error(exc: BaseException) -> str:
    if isinstance(exc, MCPToolTimeout):
        return "MCP collection timed out."
    return f"MCP collection failed: {type(exc).__name__}."
```

Use it for failed envelopes and exceptions; do not use `str(exc)`.

- [ ] **Step 4: Write failing runner summary test**

```python
assert summary["timed_out_tool_count"] == 1
assert raw_evidence not in json.dumps(summary)
```

- [ ] **Step 5: Add the count using `isinstance(item.error, ...)`-free safe evidence metadata**

Add an explicit non-sensitive timeout marker to `EvidenceItem` state/metadata or calculate it from the constant timeout error string. Do not infer from raw external text.

- [ ] **Step 6: Run focused graph/runner tests and Ruff**

Run: `cd deepagent && .venv/bin/python -m pytest -q tests/test_graph.py tests/test_runner.py && .venv/bin/ruff check deepagent/graph.py deepagent/runner.py tests/test_graph.py tests/test_runner.py`

### Task 3: Verify deployment and document bridge ownership boundary

**Files:**
- Modify: `server/deploy/docker-compose.yml` only if an explicit timeout environment value is needed beyond the default.
- Modify: `deepagent/README.md` or `docs/DEEPAGENT_CONTRACT.md` with timeout environment, semantics, and the tracked patch/fork requirement for Phase 2.
- Test: `deepagent/tests/test_observability.py`

**Interfaces:**
- Documents that a caller timeout means `mcp_call_deadline`, not proof that Velociraptor itself failed.
- Documents future bridge lifecycle categories: `client_unavailable`, `collection_timeout`, `flow_error`, `result_read_timeout`.

- [ ] **Step 1: Write failing documentation/observability assertion for timeout event safety**

```python
assert event["phase"] == "mcp_tool_call"
assert event["error_type"] == "MCPToolTimeout"
assert "raw-evidence-should-never-appear" not in json.dumps(event)
```

- [ ] **Step 2: Run the focused test**

Run: `cd deepagent && .venv/bin/python -m pytest -q tests/test_observability.py`

- [ ] **Step 3: Add concise documentation and environment example**

```text
DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS=180
```

Document that no in-container bridge edits survive rebuild; Phase 2 requires a tracked Dockerfile-applied patch or maintained fork.

- [ ] **Step 4: Run all DeepAgent tests, Ruff, Compose validation, and diff check**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q && .venv/bin/ruff check deepagent tests
cd ../server && docker compose -p asset-inventory -f deploy/docker-compose.yml config --quiet
git diff --check
```

- [ ] **Step 5: Commit only the reliability feature files**

```bash
git add deepagent server/deploy/docker-compose.yml docs/DEEPAGENT_CONTRACT.md
git commit -m "fix(deepagent): bound MCP collection calls"
```

## Plan Self-Review

- Spec coverage: Task 1 implements the caller deadline and safe timeout event; Task 2 makes timeout non-terminal and adds summary accounting; Task 3 verifies and documents the immutable upstream bridge boundary.
- Placeholder scan: no TODO/TBD items; Phase 2 is explicitly documented as a separate tracked bridge lifecycle project because this repository does not own the imported helper implementation.
- Type consistency: `MCPToolTimeout` is emitted by Task 1 and consumed by Task 2; timeout count has a dedicated safe marker rather than matching external error text.
