# Chat Assistant truy vấn Inventory + Velociraptor — Design

- **Branch:** `research/velociraptor-chat-query`
- **Ngày:** 2026-10-02
- **Trạng thái:** design v4 (tiếp thu review GPT-6.1 Sol pass 3 V3-1…V3-7), chờ review
- **Liên quan:** `docs/llm-dfir/*`, DeepAgent (`deepagent/`), `server/app/services/velociraptor.py`,
  `server/app/core/audit.py`, `server/app/core/security.py`, `server/app/api/routes/machines.py`

> v4 tiếp thu pass 3 `openai-codex/gpt-6.1-sol:high` (V3-1…V3-7) trên nền v3. Phạm vi vẫn gồm 3
> sửa cross-cutting đã được chủ sản phẩm duyệt (R3 audit/hash + machine deletion, R7 private-host
> validation, R8 budget dùng chung chat + investigation).

## Problem

Hiện muốn dùng AI truy vấn DFIR/Velociraptor phải **tạo investigation mới** (theo lô). Cần một
**chat panel** hỏi–đáp tự do, nhiều lượt: (1) thông tin inventory (thống kê, tìm kiếm, phần mềm,
cấu hình, alert, EOL) và (2) Velociraptor để đánh giá sâu; khi mở tại một máy thì lấy máy đó làm
ngữ cảnh.

## Goals

1. `ChatRail` docked cố định bên phải portal; ngữ cảnh máy là mặc định mềm.
2. Agent tự chọn tool, bounded, hai miền: inventory (backend-mediated, RBAC + audit) và Velociraptor
   read-only (VQL server-side + collection read-only).
3. **Chỉ truy vấn, không thay đổi trạng thái/thông tin**.
4. **Mọi truy vấn được audit bền vững** (hash-chain), actor từ capability backend xác thực.
5. SSE streaming có schema; turn lifecycle đầy đủ; chỉ SuperAdmin.

## Non-goals

- Không side-effect lên endpoint (kill/quarantine/YARA/upload/`collect_file`).
- Không thay logic DeepAgent hay luồng điều tra theo lô; chỉ thêm hook validate private-host và reservation budget chung (R7/R8).
- Không mở cho vai trò khác ngoài SuperAdmin.
- Không thay `MachineInvestigationPanel` / `InvestigationPromptModal`.
- Không hợp nhất BFF proxy buffering; chỉ thêm route streaming riêng.

## Quyết định đã chốt

| # | Quyết định |
|---|---|
| 1 | Agent là container riêng (`chatagent/`); DeepAgent giữ logic, chỉ thêm hook validate private-host (R7); không nhúng vào backend. |
| 2 | Velociraptor: read-only VQL (validator fail-closed) + read-only collection. |
| 3 | Inventory: tool có cấu trúc + SQL ad-hoc, **backend thực thi** trên pool least-privilege; agent không giữ DB creds. |
| 4 | Backend sở hữu hội thoại + turn + audit. |
| 5 | SSE streaming, schema versioned. |
| 6 | Ngữ cảnh máy là mặc định mềm. |
| 7 | Chỉ SuperAdmin; endpoint nội bộ bằng service token + capability turn-scoped. |
| 8 | F6: serialize `append_audit` toàn cục (advisory lock) + payload hash-bound có cấu trúc, **có version hash**. |
| 9 | F7: **1 turn active/hội thoại**; gửi thứ 2 → `409` + `active_turn_id`. |
| 10 | F12: `machine_id` lưu ở hội thoại khi tạo từ trang máy; **override per-turn**, không tự đổi ngữ cảnh đã lưu. |
| 11 | F5: container chỉ nhận `CHATAGENT_*`; **không** full root `.env`. |
| 12 | Tách **2 plan tuần tự**: (P1) nền tảng security/integration, (P2) portal delivery. |
| 13 | R3 (cross-cutting): `machine_id` **không** hash-bound; dùng `machine_ref` bất biến trong `details`; hash có version, verify legacy v1. |
| 14 | R7 (cross-cutting): thay private-host check substring bằng parse host + kiểm tra IP; có retention/purge. |
| 15 | R8 (cross-cutting): budget token **reserve/reconcile chung** chat + investigation, crash-safe. |
| 16 | R4: streaming **non-resumable** trong P1 (recovery qua history + durable completion callback). |
| 17 | V3-2: intent bind theo `(turn_id, tool_call_id)` + identity đầy đủ; không dùng `tool_call_id` unique toàn cục. |
| 18 | V3-3: completion dùng **completion token** riêng, idempotent cả khi turn đã terminal. |
| 19 | V3-5/V3-7: target identity resolve **live** từ Velociraptor; budget dùng **durable reservation** (DB), không chỉ Redis. |

## Kiến trúc & ranh giới tin cậy

