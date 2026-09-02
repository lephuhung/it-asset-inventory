# DeepAgent MCP Flow Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each existing read-only Velociraptor MCP collection return a bounded, safely classified flow outcome while DeepAgent preserves that outcome in evidence, telemetry, and assessment limitations.

**Architecture:** A repository-tracked git patch changes the pinned bridge's shared `windows_*` collection path from synchronous `watch_monitoring()` to one lifecycle: availability preflight, single flow start, bounded `flows()` polling, and bounded result read. The bridge emits a reason enum and optional flow ID only. DeepAgent validates that envelope and maps it to typed safe evidence; its existing Phase 1 caller deadline remains a distinct final fallback.

**Tech Stack:** Python 3.12, asyncio, grpcio/pyvelociraptor in pinned `mcp-velociraptor`, FastMCP, Pydantic, LangGraph, pytest, unittest, Ruff, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-02-deepagent-mcp-flow-lifecycle-design.md`

## Global Constraints

- Apply the bridge change only through `deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch` against upstream commit `37375a0c1850a327818ccfee128229a995a9625b`.
- Do not edit `/opt/mcp-velociraptor` in a running container and do not rebuild/restart the DeepAgent service while an investigation is active.
- A read-only collection starts at most one Velociraptor flow. Polling or result reads must never call `collect_client` again.
- Never log, return in an operational error field, or embed in safe evidence: API keys, VQL, YAML, prompts, raw evidence/results, report content, raw gRPC/bridge errors, or flow status text.
- `mcp_call_deadline` is the Phase 1 caller deadline only. It is not synonymous with `collection_timeout`.
- Existing model-visible tool names and tool arguments in `deepagent/catalog.py` remain unchanged.
- Execution precondition: Phase 1 reliability changes must have a clean final review and be committed separately before starting this plan. Execute Phase 2 in a fresh worktree/branch from that commit; do not mix its commits with the current uncommitted Phase 1 files.
- Defaults: caller 180 seconds; collection 150 seconds; poll 2 seconds; result read 20 seconds; offline threshold 900 seconds. These defaults reserve a 10-second caller/bridge margin; custom deployments must keep `collection + 10 <= caller` to receive bridge categories rather than the Phase 1 caller deadline.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch` | Git-format patch adding the bridge lifecycle implementation and its stdlib tests to the pinned upstream tree. |
| `deepagent/Dockerfile` | Copies, verifies, and applies the patch after detached checkout. |
| `deepagent/deepagent/config.py` | Validates lifecycle settings and injects their numeric values into the MCP child environment. |
| `server/deploy/docker-compose.yml` | Supplies the five `DEEPAGENT_MCP_*` settings to the DeepAgent container. |
| `deepagent/deepagent/models.py` | Defines safe failure reason and flow-ID evidence fields. |
| `deepagent/deepagent/mcp_client.py` | Validates the bridge envelope, logs only safe lifecycle metadata, and preserves the caller-deadline fallback. |
| `deepagent/deepagent/graph.py` | Converts every known reason to fixed evidence copy and continues the graph. |
| `deepagent/deepagent/runner.py` and `deepagent/deepagent/api.py` | Adds safe failure-reason aggregation to all job-summary paths. |
| `deepagent/tests/test_mcp_client.py`, `test_graph.py`, `test_runner.py`, `test_api.py`, `test_observability.py` | Regression coverage for safe lifecycle propagation. |
| `docs/DEEPAGENT_CONTRACT.md` | Documents the Phase 2 configuration and category semantics. |

## Task 1: Create the reproducible, bounded bridge lifecycle patch

**Files:**
- Create: `deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch`
- Patch creates: `flow_lifecycle.py`, `tests/test_flow_lifecycle.py` in the upstream bridge tree
- Patch modifies: `velociraptor_api.py`, `mcp_velociraptor_bridge.py` in the upstream bridge tree

**Interfaces:**
- Consumes the bridge's existing `run_vql_query`, `start_collection`, and `get_flow_results` behavior.
- Produces `CollectionOutcome(ok: bool, data: list[dict] | None, reason: str | None, flow_id: str | None)`.
- Produces a collection-tool envelope with only `ok`, `data`, `reason`, and `metadata.flow_id`.

