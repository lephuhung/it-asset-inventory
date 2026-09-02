# DeepAgent FIFO Queue and Bounded Event-Log Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dispatch DeepAgent investigations through a durable FIFO queue with at most 2 (configurable 1–3) active jobs and replace unbounded event-log retrieval with safe bounded triage and automatic detail expansion.

**Architecture:** PostgreSQL `pending` rows are the FIFO queue; backend claims only free slots atomically while the DeepAgent semaphore is a second capacity guard. A pinned MCP bridge patch adds typed, read-only bounded event-log helpers. The graph uses a 100-row metadata sample followed by at most two validated 50-row detail requests, and serializes all evidence under one aggregate prompt budget.

**Tech Stack:** FastAPI, SQLAlchemy async/PostgreSQL, LangGraph, Pydantic, FastMCP/Velociraptor, Docker Compose, pytest, TypeScript/Next.js.

**Spec:** `docs/superpowers/specs/2026-09-02-deepagent-queue-bounded-log-triage-design.md`

## Global Constraints

- Keep every DFIR operation read-only; do not expose `run_vql`, `collect_artifact`, file collection, YARA, quarantine, or process-kill to the model.
- `DEEPAGENT_MAX_CONCURRENT_JOBS` is an integer from 1 through 3, default 2, and is supplied identically to API and DeepAgent Compose services.
- Queue order is FIFO by `dfir_investigations.created_at`; PostgreSQL locking uses `FOR UPDATE SKIP LOCKED`.
- Initial event-log triage has at most 100 metadata rows; automatic expansion has at most two detail requests of 50 rows each.
- Expansion time windows must be within the immutable case range, no longer than 60 minutes, and Event IDs must come from the initial sample.
- The aggregate assessment evidence serialized into the LLM prompt must not exceed `max_evidence_chars`.
- Do not log raw evidence, API keys, api_client.yaml, prompt text, or model-supplied unsafe values.

---

## File Structure

- Modify `server/app/core/config.py` — validate shared backend queue capacity.
- Modify `server/app/services/dfir_investigation.py` — atomically reconcile/claim FIFO DeepAgent work instead of dispatching all active rows.
- Modify `server/tests/test_llm_deepagent.py` — queue capacity, FIFO, concurrent-claim and restart-recovery tests.
- Modify `server/deploy/docker-compose.yml` — inject the same bounded capacity into API and DeepAgent.
- Modify `deepagent/deepagent/config.py` — validate evidence/page and profile timeout settings.
- Modify `deepagent/deepagent/models.py` — typed `EventLogExpansion` decision and bounded event-log page metadata.
- Modify `deepagent/deepagent/catalog.py` — code-owned triage/detail policies and no model-owned raw arguments.
- Modify `deepagent/deepagent/mcp_client.py` — typed bridge methods, source row limits, and safe page metadata.
- Modify `deepagent/deepagent/graph.py` — six base calls, validated expansion stage, and aggregate evidence budget.
- Modify `deepagent/deepagent/analysis_model.py` — constrained expansion decision prompt/parser.
- Modify `deepagent/deepagent/runner.py` — progress metadata for triage/expansion and safe limitation propagation.
- Modify `deepagent/deepagent/api.py` — initialize semaphore with validated shared capacity and preserve queued status.
- Create `deepagent/patches/mcp-velociraptor-bounded-event-log.patch` — patch pinned upstream bridge/API result calls with specialized, read-only `LIMIT` helpers.
- Modify `deepagent/Dockerfile` — apply the tracked patch immediately after checking out the pinned MCP commit.
- Modify `deepagent/tests/test_mcp_client.py`, `deepagent/tests/test_graph.py`, `deepagent/tests/test_models.py`, `deepagent/tests/test_runner.py`, and `deepagent/tests/test_api.py` — unit/regression coverage.
- Modify `portal/app/(portal)/llm-dfir/investigations/[id]/page.tsx` and `portal/components/machine-investigation-panel.tsx` — label `pending` as FIFO queued and show safe progress metadata when supplied.
- Modify `deepagent/README.md` and `docs/RUNBOOK.md` — explain capacity configuration, source limits, and operational metrics.

## Task 1: Add one shared capacity setting and durable FIFO claims

**Files:**
- Modify: `server/app/core/config.py`
- Modify: `server/app/services/dfir_investigation.py`
- Modify: `server/deploy/docker-compose.yml`
- Test: `server/tests/test_llm_deepagent.py`

**Interfaces:**
- Produces `Settings.deepagent_max_concurrent_jobs: int` validated to `1 <= value <= 3`.
- Produces `claim_deepagent_dispatches(db: AsyncSession, capacity: int) -> list[DfirInvestigation]`.
- Consumes existing `DfirInvestigation.status`, `created_at`, `external_orchestrator`, and `external_job_id`.