```
Portal (Next.js)
  • ChatRail docked phải (layout-level)
  • route proxy SSE riêng (pipe res.body, abort propagation)
        │ session cookie (SuperAdmin)
        ▼
Backend (FastAPI) — chủ sở hữu state + audit
  • /api/chat/*                        — auth, hội thoại, turn, SSE
  • /api/internal/chat/inventory/*     — tool có cấu trúc + SQL (pool chat_ro)
  • /api/internal/chat/audit/*         — audit intent/outcome + reconcile
  • /api/internal/chat/turns/*/complete — durable completion (chống mất output)
  • bảng chat_conversations/chat_turns/chat_messages/chat_tool_calls/chat_audit_intents
  • giữ llm_config + api_client.yaml (mã hoá)
        │ service token + chat_context capability   │ pool app + pool chat_ro
        ▼                                             ▼
ChatAgent container (mới)                        PostgreSQL
  • ReAct loop (bounded)                          ├─ app pool (backend)
  • inventory tool → callback backend (audited)   └─ chat_ro (view data-minimize)
  • velociraptor tool → MCP read-only (validator fail-closed)
        │ mcp stdio
        ▼
Velociraptor Server
```

**Ranh giới tin cậy**

- Portal → backend: cookie phiên, `require_super_admin` (chấp nhận `admin_global` legacy).
- Backend → agent: service token; agent **không publish port**.
- Agent → backend: service token **+ `chat_context` capability**; agent không tự khai `actor_id`.
- Agent → Velociraptor: MCP stdio, `api_client.yaml` per-request, validator VQL fail-closed.
- Backend là nơi **duy nhất** ghi `audit_log` và chạm DB inventory.

**Cô lập môi trường (F5/R3-review).** `chatagent` chỉ nhận biến `CHATAGENT_*` liệt kê tường minh;
**không** `env_file: .env` (DeepAgent hiện nhận cả `.env` chứa `DATABASE_URL`, `SECRET_KEY`,
`DATA_ENCRYPTION_KEY` — `.env.example`). Không truyền DB creds, encryption key, JWT/context signing
key, callback key. `inventory-net` là **reachability**, không phải service identity.

## Turn lifecycle (F7/R4)

```
pending ──▶ streaming ──▶ completed
   │           │
   │           ├──▶ failed(error_category)
   │           └──▶ canceled
   ├──▶ failed(chat_dispatch_stuck)   # pending quá hạn
   └──▶ canceled                      # hủy khi chưa dispatch
```

- **1 turn active/hội thoại** (partial unique index). Gửi thứ 2 → `409` + `active_turn_id`.
- **Idempotency:** `Idempotency-Key`; trùng key + cùng nội dung → trả lại turn cũ; trùng key + **khác**
  nội dung → `409 chat_conflict_idempotency`.
- **Current-input composition:** `messages` gửi agent = **history đã commit + message user hiện tại
  ở cuối**; snapshot lấy tại thời điểm turn `pending→streaming`.
- **Pending recovery:** turn `pending` > `turn_pending_timeout_seconds` (mặc định 60s) → `failed(chat_dispatch_stuck)`.
- **Liveness:** backend lease theo turn (Redis); agent phải ack/stream trong `turn_lease_seconds`, quá
  hạn và không có liveness → `failed(chat_stream_lost)`.
- **Durable completion:** khi agent kết thúc (kể cả khi SSE tới portal đứt), agent gọi
  `POST /api/internal/chat/turns/{turn_id}/complete` (service token + `X-Chat-Completion`) với nội dung
  cuối + usage + finish_reason; backend persist `assistant` message **idempotent theo turn_id**. Đây là
  nguồn chân lý để không mất output.
- **Streaming non-resumable (P1):** `id:`/`seq` có nhưng **không có replay endpoint**; client khi
  mất kết nối reload hội thoại để đọc message đã persist. Ghi rõ đây là lựa chọn có chủ đích.
- **Cancel:** `POST .../cancel` (chỉ `created_by`) → backend gọi agent `POST /v1/chat/{turn_id}/cancel`;
  agent `asyncio.CancelledError`, trả ack. Turn đã terminal → `409`. Flow Velociraptor đã tạo **không
  huỷ**; reconcile outcome `canceled`/`unknown`.
- **Cancel transport/liveness (agent):** `POST /v1/chat/{turn_id}/cancel`, `GET /v1/chat/{turn_id}/status`.
- **Audit turn:** `chat.turn.start|cancel|fail|complete`.

## Hợp đồng dữ liệu

6 bảng mới (1 migration) + sửa `audit_log`. Thứ tự tạo: conversations → turns → messages → tool_calls → audit_intents → token_reservations.

