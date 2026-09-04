# DeepAgent Paginated Query Skills Design

## Goal

Adopt the upstream `mcp-velociraptor` pagination release and give DeepAgent code-enforced, runtime query skills. Every automatic read-only collection begins with a bounded sample; the model may ask only for a small number of validated expansions when the sample warrants it. The result must reduce endpoint, MCP, and model-context load without granting the model arbitrary VQL, artifact parameters, fields, paths, regexes, or pagination values.

## Current-State Findings

The MCP bridge now has commit `b92561b` (`feat: add limit and pagination support to MCP collection tools and VQL queries`). The helpers whose public schemas expose `limit` and `offset` return a JSON envelope:

```json
{
  "ok": true,
  "data": [],
  "pagination": {
    "limit": 100,
    "offset": 0,
    "returned_rows": 100,
    "has_more": true,
    "next_offset": 100
  }
}
```

`VELOCIRAPTOR_DEFAULT_LIMIT` defaults to 100 and `VELOCIRAPTOR_MAX_LIMIT` defaults to 1000. The bridge probes `limit + 1` rows, returns only `limit` rows, and provides `has_more` / `next_offset`. It applies this to selected collection helpers and fleet-result helpers, not every bridge tool. For example, `windows_pslist`, `windows_netstat_enriched`, `windows_services`, `windows_scheduled_tasks`, Prefetch, ShimCache, MFT, USN, and generic EVTX expose `limit`/`offset`; current `windows_autoruns`, `windows_wmi_persistence`, Amcache, UserAssist, Logon Sessions, PowerShell ScriptBlock, Event Log Cleared, and DNS Cache do not expose those caller arguments. The latter still inherit the bridge's default row cap when they call its internal collection helper, but DeepAgent cannot request 50 rows or a later page until their MCP schemas are extended. Pagination is stateless: a later page may re-run the bounded collection with its offset; there is no bridge-side evidence cache.

The release includes the previously pinned bounded event-log triage/detail helpers. DeepAgent still pins an earlier MCP commit and applies a local patch containing those helpers. Updating only the SHA would make that patch duplicate/conflict with upstream; adoption must replace the pin-and-patch build with the new upstream commit and prove the actual loaded tool schemas work.

The MCP README identifies two collection classes:

- memory-backed process and network artifacts are typically 3–7 seconds;
- disk/EVTX timeline artifacts such as Event Logs, MFT, and USN commonly take 30–45 seconds and must use ISO-8601 `DateAfter`/`DateBefore` bounds where their typed helper supports them.

It also recommends triage-first collection and inspecting pagination metadata before requesting another page. Current DeepAgent generic collection drops the caller-selected pagination arguments and clips by character count only after receiving MCP data. Existing event-log typed handling is bounded, but its metadata is separate from the generic `pagination` format.

## Decisions

- DeepAgent automatic collection remains read-only and limited to an explicit tool catalog. It will never automatically expose or invoke `run_vql`, generic artifact collection, hunting, YARA, response/quarantine, file collection, or parameter-discovery tools.
- Runtime skills are declarative code-owned policies, rendered as concise instructions to the planning/expansion model. Markdown-only prompt rules are insufficient because they cannot enforce allowed calls.
- A skill defines its allowed initial collection and expansion actions. The model chooses an action identifier and evidence references only; code produces the MCP arguments from the selected policy.
- Where a tool schema exposes `limit`, initial pages are deliberately smaller than MCP's default: 50 rows for supported snapshot/memory/persistence collections and 100 metadata rows for timeline/log triage. No automatic collection requests the bridge maximum of 1000 rows. A tool without an exposed limit remains a one-pass default-capped sample and cannot receive automatic expansion until the MCP schema supports it.
- A standard skill permits at most two total expansions, at most 50 returned rows per expansion, and at most 150 returned rows across its initial and follow-up calls. Event-log detail keeps its existing stricter rules: maximum two details, each at most 50 rows, Event IDs must come from triage, and the window is at most 60 minutes within the immutable case range.
- Offset expansion may use only the exact `next_offset` returned by the immediately preceding successful call. The model cannot provide an arbitrary offset or limit.
- A time-window expansion may use only a code-selected child window: a deterministic split of the current/request window, or a window explicitly validated against the case range and the skill maximum. It cannot change channel, provider, artifact, field set, or filter values.
- Detail expansion may use only a named, code-owned detail profile. For event logs, selected Event IDs must remain a subset of identifiers observed in the initial triage evidence.
- The existing aggregate `max_evidence_chars` guard remains authoritative. Pagination metadata and safe operational metrics are retained even when row data is reduced to a preview.