- [ ] **Step 1: Write failing queue tests**

```python
@pytest.mark.asyncio
async def test_deepagent_dispatch_claims_oldest_pending_rows_up_to_capacity(session_factory):
    async with session_factory() as db:
        first, second, third = await seed_deepagent_investigations(db, count=3)
        claimed = await claim_deepagent_dispatches(db, capacity=2)
        assert [row.id for row in claimed] == [first.id, second.id]
        await db.refresh(third)
        assert third.status == "pending"


@pytest.mark.asyncio
async def test_deepagent_dispatch_claim_respects_existing_active_slots(session_factory):
    async with session_factory() as db:
        active = await seed_deepagent_investigation(db, status="analyzing")
        queued = await seed_deepagent_investigations(db, count=2)
        claimed = await claim_deepagent_dispatches(db, capacity=2)
        assert [row.id for row in claimed] == [queued[0].id]
        assert active.status == "analyzing"
```

Add a validation test for values 0 and 4 plus accepted values 1, 2, and 3.

- [ ] **Step 2: Run the targeted tests to verify failure**

Run: `cd server && .venv/bin/pytest tests/test_llm_deepagent.py -k 'dispatch_claim or max_concurrent' -v`

Expected: FAIL because the setting and claim helper do not exist.

- [ ] **Step 3: Implement atomic capacity accounting and claim**

Add a Pydantic field in `server/app/core/config.py`:

```python
deepagent_max_concurrent_jobs: int = Field(default=2, ge=1, le=3)
```

In `dfir_investigation.py`, count active DeepAgent rows, calculate `available = max(capacity - active_count, 0)`, lock the earliest `pending` DeepAgent rows with `with_for_update(skip_locked=True)`, and reserve each selected row by assigning its deterministic `deepagent-{id}` job ID and dispatch metadata before the HTTP call. Refactor `run_pending_investigations()` to reconcile active DeepAgent rows first, then invoke this claim helper and dispatch only the claimed rows. Do not change local-LLM investigation behavior.

- [ ] **Step 4: Wire one Compose variable into both services**

Add the same environment value to API and DeepAgent:

```yaml
DEEPAGENT_MAX_CONCURRENT_JOBS: "${DEEPAGENT_MAX_CONCURRENT_JOBS:-2}"
```

Do not define different backend and DeepAgent values.

- [ ] **Step 5: Run targeted tests**

Run: `cd server && .venv/bin/pytest tests/test_llm_deepagent.py -k 'dispatch_claim or max_concurrent or job_missing' -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/app/core/config.py server/app/services/dfir_investigation.py server/deploy/docker-compose.yml server/tests/test_llm_deepagent.py
git commit -m "feat(dfir): dispatch DeepAgent investigations through FIFO capacity queue"
```

## Task 2: Patch the pinned MCP bridge with bounded, read-only event-log retrieval

**Files:**
- Create: `deepagent/patches/mcp-velociraptor-bounded-event-log.patch`
- Modify: `deepagent/Dockerfile`
- Test: `deepagent/tests/test_mcp_client.py`

**Interfaces:**
- Produces bridge tools `windows_event_logs_triage(client_id, org_id, DateAfter, DateBefore, profile_id, max_rows)` and `windows_event_logs_detail(client_id, org_id, DateAfter, DateBefore, event_ids, max_rows)`.
- Both tools accept only code-defined profile IDs/fields and cap `max_rows` to their caller-provided hard maximum.
- Produces source result metadata `{rows, original_rows, returned_rows, truncated}` without raw bridge errors.

- [ ] **Step 1: Write failing adapter tests for strict bridge arguments**

```python
@pytest.mark.asyncio
async def test_event_log_triage_passes_fixed_metadata_fields_and_100_row_cap():
    tool = FakeTool('{"ok": true, "data": []}')
    client = configured_client_with_tools(windows_event_logs_triage=tool)
    await client.collect_event_log_triage(client_id="C.1", org_id="", time_from=FROM, time_to=TO)
    assert tool.calls[0]["max_rows"] == 100
    assert tool.calls[0]["Fields"] == "EventTime,Computer,Channel,Provider,EventID"


@pytest.mark.asyncio
async def test_event_log_detail_rejects_unknown_profile_and_more_than_50_rows():
    client = configured_client_with_tools()
    with pytest.raises(MCPPolicyError):
        await client.collect_event_log_detail(
            client_id="C.1", org_id="", time_from=FROM, time_to=TO,
            event_ids=["9999"], max_rows=51,
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd deepagent && .venv/bin/pytest tests/test_mcp_client.py -k 'event_log_triage or event_log_detail' -v`

Expected: FAIL because the typed methods/tools do not exist.