```sql
CREATE TABLE chat_conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title           VARCHAR(200),
  machine_id      UUID REFERENCES machines(id) ON DELETE SET NULL,
  created_by      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message_count   INTEGER NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  archived        BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_chat_conv_owner ON chat_conversations (created_by, last_message_at DESC);

CREATE TABLE chat_turns (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  actor_id        UUID NOT NULL,                       -- snapshot, không FK (sống sót theo audit)
  machine_id      UUID,                                -- snapshot per-turn (mutable lookup, không hash)
  machine_ref     VARCHAR(128),                        -- định danh bất biến (vd client_id/hostname) để audit
  status          VARCHAR(16) NOT NULL DEFAULT 'pending',
  finish_reason   VARCHAR(16),                         -- stop|length|canceled|error
  completion_token_hash VARCHAR(64),                   -- V3-3: thẩm quyền finalization riêng
  idempotency_key VARCHAR(128),
  request_id      UUID NOT NULL,
  started_at      TIMESTAMPTZ,
  ended_at        TIMESTAMPTZ,
  error_category  VARCHAR(48),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_chat_turn_idem UNIQUE (conversation_id, idempotency_key),
  CONSTRAINT uq_chat_turn_conv_id UNIQUE (conversation_id, id)   -- cho composite FK bên dưới
);
CREATE UNIQUE INDEX uq_chat_turn_active
  ON chat_turns (conversation_id) WHERE status IN ('pending','streaming');
CREATE INDEX ix_chat_turn_status ON chat_turns (status, created_at);

CREATE TABLE chat_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  turn_id         UUID,
  role            VARCHAR(16) NOT NULL,               -- user | assistant | system
  content         TEXT NOT NULL,
  machine_id      UUID,                               -- snapshot ngữ cảnh lượt (không hash)
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  error_category  VARCHAR(48),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- FK tổ hợp: message phải thuộc cùng conversation với turn của nó
  -- V3-1: ON DELETE CASCADE (không SET NULL vì sẽ vi phạm NOT NULL/ck_chat_msg_turn)
  CONSTRAINT fk_chat_msg_turn FOREIGN KEY (conversation_id, turn_id)
    REFERENCES chat_turns (conversation_id, id) ON DELETE CASCADE,
  CONSTRAINT ck_chat_msg_turn CHECK (role = 'system' OR turn_id IS NOT NULL)
);
CREATE INDEX ix_chat_msg_conv ON chat_messages (conversation_id, created_at, id);

CREATE TABLE chat_tool_calls (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id          UUID NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
  tool_call_id     VARCHAR(64) NOT NULL,
  tool             VARCHAR(64) NOT NULL,
  args_digest      VARCHAR(64),
  ok               BOOLEAN,
  row_count        INTEGER,
  byte_count       INTEGER,
  duration_ms      INTEGER,
  client_id        VARCHAR(64),
  flow_id          VARCHAR(64),
  audit_intent_id  INTEGER,       -- khớp audit_log.id (integer), FK bên dưới
  audit_outcome_id INTEGER,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_chat_tool_call UNIQUE (turn_id, tool_call_id)
);
CREATE INDEX ix_chat_tool_calls_turn ON chat_tool_calls (turn_id);

-- Bền vững, KHÔNG cascade theo hội thoại (sống sót khi xoá hội thoại/user)
CREATE TABLE chat_audit_intents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id         UUID NOT NULL,                -- plain UUID, không FK (sống sót khi xoá hội thoại)
  tool_call_id    VARCHAR(64) NOT NULL,
  conversation_id UUID NOT NULL,                -- plain UUID, không FK
  actor_id        UUID NOT NULL,
  tool            VARCHAR(64) NOT NULL,
  args_digest     VARCHAR(64),
  client_id       VARCHAR(64),
  flow_id         VARCHAR(64),
  attempts        SMALLINT NOT NULL DEFAULT 0,  -- V3-2: đếm lần thực thi
  outcome         VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending|ok|error|canceled|unknown
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at     TIMESTAMPTZ,
  -- V3-2: danh tính intent theo turn + tool call (KHÔNG unique toàn cục)
  CONSTRAINT uq_chat_audit_intent UNIQUE (turn_id, tool_call_id)
);
CREATE INDEX ix_chat_audit_intents_open ON chat_audit_intents (outcome, created_at);

-- Sửa audit_log (append-only, có version hash)
ALTER TABLE audit_log
  ADD COLUMN details      JSONB,
  ADD COLUMN hash_version SMALLINT NOT NULL DEFAULT 1;   -- backfill = 1 cho hàng cũ
-- Hàng mới: hash_version=2. content_hash v2 = H(action, target, actor, ts,
-- request_id, machine_ref_from_details, details_canonical). KHÔNG hash `machine_id`.
ALTER TABLE chat_tool_calls
  ADD CONSTRAINT fk_toolcall_intent  FOREIGN KEY (audit_intent_id)  REFERENCES audit_log(id) ON DELETE SET NULL,
  ADD CONSTRAINT fk_toolcall_outcome FOREIGN KEY (audit_outcome_id) REFERENCES audit_log(id) ON DELETE SET NULL;

-- V3-7: reservation budget bền vững (nguồn sự thật, Redis chỉ cache)
CREATE TABLE token_reservations (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope        VARCHAR(24) NOT NULL,            -- chat | investigation
  scope_key    VARCHAR(128) NOT NULL,           -- turn_id | investigation_id
  budget_date  DATE NOT NULL,
  reserved     INTEGER NOT NULL,
  actual       INTEGER,
  state        VARCHAR(16) NOT NULL DEFAULT 'reserved',  -- reserved|settled|unknown
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at  TIMESTAMPTZ,
  CONSTRAINT uq_token_reservation UNIQUE (scope, scope_key)
);
CREATE INDEX ix_token_reservations_day ON token_reservations (budget_date, state);
```