## Query Skill Model

A new internal `QuerySkill` model is the source of truth. It is not MCP input and is not model-authored. Each entry contains:

| Field | Purpose |
| --- | --- |
| `skill_id` | Stable identifier supplied to the model, e.g. `process_network_triage`. |
| `description` | Short analyst-facing goal and evidence interpretation guidance. |
| `tool_name` | A catalog allowlisted read-only MCP tool. |
| `collection_class` | `snapshot`, `timeline`, or `typed_event_log`. |
| `initial_page` | Code-owned fields, limit, offset zero, and required fixed arguments. |
| `time_policy` | `none`, `case_range`, or `bounded_child_window`; only tools whose schemas support dates can have a non-`none` policy. |
| `expansion_actions` | A subset of `next_page`, `narrow_time_window`, and `detail_profile`. |
| `budget` | Maximum calls, pages, rows, and elapsed time for this skill. |
| `stop_conditions` | Conditions such as no `has_more`, no relevant indicator, source timeout, or exhausted budget. |

The first slice covers only the current Windows automatic catalog. Examples:

- `process_network_triage`: `windows_pslist` and `windows_netstat_enriched`, 50-row samples, at most one validated next page per source.
- `persistence_triage`: `windows_services` and `windows_scheduled_tasks`, 50-row samples and next-page-only expansion. `windows_autoruns` and `windows_wmi_persistence` remain default-capped one-pass samples until their schemas expose pagination arguments.
- `execution_snapshot_triage`: Prefetch and ShimCache, 50-row samples and next-page-only expansion. Amcache and UserAssist remain default-capped one-pass samples until their schemas expose pagination arguments.
- `event_log_triage`: preserves the specialized `windows_event_logs_triage` and detail flow; uses 100 metadata rows, never generic pagination.
- `powershell_timeline_triage` and `event_log_cleared_timeline`: case-bounded, default-capped initial queries; they may use a bounded child-time-window action only after their typed tool schema and source-side filtering are confirmed.

`windows_logon_events` is deliberately excluded from automatic expansion in the first slice. It currently exposes neither caller pagination nor a safe supported time-range parameter. It stays a default-capped one-pass sample until the MCP repository adds typed bounds or a dedicated bounded triage helper.

## Model Interaction

### Planning

The planner continues to create an investigation plan from the existing catalog. The catalog prompt is augmented with the applicable skill descriptions and their investigation purpose, but not raw argument templates. Sanitization maps each planned tool to its skill's initial action; a tool with no applicable skill is removed from automatic collection.

The agent prompt must state:

1. inspect initial samples and returned pagination metadata before considering expansion;
2. use `has_more` as proof that another page exists, not as proof that it is relevant;
3. prefer evidence correlation (process ↔ network ↔ persistence) over paging through repetitive rows;
4. for timelines, prefer a constrained time window and typed triage before any detail request;
5. stop when an expansion cannot materially confirm/refute a hypothesis.

### Structured expansion decision

After initial collection and after each accepted expansion round, one structured model invocation may return zero through two actions. The schema has only:

```text
ExpansionDecision {
  actions: [
    { skill_id, action: "next_page" | "narrow_time_window" | "detail_profile",
      evidence_refs, rationale }
  ]
}
```

`evidence_refs` must name successful evidence IDs from the current investigation. They let validation associate a decision with actual returned metadata; raw model text never becomes an MCP argument. The model cannot return `limit`, `offset`, timestamps, fields, Event IDs, artifact names, or generic parameter dictionaries.

Validation rejects an action unless all of the following are true:

