# DeepAgent FIFO Queue and Bounded Event-Log Triage Design

## Goal

Keep multiple DFIR investigations responsive by dispatching a durable FIFO queue with a system-wide concurrency limit, and reduce event-log latency/model overload through bounded, source-filtered log triage plus safe automatic detail expansion.

## Decisions

- PostgreSQL is the durable FIFO queue. `dfir_investigations.status = "pending"` means queued and not yet dispatched to DeepAgent.
- The global DeepAgent capacity is `DEEPAGENT_MAX_CONCURRENT_JOBS`, an integer from 1 through 3, default 2. Backend dispatch and the DeepAgent semaphore use the same Compose environment value.
- The initial event-log response contains at most 100 metadata rows. It excludes `Message` and `EventData`.
- A structured LLM decision may request at most two bounded follow-up queries. Each follow-up has at most 50 detail rows.
- Follow-up time windows must be fully contained in the investigation time range and have a maximum duration of 60 minutes. Requested Event IDs must occur in the initial metadata sample.
- The model never emits VQL, file paths, arbitrary channels/providers, arbitrary fields, or unbounded tool parameters.
- DeepAgent enforces `max_evidence_chars` as an aggregate prompt budget rather than only truncating each independent tool response.

## Current-State Findings

The existing backend repeatedly scans active investigations and can dispatch more DeepAgent jobs than its intended capacity. DeepAgent has an in-process semaphore, but its queue disappears when the process restarts; backend recovery later redispatches a missing job.

The pinned MCP bridge calls `realtime_collection()` for `Windows.EventLogs.EvtxHunter` and obtains all flow results. DeepAgent then retains only a 30,000-character preview after the bridge has already transferred large responses. Observed event-log responses were 12 MB and 53 MB and took 45 seconds and 161 seconds respectively; one logon query exceeded the 180-second caller deadline.

## Queue Architecture

### State and ordering

`pending` remains the durable queue state, ordered by `created_at ASC`. The backend atomically claims only the available number of pending DeepAgent investigations using `FOR UPDATE SKIP LOCKED`; it reserves a slot by setting the claimed row to `analyzing`, binding the deterministic `external_job_id`, and recording dispatch metadata before making the external HTTP call.

Active DeepAgent slots are rows whose external orchestrator is `deepagent` and whose status is `analyzing`. Terminal rows (`completed`, `failed`) free a slot. A lost DeepAgent job remains recoverable: the existing 404 check returns the row to `pending`, clears its external job ID, and the next claim re-enters FIFO order using its original `created_at`.

Backend startup/ticks first reconcile active DeepAgent jobs, then claim up to `capacity - active_count` queued rows. This preserves existing per-row callbacks and does not require Redis/Celery. The DeepAgent semaphore remains a defense-in-depth bound for direct/retry requests.

### Configuration and UI

`DEEPAGENT_MAX_CONCURRENT_JOBS` is passed to both Compose services and validated as 1–3 in each settings model. The default remains 2. The existing portal `pending` presentation is changed to communicate “queued FIFO”; it transitions to the existing active presentation only after the DeepAgent running callback.

The capacity is an environment/deployment setting, not a portal setting in this slice. Changing it requires a Compose recreate, which prevents backend/DeepAgent capacity divergence.

## Bounded Event-Log Triage

### MCP bridge patch

The Docker image continues to pin the upstream `mcp-velociraptor` commit but applies a repository-tracked patch at build time. The patch adds read-only, specialized helpers for event-log triage and detail retrieval. They invoke only `Windows.EventLogs.EvtxHunter` with code-owned fields and parameters.

The result query is capped at the source-facing bridge boundary with `LIMIT max_rows`; the bridge never serializes more rows than the configured bound. The flow is constrained before collection by the request time range and fixed high-signal channel/provider/Event-ID profiles. The initial query therefore reduces result transfer and model input; source filtering is what reduces endpoint collection work. The design does not claim that a final-result limit alone avoids all EVTX scanning by the Velociraptor artifact.

The bridge does not expose these helpers as generic model-callable VQL or `collect_artifact` functionality. DeepAgent calls them through typed client methods.

### Initial sample

A logical `windows_event_logs` plan step becomes a triage request with:

- the case time range;
- code-owned high-signal profiles for Security, System, Sysmon, and PowerShell event sources;
- fixed metadata fields: `EventTime`, `Computer`, `Channel`, `Provider`, and `EventID`;
- `max_rows=100`.

The collected envelope retains row counts, profile ID, and truncation metadata but no raw payload beyond the global evidence budget.

### Safe automatic detail expansion

After base collection, DeepAgent performs a structured expansion decision. The model can return zero, one, or two `EventLogExpansion` items, each with `date_after`, `date_before`, `event_ids`, and a bounded rationale. Code validates:

1. at most two items;
2. timestamps inside the immutable request range;
3. positive windows no longer than 60 minutes;
4. each requested Event ID exists in the initial sample;
5. the request maps to a code-owned detail profile and fixed detail fields;
6. each retrieval returns at most 50 rows.

Invalid decisions are discarded and recorded as safe limitations; they never become arbitrary bridge arguments. Detail results include the approved fields necessary for analysis, including event message/data only when within the page and aggregate evidence budgets.

The base plan is capped at six ordinary tool calls so an initial event-log triage plus two optional detail calls preserve the existing maximum of eight physical collection calls.

## Evidence and Timeout Controls

DeepAgent serializes evidence under one deterministic `max_evidence_chars` budget. Each evidence item receives a share and includes `original_chars`, `original_rows`, `returned_rows`, and `truncated` metadata when clipped. The assessment prompt cannot exceed the aggregate configured evidence budget.

Event-log triage and detail calls have explicit profile deadlines beneath or equal to the global MCP deadline. A timeout is captured as a single failed evidence item/limitation; the graph continues to assess the successful evidence and submits a completed report. Metrics/logs record profile ID, page kind, row counts, bytes, duration, expansion decision, and timeout without raw evidence or secrets.

## Error Handling and Recovery

- Queue claim/dispatch errors preserve or safely return the row to `pending`; no investigation is silently dropped.
- A DeepAgent 404 during polling triggers existing restart recovery and re-enters the durable queue.
- Invalid model expansion, bridge failed envelopes, and page timeouts produce bounded limitations, not job failure.
- Callback idempotency and job-ID binding remain unchanged.

## Testing and Acceptance

Automated tests must prove:

- two slots dispatch the first two FIFO rows and the third remains pending; capacity can be 1–3; concurrent workers cannot overclaim;
- restart recovery returns a missing job to the queue and subsequently dispatches it;
- the bridge rejects non-allowlisted fields/profiles and caps rows at configured limits;
- expansion validation rejects out-of-range times, windows over 60 minutes, unknown Event IDs, and more than two requests;
- valid expansion issues no more than two detail retrievals of 50 rows each;
- aggregate evidence serialization never exceeds `max_evidence_chars`;
- a detail timeout still yields a successful final callback using the remaining evidence.

Manual deployment acceptance is a Compose rebuild/recreate followed by three queued investigations: at most two are running, the third remains queued, and each completion dispatches the next FIFO case.