- **R1:** refs audit dùng `INTEGER` khớp `audit_log.id`; `chat_messages` có composite FK đảm bảo
  message thuộc đúng conversation; user/assistant **bắt buộc** `turn_id`.
- **R3:** `machine_id` là lookup mutable, **không** nằm trong hash; `machine_ref` bất biến lưu trong
  `chat_turns`/`details` và **được** hash. Route xoá máy (`machines.py:818-822`) được phép `SET
  machine_id=NULL` mà không phá chuỗi. `verify_chain` dispatch theo `hash_version` (v1 legacy giữ
  nguyên; **không** viết lại hash lịch sử).
- **R2:** `chat_audit_intents` không cascade → reconcile sống sót khi hội thoại/user bị xoá.

**Sở hữu (F12).** Route theo `{id}` chỉ `created_by`; SuperAdmin khác nhận **404**. Danh sách chỉ
trả hội thoại của mình.

**Ngữ cảnh máy (F12).**
- `/machines/[id]` đặt **pending per-turn context** (chip); không tự tạo hội thoại.
- Gửi đầu khi chưa có hội thoại → tạo hội thoại với `machine_id` đó.
- Đã có hội thoại → chip là **override per-turn**, không đổi `machine_id` đã lưu; nút "Ghim" gọi `PATCH`.
- Snapshot vào `chat_turns.machine_id` + `machine_ref` lúc gửi.
- Gỡ chip/reload/chuyển hội thoại → reset về `machine_id` đã lưu.
- **R6/N1:** `chat_conversations.machine_id` FK `machines`; **unlink `velociraptor_links` không**
  xoá `machine_id` (khác với xoá máy). Ngữ cảnh inventory vẫn còn nhưng truy cập Velociraptor có thể
  mất → resolver báo rõ. Hostname trùng phải trả **ambiguity** (danh sách client_id) chứ không tự chọn.

## Hợp đồng API

### Public — `/api/chat` (session auth, `require_super_admin`, ownership như trên)

| Method | Path | Body/Query | Trả |
|---|---|---|---|
| POST | `/api/chat/conversations` | `{title?, machine_id?}` | `ConversationOut` |
| GET | `/api/chat/conversations` | `?limit&offset&archived` | `{items[], total}` |
| GET | `/api/chat/conversations/{id}` | — | `ConversationDetailOut` |
| PATCH | `/api/chat/conversations/{id}` | `{title?, machine_id? (null=gỡ)}` | `ConversationOut` |
| DELETE | `/api/chat/conversations/{id}` | — | 204 |
| POST | `/api/chat/conversations/{id}/messages` | `{content, machine_context?}`, header `Idempotency-Key` | `text/event-stream` |
| POST | `/api/chat/conversations/{id}/cancel` | `{turn_id}` | `{status}` / `409` |

`ConversationOut` (`chat.api/1`): `{id, title, machine_id|null, message_count, last_message_at|null,
archived, created_at, updated_at}`. `ConversationDetailOut` thêm `messages: MessageOut[]` +
`active_turn_id|null`. `MessageOut`: `{id, role, content, turn_id|null, machine_id|null,
error_category|null, created_at}`.

### Nội bộ — `/api/internal/chat` (service token; chỉ agent)

| Method | Path | Auth | Mô tả |
|---|---|---|---|
| POST | `/inventory/query` | capability (turn active) | Tool có cấu trúc (backend chạy + audit) |
| POST | `/inventory/sql` | capability (turn active) | SQL ad-hoc read-only (pool `chat_ro` + audit) |
| POST | `/audit/intent` | capability (turn active) | Ghi audit intent trước khi chạy tool Velociraptor |
| POST | `/audit/outcome` | service token + **intent** (KHÔNG cần capability) | Ghi audit outcome sau khi có kết quả/lỗi |
| POST | `/audit/reconcile` | service token + intent | Đóng intent mồ côi → `unknown` (actor lấy từ intent) |
| POST | `/turns/{turn_id}/complete` | service token + completion token (V3-3) | Durable completion, idempotent kể cả khi turn terminal |

- **R2:** query execution **bắt buộc capability còn hiệu lực**; nhưng outcome/reconcile là **uỷ quyền
  hẹp riêng** dùng service token + bản ghi `chat_audit_intents` (không mở lại quyền chạy truy vấn).
  Actor reconcile **lấy từ intent**, không từ capability đã hết hạn.
- Intent idempotent theo **`(turn_id, tool_call_id)`**: trùng + cùng identity đầy đủ (`actor_id`, `tool`,
  `args_digest`, `client_id`) → trả bản ghi cũ; khác bất kỳ trường identity → `409`.  
  Outcome gửi kèm `attempt` tăng dần; bản ghi terminal đầu thắng; attempt cũ hơn/khác giá trị → `409`.
- Intent chưa có outcome quá `audit_outcome_deadline` (mặc định 600s) → reconciler ghi `unknown`.
- Hoàn toàn không suy diễn `ok` khi không chắc.

### Capability `chat_context` (F3/R2)