- [ ] **Step 1: Make a clean work copy at the exact pinned revision**

```bash
rm -rf /tmp/mcp-velociraptor-phase2
git clone https://github.com/lephuhung/mcp-velociraptor.git /tmp/mcp-velociraptor-phase2
git -C /tmp/mcp-velociraptor-phase2 checkout --detach 37375a0c1850a327818ccfee128229a995a9625b
```

Run: `git -C /tmp/mcp-velociraptor-phase2 rev-parse HEAD`

Expected: exactly `37375a0c1850a327818ccfee128229a995a9625b`.

- [ ] **Step 2: Write bridge lifecycle tests before implementation**

Create `/tmp/mcp-velociraptor-phase2/tests/test_flow_lifecycle.py`. Use `unittest` and an injected fake `query(vql, org_id, timeout_seconds)` callable; do not load FastMCP, credentials, or a live Velociraptor service.

```python
class FlowLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_flow_hits_collection_timeout_once(self):
        query = ScriptedQuery(
            client_rows=[{"client_id": "C.1", "last_seen_at": NOW}],
            start_rows=[{"flow_id": "F.1"}],
            flow_rows=[{"state": "RUNNING", "status": "untrusted"}],
        )
        outcome = await collect_readonly_flow(
            query=query, client_id="C.1", artifact="Windows.System.Pslist",
            org_id="", fields="*", result_scope="", parameters=None,
            collection_timeout_seconds=1, poll_seconds=1,
            result_read_timeout_seconds=1, offline_after_seconds=900,
            monotonic=TickingClock([0, 2]), sleep=AsyncMock(), now_epoch=lambda: NOW,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "collection_timeout")
        self.assertEqual(outcome.flow_id, "F.1")
        self.assertEqual(query.start_calls, 1)
        self.assertNotIn("untrusted", json.dumps(outcome.to_envelope()))
```

Add independent tests with these exact expected outcomes:

```python
# Missing or stale last_seen_at before start: client_unavailable, start_calls == 0.
# A flows() row with state == "ERROR": flow_error, flow_id retained.
# FINISHED then source query raises QueryDeadlineExceeded: result_read_timeout, start_calls == 1.
# A non-deadline query exception at any stage: external_error and no exception text in envelope.
# FINISHED then source rows: ok == True, metadata contains only flow_id.
```

- [ ] **Step 3: Run the new bridge tests and confirm they fail**

Run:

```bash
cd /tmp/mcp-velociraptor-phase2
python -m unittest tests.test_flow_lifecycle -v
```

Expected: FAIL because `flow_lifecycle` and `collect_readonly_flow` do not exist.

- [ ] **Step 4: Implement the lifecycle module with fixed enum output**

Create `flow_lifecycle.py` with these exact public definitions:

```python
SAFE_REASONS = frozenset({
    "client_unavailable", "collection_timeout", "flow_error",
    "result_read_timeout", "external_error",
})

@dataclass(frozen=True)
class CollectionOutcome:
    ok: bool
    data: list[dict] | None = None
    reason: str | None = None
    flow_id: str | None = None

    def to_envelope(self) -> dict:
        if self.ok:
            return {"ok": True, "data": self.data or {}, "metadata": _metadata(self.flow_id)}
        return {"ok": False, "reason": self.reason, "metadata": _metadata(self.flow_id)}
```

Implement `async collect_readonly_flow(...) -> CollectionOutcome` so it:

1. Queries exact `client_id` and checks numeric `last_seen_at`; returns `client_unavailable` before calling `start_collection` if missing or older than `offline_after_seconds`.
2. Starts exactly one flow and stores the returned `flow_id`; an absent/malformed start response returns `external_error`.
3. Polls `flows(client_id=..., session_id=...)` with `time.monotonic()`, treating missing rows, `RUNNING`, `PENDING`, and `IN_PROGRESS` as non-terminal. `FINISHED` proceeds to the read; `ERROR` returns `flow_error`; elapsed deadline returns `collection_timeout`.
4. Reads `source(client_id=..., flow_id=..., artifact=artifact + result_scope)` once after `FINISHED`; converts only the bridge's dedicated query-deadline exception to `result_read_timeout`.
5. Catches all other query exceptions and returns `external_error`; it never serializes an exception string or a state/status string.