- `skill_id` and action are in the static registry;
- the referenced initial/current evidence belongs to that skill and succeeded;
- all skill/global budgets remain available;
- `next_page` has `pagination.has_more == true` and uses only its recorded `next_offset`;
- a time action is valid for the tool and produces a non-empty window within the original case range and skill cap;
- a detail profile is static and any derived selectors are present in sampled evidence;
- the action is not a duplicate page, duplicate window, or duplicate profile request.

Rejected actions are not retried and become static safe limitation labels such as `expansion_budget_exhausted`, `next_page_unavailable`, `time_expansion_not_supported`, or `expansion_reference_invalid`. No raw LLM content or evidence is emitted in these labels.

## MCP Adoption and Compatibility

1. Pin the DeepAgent Docker build to upstream `b92561b` (or a later explicitly approved MCP revision).
2. Remove the build-time bounded-event-log patch only after confirming that the upstream revision contains the exact typed tools and source-facing limits required by current DeepAgent tests.
3. Ensure MCP initialization/tool discovery completes before LangGraph execution, so the typed helpers and new generic schemas are visible.
4. Normalize both response variants into one internal `CollectionResult` shape:
   - `ok`, `data`, and safe error information;
   - `pagination` (`limit`, `offset`, `returned_rows`, `has_more`, `next_offset`) for generic tools;
   - typed source metadata (`original_rows`, `returned_rows`, `truncated`, selectors) for event-log helpers.
5. Verify source code semantics for `limit` and `offset`: pagination must be applied in VQL/collection result retrieval before JSON serialization, not merely clipped in DeepAgent after transfer. The integration must not assume `offset` gives an immutable endpoint snapshot.
6. Set bridge environment defaults defensively (`VELOCIRAPTOR_DEFAULT_LIMIT=100`, `VELOCIRAPTOR_MAX_LIMIT=1000` or a lower deployment-approved cap). DeepAgent still passes its own lower initial limit.

## Observability and Evidence

For every MCP call, structured logs record only safe metadata:

- tool and skill IDs, collection class, page role (`initial` or `expansion`);
- requested limit, actual returned rows, offset, `has_more`, and whether an expansion was accepted/rejected;
- original rows/truncation for typed helpers when supplied;
- duration, timeout classification, and serialized evidence character count.

They must not log raw rows, evidence previews, arbitrary model rationale, credentials, VQL, or endpoint secrets. Assessment evidence retains pagination/truncation metadata so the final report can state when conclusions are based on partial samples.

## Error Handling

- A malformed or failed MCP pagination envelope becomes a bounded failed `EvidenceItem`; the graph continues with independent evidence.
- An MCP timeout stops only the affected skill; no next-page retry occurs automatically.
- An empty page, no `has_more`, or a repeated `next_offset` stops paging and records a safe limitation if relevant.
- Upstream MCP tool/schema drift fails startup/health validation with a safe operator-facing message rather than silently falling back to unbounded collection.
- Existing queue, FIFO capacity, callback idempotency, and restart recovery semantics are unchanged.

## Testing and Acceptance

Automated tests must establish that:

1. the Docker/build integration pins the approved MCP revision and applies no stale duplicate patch;
2. generic calls pass only skill-owned `limit=50`, `offset=0`, and allowed case time bounds when the discovered schema supports each argument; unsupported tools receive no invented parameters and are not pageable;
3. pagination metadata survives decoding, character clipping, evidence budgeting, and report synthesis;
4. an initial `has_more=true` result can yield only the exact next offset; arbitrary/repeated offsets and over-budget actions are rejected;
5. a tool with no supported time range cannot receive a model-selected time range;
6. each skill permits at most its configured expansion count/row/call budget;
7. the existing event-log triage/detail source limits and Event ID/window validation still pass unchanged;
8. bridge failed envelopes/timeouts do not cause another automatic page request;
9. logs contain safe row/page/duration metadata and no raw evidence;
10. existing DeepAgent and server/portal test suites remain green, and the rebuilt DeepAgent image reports the expected tool inventory.

Manual acceptance uses a host with known high-volume process/network or timeline data. The initial investigation must show a 50-row (snapshot) or 100-row (timeline metadata) page with pagination metadata. At most two code-validated expansion calls may follow, and the final assessment evidence must remain at or below `DEEPAGENT_MAX_EVIDENCE_CHARS`.