- JWT compact, **HS256**, ký bằng `CHAT_CONTEXT_SECRET` (backend-only). Agent chỉ mang token.
- Claims: `iss="backend"`, `aud="chat-internal"`, `sub=actor_id`, `cid`, `tid`, `rid`, `iat`,
  `exp` (≤ 300s).
- Verify: chữ ký + `aud` + `exp` (skew ≤ 30s) + DB: turn `tid` tồn tại, `status ∈ {pending,streaming}`,
  `conversation.created_by == sub`.
- Revoke theo turn: turn terminal → mọi call cần capability bị từ chối (outcome/reconcile không cần).
- Nhiều tool call trong 1 turn dùng chung capability là hợp lệ; mỗi call có `tool_call_id` riêng.
- **V3-3 — thẩm quyền finalization riêng:** backend phát `completion_token` ngẫu nhiên (lưu
  `completion_token_hash`) trong request dispatch; agent gọi `/turns/{id}/complete` bằng **service token
  + `X-Chat-Completion`**. Endpoint chấp nhận turn ở mọi trạng thái (kể cả đã terminal) trong
  `completion_grace_seconds=120`: lần complete đầu thắng; trùng `content_digest` → idempotent; khác →
  `409` + audit `chat.turn.late_output`, **không** persist/không mở lại execution. Completion **không**
  phụ thuộc `exp` của capability.

### Agent API

- `POST /v1/chat` (service token) — SSE, body:

```jsonc
{
  "schema_version": "chat.agent.request/1.0",
  "conversation_id": "uuid", "turn_id": "uuid", "request_id": "uuid",
  "machine_context": { "machine_id": "uuid", "client_id": "C...", "hostname": "WS-01" },
  "messages": [ { "role": "user|assistant", "content": "…" } ],   // history + message user hiện tại ở cuối
  "chat_context": "<jwt>",
  "llm_runtime": { "base_url": "…", "api_key": "…", "model": "…", "temperature": 0.2,
                   "timeout_seconds": 120, "max_tokens": 4096, "allow_cloud": false,
                   "system_prompt": "…" },
  "velociraptor_api_client_yaml": "…",
  "limits": { "max_tool_calls": 12, "max_evidence_chars": 120000, "wall_clock_seconds": 300 }
}
```

- `GET /v1/chat/{turn_id}/status` (service token) → `{status, alive_at}`.
- `POST /v1/chat/{turn_id}/cancel` (service token) → ack.
- `GET /healthz`.

### SSE event schema (F8) — `chat.sse/1`

| `type` | Fields |
|---|---|
| `start` | `v, seq, turn_id, message_id` |
| `tool_start` | `v, seq, tool_call_id, tool, params_digest, summary` |
| `tool_result` | `v, seq, tool_call_id, ok, row_count, byte_count, duration_ms, client_id?, flow_id?, error_category?` |
| `token` | `v, seq, text` |
| `usage` | `v, seq, input_tokens, output_tokens` |
| `done` | `v, seq, message_id, finish_reason` |
| `error` | `v, seq, category, hint, retryable, http_status?` |

- `seq` đơn điệu; heartbeat `:hb` 15s; non-resumable (không replay).
- Lỗi trước stream → HTTP JSON; lỗi trong stream → event `error` rồi đóng.
- **Error taxonomy:** `chat_validation | chat_authz | chat_not_found | chat_conflict_active_turn |
  chat_conflict_idempotency | chat_rate_limited | chat_budget_exceeded | chat_budget_unavailable |
  chat_guardrail_sql | chat_guardrail_vql | chat_collection_denied | chat_timeout_llm |
  chat_timeout_tool | chat_upstream_llm | chat_upstream_velo | chat_mcp_bridge | chat_canceled |
  chat_stream_lost | chat_dispatch_stuck | chat_internal`.

## Catalog tool & mapping (F8/F9)

Đặt tên trùng bridge nơi có thể; alias có mapping tường minh + **kiểm tra schema lúc khởi động**
(fail-closed nếu thiếu/khác). Structured tool inventory **dùng cùng pool `chat_ro`** và chỉ view đã duyệt.

**Inventory:** `inventory_search`, `inventory_machine_detail`, `inventory_resolve_machine`,
`inventory_stats`, `inventory_software`, `inventory_hardware`, `inventory_alerts`, `inventory_sql`
(schema typed + output field thuộc manifest view).

**Velociraptor server-side:** `list_clients`, `get_client_metadata`, `list_flows`, `get_flow_results`,
`run_vql` (validator). **Collection read-only:** đúng tên bridge (`windows_pslist`,
`windows_netstat_enriched`, `windows_event_logs` qua triage/detail typed, `windows_execution_prefetch`, ...).

## Policy VQL fail-closed (F1)

`run_vql` chỉ VQL phía **server**; endpoint quét qua collection. Validator fail-closed (từ chối nếu
không parse/chứng minh an toàn):

1. Một statement; chỉ `SELECT`/`WITH`; cấm `;`.
2. Allowlist plugin **server-side** (`clients`, `flows`, `hunts`, `labels`, `artifacts`, `notebooks`,
   `info`, `scope`, ...). Artifact client-side (`pslist`, ...) **không** hợp lệ trong `run_vql`.