- [ ] **Step 3: Create the upstream patch and apply it in Dockerfile**

Patch the checked-out bridge and its `velociraptor_api.py` to add dedicated read-only helpers. The source-result VQL must append a validated `LIMIT` and use fixed `SELECT` fields. The triage helper accepts only named code-owned profiles; the detail helper accepts a validated Event-ID list and fixed detail fields. Neither helper accepts VQL, arbitrary paths, arbitrary field lists, or arbitrary regexes.

Apply it after checkout:

```dockerfile
COPY patches/mcp-velociraptor-bounded-event-log.patch /tmp/
RUN git -C /opt/mcp-velociraptor apply /tmp/mcp-velociraptor-bounded-event-log.patch
```

- [ ] **Step 4: Implement typed `VelociraptorMCP` methods**

Add `collect_event_log_triage()` and `collect_event_log_detail()` that construct only validated arguments, invoke the corresponding bridge tool through `_invoke_tool`, and return envelopes with bounded row metadata. Retain ordinary `collect()` for non-event tools.

- [ ] **Step 5: Run unit tests and build smoke test**

Run:

```bash
cd deepagent && .venv/bin/pytest tests/test_mcp_client.py -v
docker compose -p asset-inventory -f server/deploy/docker-compose.yml build deepagent
```

Expected: all adapter tests pass and the Docker build applies the patch successfully.

- [ ] **Step 6: Commit**

```bash
git add deepagent/Dockerfile deepagent/patches/mcp-velociraptor-bounded-event-log.patch deepagent/deepagent/mcp_client.py deepagent/tests/test_mcp_client.py
git commit -m "feat(deepagent): bound event-log retrieval in MCP bridge"
```

## Task 3: Add constrained model escalation and aggregate evidence budgeting

**Files:**
- Modify: `deepagent/deepagent/models.py`
- Modify: `deepagent/deepagent/catalog.py`
- Modify: `deepagent/deepagent/analysis_model.py`
- Modify: `deepagent/deepagent/graph.py`
- Modify: `deepagent/deepagent/config.py`
- Test: `deepagent/tests/test_models.py`
- Test: `deepagent/tests/test_graph.py`

**Interfaces:**
- Produces `EventLogExpansion(date_after: datetime, date_before: datetime, event_ids: list[str], rationale: str)`.
- Produces `validate_event_log_expansions(expansions, request_range, sampled_event_ids) -> list[EventLogExpansion]`.
- Produces `fit_evidence_budget(evidence: list[EvidenceItem], max_chars: int) -> list[EvidenceItem]`.

- [ ] **Step 1: Write failing validation and budget tests**

```python
def test_expansion_rejects_time_outside_case_window():
    expansion = EventLogExpansion(date_after=FROM - timedelta(seconds=1), date_before=FROM, event_ids=["4688"], rationale="x")
    assert validate_event_log_expansions([expansion], REQUEST_RANGE, {"4688"}) == []


def test_expansion_keeps_at_most_two_50_row_requests_with_sampled_ids():
    expansions = [valid_expansion("4688"), valid_expansion("1102"), valid_expansion("4625")]
    assert len(validate_event_log_expansions(expansions, REQUEST_RANGE, {"4688", "1102", "4625"})) == 2


def test_fit_evidence_budget_never_exceeds_global_max_chars():
    evidence = [
        EvidenceItem(
            evidence_id=f"E-{index:03d}", tool="windows_event_logs",
            collected_at=datetime.now(UTC), ok=True, data={"payload": "x" * 80_000},
        )
        for index in range(3)
    ]
    bounded = fit_evidence_budget(evidence, max_chars=120_000)
    assert len(json.dumps([item.model_dump(mode="json") for item in bounded])) <= 120_000
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd deepagent && .venv/bin/pytest tests/test_models.py tests/test_graph.py -k 'expansion or evidence_budget' -v`

Expected: FAIL because the models and helpers do not exist.

- [ ] **Step 3: Add exact schemas and validators**

Add Pydantic models for the expansion response. Validation must reject more than two items, durations over 60 minutes, timestamps outside `request.time_range`, empty or unknown Event IDs, and values that fail the strict model schema. Record invalid choices as safe limitations, not external error text.

Set `max_steps=6` for ordinary plan sanitization; the graph may add at most two physical detail calls after event-log triage.

- [ ] **Step 4: Add two-stage graph collection**

When the sanitized plan contains `windows_event_logs`, call `collect_event_log_triage()` instead of generic collection. Extract only sampled Event IDs from trusted envelope structure, ask `AnalysisModel.plan_event_log_expansion()` for the strict expansion object, validate it, and invoke at most two detail calls. Ordinary evidence failures and page timeouts must continue to the assessment node.

- [ ] **Step 5: Enforce the aggregate evidence budget before assessment**