Keep `flow_id` only if `re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value)` succeeds. `_metadata()` returns `{}` when validation fails.

- [ ] **Step 5: Add bounded query support and route existing wrappers through the lifecycle**

In `velociraptor_api.py`, extend `run_vql_query` with an optional `timeout_seconds: float | None` parameter and call the gRPC query iterator with that deadline when supplied. Raise a local `QueryDeadlineExceeded` only for a gRPC `DEADLINE_EXCEEDED` response; re-raise all other transport failures for lifecycle conversion to `external_error`.

In `mcp_velociraptor_bridge.py`, replace `_run_collection_tool()`'s call to `realtime_collection()` with `await collect_readonly_flow(...)`. Pass the existing `client_id`, artifact, parameters, fields, result scope, and org ID unchanged. Read these child environment variables once, validate them as positive integers, and use safe defaults if absent:

```python
MCP_COLLECTION_TIMEOUT_SECONDS = 150
MCP_FLOW_POLL_SECONDS = 2
MCP_RESULT_READ_TIMEOUT_SECONDS = 20
MCP_CLIENT_OFFLINE_AFTER_SECONDS = 900
```

Return `json.dumps(outcome.to_envelope(), default=str)`. Do not change any `windows_*` tool signature or tool name. Do not call `_json_error(str(exc))` from this collection path.

- [ ] **Step 6: Run the bridge tests and verify all categories**

Run:

```bash
cd /tmp/mcp-velociraptor-phase2
python -m unittest tests.test_flow_lifecycle -v
```

Expected: PASS; every failure envelope contains a reason from `SAFE_REASONS`, no fixture status/error text, and each test observes at most one start call.

- [ ] **Step 7: Generate and store the tracked patch**

```bash
cd /tmp/mcp-velociraptor-phase2
git add velociraptor_api.py mcp_velociraptor_bridge.py flow_lifecycle.py tests/test_flow_lifecycle.py
git diff --cached --binary > /home/windowsId/deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch
cd /home/windowsId
git apply --check deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch
```

Expected: `git apply --check` exits 0. The patch has no unrelated upstream formatting changes.

- [ ] **Step 8: Commit the bridge patch in isolation**

```bash
git add deepagent/patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch
git commit -m "feat(deepagent): patch bounded MCP flow lifecycle"
```

## Task 2: Make Docker patch application deterministic

**Files:**
- Modify: `deepagent/Dockerfile`

**Interfaces:**
- Consumes the tracked patch from Task 1.
- Produces `/opt/mcp-velociraptor` at the pinned revision plus the lifecycle patch, or fails image build before dependencies install.

- [ ] **Step 1: Add the Dockerfile patch copy and apply check**

Change the bridge build sequence to copy the patch before cloning and apply it after detached checkout:

```dockerfile
COPY patches/mcp-velociraptor/0001-bounded-readonly-flow-lifecycle.patch /tmp/mcp-flow-lifecycle.patch
RUN git clone https://github.com/lephuhung/mcp-velociraptor.git /opt/mcp-velociraptor \
    && git -C /opt/mcp-velociraptor checkout --detach "$MCP_VELOCIRAPTOR_REF" \
    && git -C /opt/mcp-velociraptor apply --check /tmp/mcp-flow-lifecycle.patch \
    && git -C /opt/mcp-velociraptor apply /tmp/mcp-flow-lifecycle.patch \
    && python -m venv /opt/mcp-venv \
    && /opt/mcp-venv/bin/pip install --no-cache-dir -r /opt/mcp-velociraptor/requirements.txt
```

- [ ] **Step 2: Build a temporary image only when no investigation is active**

Run only after checking no active investigation exists:

```bash
docker build -t asset-inventory-deepagent:phase2-verify deepagent
```

Expected: success. A patch context mismatch must fail this build rather than silently use unpatched upstream code.

- [ ] **Step 3: Run bridge tests inside the built image**

```bash
docker run --rm --entrypoint /opt/mcp-venv/bin/python \
  asset-inventory-deepagent:phase2-verify \
  -m unittest discover -s /opt/mcp-velociraptor/tests -p 'test_flow_lifecycle.py' -v
```