3. **Allowlist function** cho projection/predicate/argument/subquery/nested (không chỉ plugin ở FROM).
   Cấm mọi hàm side-effect kể cả trong `SELECT`: `collect_client`/`collect_artifact`/`artifact_set`/
   `file_write`/`upload`/`execve`/`shell`/`rm`/`kill_process`/`quarantine`/`yara`.
4. Cấm `LET`, gán động, gọi gián tiếp, cấu trúc ngoài grammar.
5. Trần: timeout, row cap, byte cap.

**Test bắt buộc:** side-effect-trong-SELECT, nested, alias, comment/obfuscation, dynamic dispatch →
đều bị từ chối. Nếu validator không đủ tin cậy → **fallback**: chỉ template truy vấn cố định tham số
typed (không free VQL), và **từ chối raw VQL ở mọi seam**. Lựa chọn cuối ghi ở P1.

## Guardrail SQL inventory (F4/R5)

- **Pool riêng `chat_ro`** (role `inventory_chat_ro`), `GRANT SELECT` **chỉ** trên view đã duyệt.
  Không quyền trên bảng gốc. Schema `chat_ro_views` làm `search_path`.
- **Manifest view/cột (đóng):**
  - `v_chat_machines(id, hostname, org_name, os_name, os_version, status, last_seen, eol_flag)`
  - `v_chat_machine_detail(id, hostname, org_name, os_name, os_version, cpu, ram_mb, disk_gb, status, last_seen)`
  - `v_chat_org_stats(org_name, machine_count, online_count, eol_count)`
  - `v_chat_software(machine_id, hostname, software_name, version, install_date)`
  - `v_chat_hardware(machine_id, hostname, component, value)`
  - `v_chat_alerts(id, machine_id, hostname, severity, category, created_at, status)`
  - **Không** PII (không `users.*`, phone/CCCD/email); masking thực hiện **trong view**, không theo tên cột.
- **P1 plan task (V3-4):** xác định projection an toàn từ `MachineCurrent`/`MachineSoftware` (CPU/disk là
  JSONB, RAM là `ram_gb`); EOL hiện ở `portal/lib/eol.ts` (không có field backend) → cần derivation +
  xử lý `unknown`; alert: chốt nguồn (`AlertEvent` thiếu `status`; `DfirAlert` dùng `resolved`); kèm
  parity test trước khi viết migration view.
- **Ranh giới thực thi (V3-4):** PostgreSQL cho `PUBLIC` quyền đọc `pg_catalog`, nên **catalog/function
  isolation là validator-enforced (tuyến chính)**, không thể chỉ dựa `REVOKE ... FROM inventory_chat_ro`.
  DB-enforced tối thiểu: role `inventory_chat_ro` `NOINHERIT`, không là member role khác, không sở hữu
  object, chỉ `USAGE` schema `chat_ro_views` + `SELECT` view; không grant bảng gốc, `users`, `llm_config`,
  `velociraptor_config`, `api_keys`, `audit_log`, `chat_*`. Deployment **có thể** siết thêm `PUBLIC` nếu
  tương thích; ghi rõ phần nào DB-enforced vs validator-enforced và test bằng role thật.
- **Validator-enforced:** một statement `SELECT`/CTE; cấm `INSERT/UPDATE/DELETE/DDL/COPY/CALL/SET`;
  không tham chiếu `pg_catalog`/`information_schema`/`pg_*`; function registry đóng
  (`count,min,max,sum,avg,coalesce,date_trunc,lower,upper,length,now`); resolve tên an toàn.
- **Trần:** `statement_timeout=5000ms`, row cap 5000, byte cap 2MB; vượt → từ chối/`truncated`.
- SQL audit = `sha256(normalized_sql)`, không raw.
- Test bằng **role thật** `inventory_chat_ro` (không dùng app pool): alias che PII, `JOIN pg_catalog`,
  function side-effect, multi-statement, nested CTE, timeout, structured-tool field leakage.

## Collection safety (F9/R6)

- **Artifact manifest đóng**, có `supported_platforms` và provenance (chỉ định nghĩa built-in đã review;
  custom artifact **bị loại trừ** trừ khi execution policy được xác minh độc lập — validator
  `velociraptor_artifacts.py:78-105` không chứng minh read-only).
- Agent **không** truyền parameters/fields; code sinh argument (pattern `mcp_client.py:339-358`).
- **Trần số (enforce):** `chat_collection_max_time_range_hours=24`, `chat_collection_flow_deadline_seconds=240`,
  `chat_collection_max_rows=5000`, `chat_collection_max_outstanding_per_client=1`, `chat_collection_per_machine_per_hour=6`.
  Helper không enforce được bound → fail closed.
- **Canonical target identity (V3-5):** resolve **live** từ Velociraptor (`search_clients`/`get_all_clients`)
  tại thời điểm bắt đầu turn — `velociraptor_links` chỉ là gợi ý vì sync đã bỏ duplicate và giữ newest
  (`velociraptor_sync.py:189-209`). Nhiều match hostname → trả **ambiguity list**; 0 match → fail closed
  (`chat_collection_denied`). Giới hạn per-machine ghi theo **`client_id`** (client-stable), không theo
  cặp `(client_id, machine_id)`; nếu không xác lập được identity → fail closed.