Implement deterministic JSON-size accounting. Preserve evidence IDs, tools, success/error/timeout flags, truncation metadata, and the earliest safe preview. Reduce data fields until the serialized evidence list is at or below `settings.max_evidence_chars`; do not remove the evidence item entirely unless its data budget is zero. Pass only this bounded list to `model.assess()` and report rendering.

- [ ] **Step 6: Run graph/model tests**

Run: `cd deepagent && .venv/bin/pytest tests/test_models.py tests/test_graph.py -v`

Expected: PASS, including a graph case where one detail call times out but assessment/report continue.

- [ ] **Step 7: Commit**

```bash
git add deepagent/deepagent/models.py deepagent/deepagent/catalog.py deepagent/deepagent/analysis_model.py deepagent/deepagent/graph.py deepagent/deepagent/config.py deepagent/tests/test_models.py deepagent/tests/test_graph.py
git commit -m "feat(deepagent): triage event logs before bounded detail expansion"
```

## Task 4: Surface queue/progress state safely and verify end-to-end operation

**Files:**
- Modify: `deepagent/deepagent/runner.py`
- Modify: `deepagent/deepagent/api.py`
- Modify: `deepagent/tests/test_runner.py`
- Modify: `deepagent/tests/test_api.py`
- Modify: `portal/app/(portal)/llm-dfir/investigations/[id]/page.tsx`
- Modify: `portal/components/machine-investigation-panel.tsx`
- Modify: `deepagent/README.md`
- Modify: `docs/RUNBOOK.md`

**Interfaces:**
- Produces safe callback progress payloads with `phase`, `current_step`, `total_steps`, and a non-sensitive message.
- Portal consumes existing `hermes_response` progress fields without displaying raw evidence or filter contents.

- [ ] **Step 1: Write failing progress/UI tests**

```python
@pytest.mark.asyncio
async def test_runner_reports_event_log_triage_and_detail_progress(monkeypatch):
    payloads = await run_fake_event_log_expansion(monkeypatch)
    assert [(p["phase"], p["current_step"]) for p in payloads] == [
        ("running", 0), ("collecting", 1), ("collecting", 2), ("finalizing", 8)
    ]
```

Add a portal component test or focused rendering assertion that `pending` copy says it is waiting in FIFO and active progress reads only the safe callback message.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd deepagent && .venv/bin/pytest tests/test_runner.py tests/test_api.py -k 'triage or progress or queued' -v
cd portal && pnpm test -- --runInBand
```

Expected: FAIL for the new progress expectations; if the portal has no test runner, add the smallest existing-compatible test command and document it in the task commit.

- [ ] **Step 3: Implement safe progress and portal copy**

Emit `collecting` callback progress before triage/detail phases, with counts only. Retain `running` and `finalizing`; never include raw logs, event IDs, filters, or prompts in callback messages. Keep `JobStatus.status="queued"` until the semaphore begins work. Update portal pending copy to “Đang chờ trong hàng đợi FIFO” and display safe current-step progress.

- [ ] **Step 4: Update operations documentation**

Document the shared capacity variable, the 1–3 range, a Compose rebuild/recreate command, source filtering limits, expansion caps, global evidence budget, timeout interpretation, and the procedure for inspecting safe operational logs.

- [ ] **Step 5: Run full verification**

Run:

```bash
cd deepagent && .venv/bin/ruff check deepagent tests && .venv/bin/pytest -q
cd server && .venv/bin/pytest tests/test_llm_deepagent.py -v
cd portal && pnpm lint && pnpm test -- --runInBand
docker compose -p asset-inventory -f server/deploy/docker-compose.yml config
docker compose -p asset-inventory -f server/deploy/docker-compose.yml build deepagent api
```

Expected: all available test suites/lint checks pass; Compose config/build succeeds.

- [ ] **Step 6: Manual three-job acceptance**

1. Set `DEEPAGENT_MAX_CONCURRENT_JOBS=2`.
2. Create three DeepAgent investigations in creation order.
3. Verify only two receive running callbacks; the third remains `pending` with FIFO queue copy.
4. Complete one active job and verify the third dispatches next.
5. Trigger an event-log case and verify the initial result has at most 100 metadata rows, no more than two 50-row detail requests occur, and prompt evidence stays within the configured aggregate budget.

- [ ] **Step 7: Commit**

```bash
git add deepagent/deepagent/runner.py deepagent/deepagent/api.py deepagent/tests/test_runner.py deepagent/tests/test_api.py portal/app/(portal)/llm-dfir/investigations/[id]/page.tsx portal/components/machine-investigation-panel.tsx deepagent/README.md docs/RUNBOOK.md
git commit -m "feat(dfir): expose bounded queue and triage progress"
```