Expected: PASS without a Velociraptor server, credentials, or external result data.

- [ ] **Step 4: Commit the Docker delivery boundary**

```bash
git add deepagent/Dockerfile
git commit -m "build(deepagent): apply tracked MCP flow patch"
```

## Task 3: Validate and inject lifecycle budgets from DeepAgent

**Files:**
- Modify: `deepagent/deepagent/config.py`
- Modify: `server/deploy/docker-compose.yml`
- Modify: `deepagent/tests/test_mcp_client.py`

**Interfaces:**
- Produces four validated `Settings` fields and four numeric bridge child-process environment values.
- Consumes the existing Phase 1 `mcp_tool_timeout_seconds`.

- [ ] **Step 1: Write settings validation tests**

Add these tests to `deepagent/tests/test_mcp_client.py`:

```python
def test_mcp_flow_lifecycle_defaults_and_child_environment() -> None:
    settings = Settings()
    assert settings.mcp_collection_timeout_seconds == 150
    assert settings.mcp_flow_poll_seconds == 2
    assert settings.mcp_result_read_timeout_seconds == 20
    assert settings.mcp_client_offline_after_seconds == 900
    child_env = settings.mcp_env()
    assert child_env["MCP_COLLECTION_TIMEOUT_SECONDS"] == "150"
    assert child_env["MCP_FLOW_POLL_SECONDS"] == "2"
    assert child_env["MCP_RESULT_READ_TIMEOUT_SECONDS"] == "20"
    assert child_env["MCP_CLIENT_OFFLINE_AFTER_SECONDS"] == "900"


def test_mcp_flow_lifecycle_preserves_phase1_minimum_and_validates_read_budget() -> None:
    # Phase 1's documented minimum remains valid; its outer deadline may win.
    assert Settings(mcp_tool_timeout_seconds=10).mcp_tool_timeout_seconds == 10
    with pytest.raises(ValidationError):
        Settings(mcp_collection_timeout_seconds=150, mcp_result_read_timeout_seconds=150)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `cd deepagent && .venv/bin/python -m pytest -q tests/test_mcp_client.py -k lifecycle`

Expected: FAIL because lifecycle settings and child environment entries do not exist.

- [ ] **Step 3: Implement exact settings and cross-field validation**

Add Pydantic fields with these definitions:

```python
mcp_collection_timeout_seconds: int = Field(default=150, ge=10, le=1790)
mcp_flow_poll_seconds: int = Field(default=2, ge=1, le=60)
mcp_result_read_timeout_seconds: int = Field(default=20, ge=1, le=300)
mcp_client_offline_after_seconds: int = Field(default=900, ge=60, le=604800)
```

In an `@model_validator(mode="after")`, reject an instance unless:

```python
self.mcp_result_read_timeout_seconds < self.mcp_collection_timeout_seconds
```

Do not reject `mcp_tool_timeout_seconds=10`: that is an existing valid Phase 1 configuration. The default settings satisfy `150 + 10 <= 180`; document that custom settings which violate this operational margin can yield only `mcp_call_deadline`.

In `mcp_env()`, merge these four string values after parsing `DEEPAGENT_MCP_ENV_JSON`, so JSON configuration cannot override validated lifecycle budgets.

- [ ] **Step 4: Configure the four deployment values**

Add to the `deepagent` environment section of `server/deploy/docker-compose.yml`:

```yaml
DEEPAGENT_MCP_COLLECTION_TIMEOUT_SECONDS: "${DEEPAGENT_MCP_COLLECTION_TIMEOUT_SECONDS:-150}"
DEEPAGENT_MCP_FLOW_POLL_SECONDS: "${DEEPAGENT_MCP_FLOW_POLL_SECONDS:-2}"
DEEPAGENT_MCP_RESULT_READ_TIMEOUT_SECONDS: "${DEEPAGENT_MCP_RESULT_READ_TIMEOUT_SECONDS:-20}"
DEEPAGENT_MCP_CLIENT_OFFLINE_AFTER_SECONDS: "${DEEPAGENT_MCP_CLIENT_OFFLINE_AFTER_SECONDS:-900}"
```

- [ ] **Step 5: Run settings, lint, and Compose validation**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q tests/test_mcp_client.py && .venv/bin/ruff check deepagent/config.py tests/test_mcp_client.py
cd ../server && docker compose -p asset-inventory -f deploy/docker-compose.yml config --quiet
```