- Caller timeout **không** phải flow-level guarantee (`mcp_client.py:38-43`); collection dùng polling
  flow-status với deadline riêng; quá hạn → outcome `unknown`, flow giữ nguyên (không huỷ).

## Audit (F2/F6/R2/R3)

**F6/R3 — hash-chain toàn cục + version.**
- Serialize `get_last_hash` + insert bằng `pg_advisory_xact_lock(<const>)` trong `append_audit`
  (`core/audit.py:48-75`) — mọi writer hưởng lợi.
- Thêm `details JSONB` + `hash_version`. v1 = `H(action,target,actor,ts)` (giữ legacy);
  v2 = `H(action,target,actor,ts,request_id,machine_ref,details_canonical)`. **`machine_id` mutable
  không hash**. `verify_chain` dispatch theo version; **không** viết lại hash cũ.
- Route xoá máy giữ `UPDATE machine_id=NULL` (không phá hash). `machine_ref` (client_id/hostname)
  lưu bất biến trong `details`.
- Test thật PostgreSQL: mixed v1/v2 verify, append đồng thời nhiều transaction, tamper, xoá máy.

**F2/R2 — audit bền vững Velociraptor.**
1. `POST /audit/intent` (capability) → tạo `chat_audit_intents` + hàng `audit_log`
   `chat.query.velociraptor phase=intent`, trả `audit_id`.
2. Chạy tool.
3. `POST /audit/outcome` (service token + intent) → hàng `phase=outcome` + cập nhật intent
   (`ok|error|canceled`), `audit_outcome_id`.
4. `POST /audit/reconcile` (service token + intent) → intent mồ côi quá deadline → `unknown`.
Intent fail → **không chạy tool**. Outcome/reconcile chạy được cả khi turn terminal/capability hết hạn.
`append_audit` chỉ `flush`; route phải **commit**.

**Action audit:** `chat.conversation.create|update|delete`, `chat.turn.start|complete|cancel|fail`,
`chat.query.inventory`, `chat.query.inventory.sql` (digest), `chat.query.velociraptor` (intent/outcome),
`chat.tool.denied`. Actor **luôn** từ capability đã verify hoặc từ intent (reconcile).

## Prompt-injection & privacy (F10/R7)

- Bọc output tool trong `<untrusted_tool_output tool="…">`; catalog/allowlist do code quyết định.
- Không credential vào input/log model. Mặc định **log metadata-only**; prompt/response log (nếu bật)
  vào bảng riêng, admin-gated.
- Redaction trước prompt: regex secret `(?i)(api[-_]?key|token|secret|password)\s*[:=]\s*\S+`, CCCD/SĐT;
  không echo `api_client.yaml`.
- **R7 — private-host validation thay thế:** parse URL bằng `urllib.parse`; resolve host bằng
  `socket.getaddrinfo`; chỉ chấp nhận IP loopback/private/link-local/CGNAT qua `ipaddress`
  (IPv4+IPv6); **pin IP đã resolve** khi kết nối; cấm redirect sang public. Bỏ hẳn substring check
  trong `llm_dfir.py:114-119`. Khi `allow_cloud=false` + endpoint public → từ chối `chat_upstream_llm`.
- **V3-6 — áp ở MỌI executor:** backend `services/llm.py`, **ChatAgent** (validate `llm_runtime.base_url`
  ngay trước khi gọi LLM), và **DeepAgent** (`analysis_model.py` thêm hook cùng validator). Điều này
  thu hẹp cam kết 'DeepAgent nguyên vẹn' đúng mức tối thiểu cho an toàn egress.
- **Retention:** `chat_retention_days=180` cho hội thoại; prompt log (nếu bật) `chat_prompt_log_retention_days=30`;
  job purge hằng ngày; xoá theo yêu cầu user; output canceled/failed chịu cùng policy.
- Test injection âm: output chứa "ignore instructions" không đổi tool policy.

## Admission control & budget chung (F11/R8)

| Key | Default | Phạm vi |
|---|---|---|
| `chat_rate_per_user_per_min` | 10 | per user |
| `chat_max_active_conversations_per_user` | 3 | per user |
| `chat_max_concurrent_sse_total` | 12 | toàn hệ thống |
| `chat_max_messages_per_conversation` | 100 | per conversation |
| `chat_max_message_chars` | 8000 | per message |
| `chat_max_history_messages` | 40 | per turn |
| `chat_max_history_chars` | 60000 | per turn |
| `chat_max_tool_calls_per_turn` | 12 | per turn |
| `chat_wall_clock_seconds` | 300 | per turn |
| `chat_evidence_chars` | 120000 | per turn |
| `chat_daily_token_budget` | từ `llm_config.daily_token_budget` | dùng chung chat + investigation |