Expected: all pass.

- [ ] **Step 6: Commit the validated deployment configuration**

```bash
git add deepagent/deepagent/config.py deepagent/tests/test_mcp_client.py server/deploy/docker-compose.yml
git commit -m "feat(deepagent): configure MCP flow lifecycle budgets"
```

## Task 4: Preserve safe lifecycle outcomes in DeepAgent evidence

**Files:**
- Modify: `deepagent/deepagent/models.py`
- Modify: `deepagent/deepagent/mcp_client.py`
- Modify: `deepagent/deepagent/graph.py`
- Modify: `deepagent/tests/test_mcp_client.py`
- Modify: `deepagent/tests/test_graph.py`
- Modify: `deepagent/tests/test_observability.py`

**Interfaces:**
- Produces `EvidenceItem.failure_reason` and `EvidenceItem.flow_id`.
- Consumes bridge `{ok, reason, metadata.flow_id}` envelopes.
- Produces a `mcp_call_deadline` reason only from `MCPToolTimeout`.

- [ ] **Step 1: Write failing envelope and graph-continuation tests**

Add a fake `windows_pslist` MCP tool that returns this bridge envelope followed by a successful `windows_services` result:

```python
'{"ok": false, "reason": "flow_error", "metadata": {"flow_id": "F.123"}}'
```

Assert:

```python
assert evidence[0].ok is False
assert evidence[0].failure_reason == "flow_error"
assert evidence[0].flow_id == "F.123"
assert evidence[0].error == "MCP collection flow failed."
assert evidence[1].ok is True
```

Add an invalid-reason fixture containing sensitive text in `reason` and `metadata.flow_id`. Assert the evidence instead has `failure_reason == "external_error"`, `flow_id is None`, and none of the fixture text appears in stdout or serialized evidence.

Add a Phase 1 hanging tool fixture and assert `failure_reason == "mcp_call_deadline"` and `timeout is True`.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q tests/test_mcp_client.py tests/test_graph.py tests/test_observability.py -k 'reason or flow_id or deadline'
```

Expected: FAIL because models and envelope validation do not expose lifecycle metadata.

- [ ] **Step 3: Define safe reason and flow-ID model fields**

In `models.py`, define:

```python
MCPFailureReason = Literal[
    "mcp_call_deadline", "client_unavailable", "collection_timeout",
    "flow_error", "result_read_timeout", "external_error",
]
```

Add to `EvidenceItem`:

```python
failure_reason: MCPFailureReason | None = None
flow_id: str | None = Field(default=None, max_length=128)
```

Do not remove `timeout`; it remains true only for `mcp_call_deadline`.

- [ ] **Step 4: Validate bridge envelopes before logging or graph use**

In `mcp_client.py`, add one helper that accepts a decoded envelope and returns only `(reason, flow_id)` where:

```python
BRIDGE_FAILURE_REASONS = frozenset({
    "client_unavailable", "collection_timeout", "flow_error",
    "result_read_timeout", "external_error",
})
FLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
```

A missing/unknown reason becomes `external_error`; an invalid/missing flow ID becomes `None`. Never include `payload["error"]` in the helper output. Update `_log_tool_result()` to log only `failure_reason` and validated `flow_id` for failed collection envelopes.

- [ ] **Step 5: Map each reason to fixed evidence copy and preserve continuation**

In `graph.py`, use exactly this copy map:

```python
SAFE_COLLECTION_ERRORS = {
    "mcp_call_deadline": "MCP collection timed out.",
    "client_unavailable": "MCP target client is unavailable.",
    "collection_timeout": "MCP collection flow did not finish before its deadline.",
    "flow_error": "MCP collection flow failed.",
    "result_read_timeout": "MCP collection result read timed out.",
    "external_error": "MCP collection returned an external failure.",
}
```

For a failed envelope, create `EvidenceItem(ok=False, data=None, error=SAFE_COLLECTION_ERRORS[reason], failure_reason=reason, flow_id=flow_id, timeout=False)`. For `MCPToolTimeout`, use `mcp_call_deadline`, its existing fixed text, and `timeout=True`. Keep the current `after_collect()` edge unchanged so every later planned tool is attempted.

- [ ] **Step 6: Run evidence/observability tests and Ruff**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q tests/test_mcp_client.py tests/test_graph.py tests/test_observability.py
cd deepagent && .venv/bin/ruff check deepagent/models.py deepagent/mcp_client.py deepagent/graph.py tests/test_mcp_client.py tests/test_graph.py tests/test_observability.py
```

Expected: PASS; JSON output contains only enum reasons, fixed messages, and validated flow IDs.

- [ ] **Step 7: Commit typed evidence propagation**

```bash
git add deepagent/deepagent/models.py deepagent/deepagent/mcp_client.py deepagent/deepagent/graph.py deepagent/tests/test_mcp_client.py deepagent/tests/test_graph.py deepagent/tests/test_observability.py
git commit -m "feat(deepagent): retain safe MCP flow outcomes"
```

## Task 5: Aggregate reason counts and make assessment limitations explicit

**Files:**
- Modify: `deepagent/deepagent/analysis_model.py`
- Modify: `deepagent/deepagent/runner.py`
- Modify: `deepagent/deepagent/api.py`
- Modify: `deepagent/tests/test_runner.py`
- Modify: `deepagent/tests/test_api.py`

**Interfaces:**
- Produces `job_summary.failure_reason_counts: dict[str, int]` containing positive known-reason counts only.
- Consumes typed `EvidenceItem.failure_reason`.
- Produces an assessment prompt that treats operational reasons as limitations, never as evidence of absence.

- [ ] **Step 1: Write failing summary and assessment tests**

Add a runner fixture with one successful item, one `flow_error`, one `collection_timeout`, and one `mcp_call_deadline`. Assert:

```python
assert summary["successful_tool_count"] == 1
assert summary["failed_tool_count"] == 3
assert summary["timed_out_tool_count"] == 1
assert summary["failure_reason_counts"] == {
    "flow_error": 1,
    "collection_timeout": 1,
    "mcp_call_deadline": 1,
}
```

Use a raw-error sentinel in the fixture and assert it is absent from `json.dumps(summary)`.

Add a model fixture that captures the assessment prompt. Provide failed evidence with `failure_reason="flow_error"`; assert the prompt contains `failure_reason` and the fixed instruction that failed collection is a limitation, not evidence that the endpoint is safe.

Add an API runner-none failure test asserting:

```python
assert event["timed_out_tool_count"] == 0
assert event["failure_reason_counts"] == {}
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q tests/test_runner.py tests/test_api.py -k 'reason_counts or runner_none'
```

Expected: FAIL because the summary omits `failure_reason_counts`.

- [ ] **Step 3: Implement safe summary aggregation**

In `runner.py`, count `item.failure_reason` only when it is non-null, using `collections.Counter`. Serialize `{reason: count for reason, count in counter.items() if count > 0}` into every completed and failed runner `job_summary` event. Continue computing `timed_out_tool_count` from `item.timeout`, not reason text.

In `api.py`, include `failure_reason_counts={}` with the existing zero counts in the `runner is None` summary path.

- [ ] **Step 4: Make the limitation rule explicit to the assessment model**

Add this sentence immediately before `<untrusted_evidence>` in `analysis_model.py`:

```text
`failure_reason` và `timeout` là metadata vận hành an toàn. Mọi evidence `ok=false` phải được ghi nhận là limitation; không được suy luận máy an toàn hoặc không có dấu hiệu chỉ vì collection thất bại.
```

Do not create a new model output field and do not pass raw bridge status/error values.