- **R8 / V3-7 — reservation bền vững (DB là source of truth, Redis chỉ cache):**
  - Trước khi chạy: **check-and-reserve atomic** bằng `INSERT ... ON CONFLICT` (unique `(scope, scope_key)`)
    + kiểm tra tổng `reserved` so với `llm_config.daily_token_budget`; envelope bảo thủ theo model/calls
    (`chat_reserve_tokens`, mặc định 32k; investigation envelope riêng).
  - Khi xong/lỗi/hủy: settle = actual usage; **unknown consumption → charge đủ envelope** (bảo thủ),
    `state=unknown`. Idempotent theo `(scope, scope_key)`.
  - Rollover theo `budget_date` (UTC). DB không khả dụng → **fail closed** cho execution MỚI
    (`chat_budget_unavailable`), **không** huỷ kết quả đã hoàn thành.
  - Áp cho **mọi** đường investigation (`dfir_investigation.py:1087,1168,1320-1344,1371-1374`), kể cả nhánh
    external fail; DeepAgent callback hiện không báo usage → tính theo envelope. Thêm usage vào callback
    là enhancement sau (không mở lại DeepAgent trong P1).
- Trần input/history enforce trước khi gọi LLM (`chat_max_message_chars`, history caps).
- Vượt trần → `429`/`error` + `retryable` + `Retry-After`; đếm cả model retry và collection ẩn.

## UI (Portal)

- `ChatRail` docked ~400px trong `(portal)/layout.tsx`, sibling cột nội dung; nội dung co lại;
  mở/đóng `localStorage`; màn nhỏ → drawer.
- `/machines/[id]`: pending per-turn context; chip `Đang hỏi về: <hostname>` + gỡ/ghim.
- `ChatMessage` (markdown, tái dùng `investigation-markdown`), `ChatToolTrace`, `useChatStream`
  (fetch + `ReadableStream`, abort propagation), nút Dừng.
- Danh sách/lịch sử/xoá hội thoại; ownership như trên.
- Route proxy SSE riêng: `Content-Type: text/event-stream`, `Cache-Control: no-store`,
  `X-Accel-Buffering: no`, refresh token trước khi pipe, propagate abort, **không** tự chạy lại sau khi stream bắt đầu.

## Kiểm thử

- **Agent:** validator VQL (side-effect/nested/alias), mapping tool + schema check, injection, lỗi an toàn,
  cancel/liveness, complete callback.
- **Backend:** ownership/404, turn state machine (active 409, idempotency, pending recovery, cancel,
  reconcile), audit intent/outcome/reconcile + hash-chain **concurrency + mixed-version test**, guardrail
  SQL bằng role thật, private-host validation, budget dùng chung (chat + investigation), rate limit, SSE schema.
- **Portal:** `ChatRail` docked, context chip lifecycle, `useChatStream` parse/abort, proxy headers.
- **E2E:** compose smoke (tạo → hỏi → trả lời + audit + tool trace + cancel; backend restart giữa chừng → history recovery).

## Triển khai

- Container `chatagent/` (Dockerfile clone `mcp-velociraptor` **pin SHA DeepAgent**
  `9b3c4b3a590029390e88049896a473d7f909c0ce`; xác minh tool surface + bù adapter safeguard nếu cần). Không publish port.
- Compose `chatagent`: chỉ biến `CHATAGENT_*` (không `env_file: .env`). Cập nhật `.env.example` + `scripts/gen-env-example.py`.
- Migration 6 bảng + role/pool `chat_ro` + view + `ALTER audit_log` + FK refs (R1) + `token_reservations` (V3-7).
- Sửa cross-cutting: `core/audit.py` (advisory lock + version hash + details), `routes/machines.py`
  (giữ mutation không-hash), `services/llm.py` + `routes/llm_dfir.py` (private-host), `services/dfir_investigation.py`
  (budget chung), `main.py` (routers).
- Portal: `lib/backend.ts` + route proxy SSE mới, `(portal)/layout.tsx` (ChatRail).

## Kế hoạch triển khai (2 plan, 1 spec)

1. **P1 — Security/integration foundation:** verify bridge, typed tools + mapping, validator VQL,
   pool/view SQL + manifest projection, env isolation, capability + completion token (V3-3), audit
   intent/outcome/reconcile + hash version + advisory lock, turn lifecycle, authoritative candidate
   resolution (V3-5), private-host validator ở mọi executor, durable reservation budget (V3-7),
   admission control, schema API/SSE/error.
2. **P2 — Portal delivery:** proxy SSE, ChatRail, context lifecycle, conversation/cancel UX, full-stack test.

## Residual risks

- Nguồn `mcp-velociraptor` clone lúc build, không có trong repo: schema, `ENABLE_DANGEROUS_TOOLS`,
  patch, huỷ flow, validate VQL, giới hạn tài nguyên — xác minh ở P1.
- Audit race/mixed-version suy ra từ đọc source; reproduce bằng test ở P1.
- Collection read-only vẫn tạo flow và tốn tài nguyên endpoint — chấp nhận, không hứa "zero state".
- Streaming non-resumable: mất kết nối giữa stream chỉ phục hồi được phần đã persist qua completion callback.
- DB-level catalog isolation không tuyệt đối (PUBLIC) — validator là tuyến chính.

## Future work

- Mở cho vai trò khác theo org; hợp nhất luồng điều tra; approval cho hành động nặng; resumable streaming.