- [ ] **Step 5: Run runner/API/model tests and Ruff**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q tests/test_runner.py tests/test_api.py tests/test_graph.py
cd deepagent && .venv/bin/ruff check deepagent/analysis_model.py deepagent/runner.py deepagent/api.py tests/test_runner.py tests/test_api.py
```

Expected: PASS.

- [ ] **Step 6: Commit summary and assessment behavior**

```bash
git add deepagent/deepagent/analysis_model.py deepagent/deepagent/runner.py deepagent/deepagent/api.py deepagent/tests/test_runner.py deepagent/tests/test_api.py
git commit -m "feat(deepagent): summarize MCP flow failure reasons"
```

## Task 6: Document, validate, and perform controlled operational verification

**Files:**
- Modify: `docs/DEEPAGENT_CONTRACT.md`
- Modify: `deepagent/.env.example`
- Modify: `deepagent/README.md`

**Interfaces:**
- Documents all five deadline settings, reason enum semantics, one-flow rule, and tracked-patch rebuild requirement.

- [ ] **Step 1: Document exact semantics and environment examples**

Add this configuration block to `deepagent/.env.example` and README deployment documentation:

```dotenv
DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS=180
DEEPAGENT_MCP_COLLECTION_TIMEOUT_SECONDS=150
DEEPAGENT_MCP_FLOW_POLL_SECONDS=2
DEEPAGENT_MCP_RESULT_READ_TIMEOUT_SECONDS=20
DEEPAGENT_MCP_CLIENT_OFFLINE_AFTER_SECONDS=900
```

Document the invariant `collection + 10 <= caller` and that `mcp_call_deadline` only means the MCP caller did not receive a response. List the five bridge reasons and state that `external_error` intentionally has no raw body.

- [ ] **Step 2: Update the contract document**

In `docs/DEEPAGENT_CONTRACT.md`, replace the Phase 2 future-tense paragraph with the delivered contract:

- bridge categories are `client_unavailable`, `collection_timeout`, `flow_error`, `result_read_timeout`, and `external_error`;
- `mcp_call_deadline` stays DeepAgent-owned;
- `failure_reason_counts` contains only safe enum values;
- no timeout/error creates another collection flow;
- bridge code is applied from the named patch at the pinned revision.

- [ ] **Step 3: Run complete static verification**

Run:

```bash
cd deepagent && .venv/bin/python -m pytest -q
cd deepagent && .venv/bin/ruff check deepagent tests
cd ../server && docker compose -p asset-inventory -f deploy/docker-compose.yml config --quiet
cd .. && git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Build and test the candidate image only after confirming no active investigation**

Run:

```bash
docker build -t asset-inventory-deepagent:phase2-verify deepagent
docker run --rm --entrypoint /opt/mcp-venv/bin/python asset-inventory-deepagent:phase2-verify -m unittest discover -s /opt/mcp-velociraptor/tests -p 'test_flow_lifecycle.py' -v
```

Expected: build and bridge lifecycle tests pass. Do not tag as `latest`, run Compose up, or restart a service in this task.

- [ ] **Step 5: Request review before deployment**

Provide reviewers the commits, spec, plan, complete pytest/Ruff/Compose/build outputs, and confirm no active investigation was restarted. Require review specifically for: patch applies at pinned ref, `flows().state` is used, raw bridge errors cannot enter any envelope, and exactly one `collect_client` occurs per test lifecycle.

- [ ] **Step 6: Commit documentation and validation artifacts**

```bash
git add docs/DEEPAGENT_CONTRACT.md deepagent/.env.example deepagent/README.md
git commit -m "docs(deepagent): document MCP flow lifecycle contract"
```

## Plan self-review

- **Spec coverage:** Task 1 implements all bridge state/reason outcomes and single-flow behavior. Task 2 makes the patch reproducible. Task 3 enforces deadline hierarchy. Task 4 converts bridge envelopes to safe evidence and preserves graph continuation. Task 5 adds safe summaries and limitations. Task 6 documents and validates the full contract.
- **Placeholder scan:** The plan contains no open implementation placeholders or unspecified error handling; every failure category, default, validation rule, and command is explicit.
- **Type consistency:** Bridge reasons exclude `mcp_call_deadline`; `MCPFailureReason` adds it only in DeepAgent. `timeout=True` is reserved for `mcp_call_deadline`; `failure_reason_counts` reads typed evidence rather than external strings. The existing valid 10-second Phase 1 caller setting remains accepted; the documented 10-second bridge margin is an operational deployment invariant, not a breaking validation rule.
