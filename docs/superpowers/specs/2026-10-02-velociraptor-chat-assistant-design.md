# Chat Assistant truy vấn Inventory + Velociraptor — Design

- **Branch:** `research/velociraptor-chat-query`
- **Ngày:** 2026-10-02
- **Trạng thái:** design v2 (đã tiếp thu review GPT-6.1 Sol F1–F12), chờ review
- **Liên quan:** `docs/llm-dfir/*`, DeepAgent (`deepagent/`), `server/app/services/velociraptor.py`,
  `server/app/core/audit.py`, `server/app/core/security.py`

> v2 tiếp thu review độc lập `openai-codex/gpt-6.1-sol:high` (verdict REVISE). Các mục
> **F1–F12** dưới đây là hợp đồng bắt buộc, không phải chi tiết để lại cho implementation.

## Problem

Hiện muốn dùng AI để truy vấn dữ liệu DFIR/Velociraptor, người dùng phải **tạo một
investigation mới** (theo máy, chạy theo lô, chờ báo cáo). Không có cách hỏi–đáp tự do,
nhiều lượt, để (1) truy vấn thông tin inventory (thống kê, tìm kiếm máy, phần mềm, cấu
hình, alert, EOL...) và (2) truy vấn thêm Velociraptor để đánh giá sâu. Người dùng cần
một **chat panel** thường trú, hỏi bất kỳ, agent tự chọn tool và chạy nhiều bước; khi mở
tại một máy thì mặc định lấy máy đó làm ngữ cảnh.

## Goals

1. `ChatRail` docked cố định bên phải portal, dùng ở mọi trang; ngữ cảnh máy là mặc định mềm.
2. Agent tự chọn tool, bounded, hai miền: inventory (backend-mediated, có RBAC + audit) và
   Velociraptor read-only (VQL server-side + collection read-only).
3. **Chỉ truy vấn, không thay đổi trạng thái/thông tin**: không kill/quarantine/YARA/collect_file,
   không DDL/DML, không sửa/xoá dữ liệu.
4. **Mọi truy vấn được audit bền vững** bằng hash-chain, actor từ ngữ cảnh backend đã xác thực.
5. SSE streaming có schema; turn lifecycle rõ ràng; chỉ SuperAdmin.

## Non-goals

- Không hành động side-effect lên endpoint (kill/quarantine/YARA/upload/`collect_file`).
- Không thay DeepAgent hay luồng điều tra theo lô.
- Không mở cho vai trò khác ngoài SuperAdmin (giai đoạn này).
- Không thay `MachineInvestigationPanel` / `InvestigationPromptModal`.
- Không hợp nhất BFF proxy buffering hiện có; chỉ thêm route streaming riêng.

## Quyết định đã chốt

| # | Quyết định |
|---|---|
| 1 | Agent là container riêng (`chatagent/`); DeepAgent nguyên vẹn; không nhúng vào backend. |
| 2 | Velociraptor: read-only VQL (validator fail-closed) + read-only collection; không tool thay đổi trạng thái. |
| 3 | Inventory: tool có cấu trúc + SQL ad-hoc, **backend thực thi** trên pool least-privilege riêng; agent không giữ credential DB. |
| 4 | Backend sở hữu hội thoại + turn + audit. |
| 5 | SSE streaming, schema versioned. |
| 6 | Ngữ cảnh máy là mặc định mềm (soft default). |
| 7 | Chỉ SuperAdmin; endpoint nội bộ bằng service token + capability turn-scoped. |
| 8 | F6: sửa `append_audit` **toàn cục** (advisory lock) + payload hash-bound có cấu trúc. |
| 9 | F7: **1 turn active/hội thoại**; gửi thứ 2 → `409` kèm `active_turn_id`. |
| 10 | F12: `machine_id` lưu ở hội thoại khi tạo từ trang máy; **override per-turn**, không tự đổi ngữ cảnh đã lưu. |
| 11 | F5: container chỉ nhận `CHATAGENT_*` + credential tối thiểu; **không** nhận full root `.env`. |
| 12 | Tách **2 plan tuần tự** dưới 1 spec: (P1) nền tảng security/integration, (P2) portal delivery. |

## Kiến trúc & ranh giới tin cậy

```
Portal (Next.js)
  • ChatRail docked phải (layout-level)
  • route proxy SSE riêng (pipe res.body, abort propagation)
        │ session cookie (SuperAdmin)
        ▼
Backend (FastAPI) — chủ sở hữu state + audit
  • /api/chat/*                      — auth, hội thoại, turn, SSE
  • /api/internal/chat/inventory/*   — tool có cấu trúc + SQL (pool read-only riêng)
  • /api/internal/chat/audit/*       — audit intent/outcome bền vững (agent gọi)
  • bảng chat_conversations/chat_messages/chat_turns/chat_tool_calls
  • giữ llm_config + api_client.yaml (mã hoá)
        │ service token + chat_context capability   │ DB pool chat_ro (least-privilege)
        ▼                                             ▼
ChatAgent container (mới)                        PostgreSQL
  • ReAct loop (bounded)                          ├─ app pool (backend, quyền đầy đủ theo code)
  • inventory tool → callback backend (audited)   └─ chat_ro pool (view đã data-minimize)
  • velociraptor tool → MCP read-only (validator fail-closed)
        │ mcp stdio
        ▼
Velociraptor Server
```

**Ranh giới tin cậy**

- Portal → backend: cookie phiên, `require_super_admin` (chấp nhận cả `admin_global` legacy — ghi rõ).
- Backend → agent: service token, mạng Docker nội bộ, agent **không publish port**.
- Agent → backend: service token **+ `chat_context` capability** turn-scoped; agent không thể
  tự khai `actor_id` (F3).
- Agent → Velociraptor: MCP stdio, `api_client.yaml` per-request, validator VQL fail-closed.
- Backend là nơi **duy nhất** ghi `audit_log` và chạm DB inventory.

**Cô lập môi trường (F5).** Container `chatagent` chỉ nhận các biến `CHATAGENT_*` được liệt kê
tường minh trong compose. **Không** dùng `env_file: .env` (DeepAgent hiện nhận cả `.env`, gồm
`DATABASE_URL`, `SECRET_KEY`, `DATA_ENCRYPTION_KEY` — `.env.example:10,24,37,49`; đây là lỗi
cần tránh). Không truyền DB creds, encryption key, JWT/context signing key, hay callback key
của backend. Ghi rõ: chung `inventory-net` là **reachability**, không phải service identity.

## Turn lifecycle (F7)

Mỗi lượt gửi là một **turn** có định danh bền vững; backend sở hữu state machine:

```
(pending) ──▶ streaming ──▶ completed
                  │
                  ├──▶ failed(error_category)
                  └──▶ canceled
```

- **1 turn active/hội thoại.** Gửi khi đang có turn `pending|streaming` → `409` + `active_turn_id`.
- **Idempotency:** `POST .../messages` nhận `Idempotency-Key`; nếu trùng key của turn đã có →
  trả lại turn đó (không tạo turn mới).
- **History snapshot:** agent nhận history đã commit *tại thời điểm turn bắt đầu*, theo
  `created_at, id` tăng dần; message của turn đang chạy không nằm trong snapshot.
- **Persistence khi kết thúc:** turn terminal lưu `assistant` message (đầy đủ hoặc partial
  tới token cuối), `usage`, `error_category`; token usage cập nhật một lần, atomic.
- **Restart/đứt stream reconciliation:** backend quét turn `streaming` quá `turn_stale_seconds`;
  nếu agent không xác nhận còn sống → đánh `failed(chat_stream_lost)` và ghi audit, không tự
  chạy lại tool.
- **Cancel:** `POST .../cancel` gửi tín hiệu hủy tới agent; agent `asyncio.CancelledError` dừng
  vòng lặp. Với collection đã tạo flow: **không huỷ flow** (đã nêu ở Non-goals) — ghi rõ flow
  vẫn tồn tại và được audit; trả `409` nếu turn đã terminal. Chỉ `created_by` được cancel.
- **Audit turn:** `chat.turn.start`, `chat.turn.cancel`, `chat.turn.fail` (F2/F9 của review).

## Hợp đồng dữ liệu

4 bảng mới (1 migration). FK/index tường minh.

```sql
-- Ngữ cảnh hội thoại (soft default + snapshot per-turn)
CREATE TABLE chat_conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title           VARCHAR(200),
  machine_id      UUID REFERENCES machines(id) ON DELETE SET NULL,   -- ngữ cảnh lưu, nullable
  created_by      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message_count   INTEGER NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  archived        BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_chat_conv_owner ON chat_conversations (created_by, last_message_at DESC);

CREATE TABLE chat_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  turn_id         UUID,                         -- NULL cho message user? (turn tạo trước message)
  role            VARCHAR(16) NOT NULL,         -- user | assistant | system
  content         TEXT NOT NULL,
  machine_id      UUID,                         -- snapshot ngữ cảnh của lượt
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  error_category  VARCHAR(48),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_chat_msg_conv ON chat_messages (conversation_id, created_at, id);

CREATE TABLE chat_turns (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  actor_id        UUID NOT NULL,
  machine_id      UUID,                         -- snapshot per-turn
  status          VARCHAR(16) NOT NULL DEFAULT 'pending',
  idempotency_key VARCHAR(128),
  request_id      UUID NOT NULL,
  started_at      TIMESTAMPTZ,
  ended_at        TIMESTAMPTZ,
  error_category  VARCHAR(48),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_chat_turn_idem UNIQUE (conversation_id, idempotency_key)
);
-- Bất biến "1 turn active/hội thoại" ở tầng DB:
CREATE UNIQUE INDEX uq_chat_turn_active
  ON chat_turns (conversation_id) WHERE status IN ('pending','streaming');

CREATE TABLE chat_tool_calls (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id         UUID NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
  tool_call_id    VARCHAR(64) NOT NULL,
  tool            VARCHAR(64) NOT NULL,
  args_digest     VARCHAR(64),                  -- sha256(args canonical), không lưu raw PII
  ok              BOOLEAN,
  row_count       INTEGER,
  byte_count      INTEGER,
  duration_ms     INTEGER,
  client_id       VARCHAR(64),
  flow_id         VARCHAR(64),
  audit_intent_id UUID,                         -- trỏ tới audit_log (intent)
  audit_outcome_id UUID,                        -- trỏ tới audit_log (outcome)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_chat_tool_call UNIQUE (turn_id, tool_call_id)
);
CREATE INDEX ix_chat_tool_calls_turn ON chat_tool_calls (turn_id);
```

**Sở hữu (F12).** Mọi route theo `{id}` chỉ cho `created_by` truy cập; SuperAdmin khác nhận
**404** (không phân biệt với không tồn tại, tránh enumeration). Danh sách chỉ trả hội thoại của mình.

**Ngữ cảnh máy (F12/decision 10).**
- Vào `/machines/[id]` đặt một **pending per-turn context** (chip). Không tự tạo hội thoại.
- Lần gửi đầu khi chưa có hội thoại mở → tạo hội thoại với `machine_id` = máy đó.
- Khi đã có hội thoại: chip là **override per-turn** (gửi trong body), **không** đổi `machine_id`
  đã lưu; có nút "Ghim làm ngữ cảnh" gọi `PATCH` để cập nhật `machine_id` (hành động tường minh).
- Turn snapshot `machine_id` vào `chat_turns.machine_id` + `chat_messages.machine_id` lúc gửi.
- Gỡ chip, reload, chuyển hội thoại: chip reset về `machine_id` đã lưu (nếu có).
- Máy bị xoá/unlink: FK `ON DELETE SET NULL`; resolver hostname trùng phải trả **ambiguity rõ
  ràng** (nêu danh sách) chứ không tự chọn bừa (`server/app/db/models.py:751-758`).

## Hợp đồng API

### Public — `/api/chat` (session auth, `require_super_admin`, ownership như trên)

| Method | Path | Body/Query | Trả |
|---|---|---|---|
| POST | `/api/chat/conversations` | `{title?, machine_id?}` | `ConversationOut` |
| GET | `/api/chat/conversations` | `?limit&offset&archived` | `{items[], total}` |
| GET | `/api/chat/conversations/{id}` | — | `ConversationDetailOut` (+ messages) |
| PATCH | `/api/chat/conversations/{id}` | `{title?, machine_id? (nullable → gỡ)}` | `ConversationOut` |
| DELETE | `/api/chat/conversations/{id}` | — | 204 |
| POST | `/api/chat/conversations/{id}/messages` | `{content, machine_context?, Idempotency-Key header}` | `text/event-stream` |
| POST | `/api/chat/conversations/{id}/cancel` | `{turn_id}` | `{status}` / `409` |

Response schema (ví dụ, versioned `chat.api/1`):

```jsonc
// ConversationOut
{ "id": "uuid", "title": "…", "machine_id": "uuid|null",
  "message_count": 0, "last_message_at": "iso|null", "archived": false,
  "created_at": "iso", "updated_at": "iso" }
```

### Nội bộ — `/api/internal/chat` (service token; chỉ agent)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/internal/chat/inventory/query` | Tool có cấu trúc (backend chạy + audit) |
| POST | `/api/internal/chat/inventory/sql` | SQL ad-hoc read-only (pool `chat_ro` + audit) |
| POST | `/api/internal/chat/audit/intent` | Ghi audit **trước** khi chạy tool Velociraptor |
| POST | `/api/internal/chat/audit/outcome` | Ghi audit **sau** khi có kết quả/lỗi/hủy |

Mọi call mang `Authorization: Bearer <service-token>` + `X-Chat-Context: <capability>`.
Backend verify capability, resolve `actor_id`, kiểm tra turn còn active, chạy/ghi audit rồi trả.

### Capability `chat_context` (F3)

- **Định dạng:** JWT compact, **HS256**, ký bằng `CHAT_CONTEXT_SECRET` (backend-only, không
  truyền cho agent). Agent chỉ **mang** token, không tạo được.
- **Claims bắt buộc:** `iss="backend"`, `aud="chat-internal"`, `sub=actor_id`, `cid=conversation_id`,
  `tid=turn_id`, `rid=request_id`, `iat`, `exp` (**≤ 300s**).
- **Verify:** chữ ký + `aud` + `exp` (cho phép clock skew ≤ 30s) + tra DB: turn `tid` tồn tại,
  `status ∈ {pending, streaming}`, `conversation.created_by == sub`. Bất kỳ điều kiện sai → `401/403`.
- **Revoke theo turn:** khi turn terminal, capability hết hiệu lực (kiểm tra status DB). Token bị
  replay sau khi turn xong → từ chối. Trong lúc turn active, nhiều tool call dùng cùng capability
  là hợp lệ; mỗi call có `tool_call_id` riêng để audit idempotent.
- **Body-binding:** call inventory/audit gửi kèm `turn_id` + `tool_call_id`; backend đối chiếu turn.
  (Không bind toàn bộ body vì mỗi tool call có body khác nhau; bảo vệ bằng turn-scope + service token.)

### Agent API — `POST /v1/chat` (service token, SSE)

```jsonc
{
  "schema_version": "chat.agent.request/1.0",
  "conversation_id": "uuid",
  "turn_id": "uuid",
  "request_id": "uuid",
  "machine_context": { "machine_id": "uuid", "hostname": "WS-01" },
  "messages": [ { "role": "user|assistant", "content": "…" } ],
  "chat_context": "<jwt>",
  "llm_runtime": { "base_url": "…", "api_key": "…", "model": "…",
                   "temperature": 0.2, "timeout_seconds": 120, "max_tokens": 4096,
                   "allow_cloud": false, "system_prompt": "…" },
  "velociraptor_api_client_yaml": "…",
  "limits": { "max_tool_calls": 12, "max_evidence_chars": 120000,
              "wall_clock_seconds": 300 }
}
```

### SSE event schema (F8) — `chat.sse/1`

| `type` | Fields | Ghi chú |
|---|---|---|
| `start` | `v, seq, turn_id, message_id` | Bắt đầu stream |
| `tool_start` | `v, seq, tool_call_id, tool, params_digest, summary` | `params_digest` = sha256, không lộ PII |
| `tool_result` | `v, seq, tool_call_id, ok, row_count, byte_count, duration_ms, client_id?, flow_id?, error_category?` | An toàn, không raw data |
| `token` | `v, seq, text` | Delta câu trả lời |
| `usage` | `v, seq, input_tokens, output_tokens` | |
| `done` | `v, seq, message_id, finish_reason` | `stop|length|canceled` |
| `error` | `v, seq, category, hint, retryable, http_status?` | `hint` = static, không raw |

- `seq` tăng đơn điệu; có `id:` để client resume và heartbeat comment `:hb` mỗi 15s.
- Lỗi **trước khi** mở stream trả HTTP thường (JSON `{category, hint}`); lỗi **trong** stream là
  event `error` rồi đóng.
- **Error taxonomy** (ổn định): `chat_validation | chat_authz | chat_not_found |
  chat_conflict_active_turn | chat_rate_limited | chat_budget_exceeded | chat_guardrail_sql |
  chat_guardrail_vql | chat_collection_denied | chat_timeout_llm | chat_timeout_tool |
  chat_upstream_llm | chat_upstream_velo | chat_mcp_bridge | chat_canceled | chat_stream_lost |
  chat_internal`.

## Catalog tool & mapping (F8/F9)

Đặt tên tool **trùng** bridge nơi có thể để giảm sai khác; alias phải có mapping tường minh và
kiểm tra schema lúc khởi động (fail-closed nếu tool thiếu/khác schema).

**Inventory (backend thực thi):** `inventory_search`, `inventory_machine_detail`,
`inventory_resolve_machine`, `inventory_stats`, `inventory_software`, `inventory_hardware`,
`inventory_alerts`, `inventory_sql`. Mỗi tool có schema typed (`{args} → {rows, row_count, truncated}`),
`args_digest` ghi audit.

**Velociraptor server-side:** `list_clients`, `get_client_metadata`, `list_flows`,
`get_flow_results`, `run_vql` (validator). **Collection read-only:** dùng đúng tên helper của bridge
(`windows_pslist`, `windows_netstat_enriched`, `windows_event_logs` (đi qua triage/detail typed
như DeepAgent `catalog.py:48-52`), `windows_execution_prefetch`, ...). Mapping alias→bridge nằm
trong registry + test.

## Policy VQL fail-closed (F1)

`run_vql` chỉ chạy VQL phía **server**; không dùng nó để quét endpoint (endpoint đi qua collection).

Validator **fail-closed** (từ chối nếu không parse/không chứng minh được an toàn):

1. Chỉ **một** statement; chỉ `SELECT`/`WITH`; cấm `;`.
2. Tách **execution locus**: allowlist plugin **server-side** (`clients`, `flows`, `hunts`, `labels`,
   `artifacts`, `notebooks`, `info`, `scope`, ...). Artifact client-side (`pslist`, `netstat`, ...)
   **không** hợp lệ trong `run_vql`.
3. **Allowlist function** cho projection/predicate/argument/subquery/nested — không chỉ plugin ở
   `FROM`. Cấm mọi hàm side-effect kể cả trong `SELECT`: `collect_client`/`collect_artifact`/
   `artifact_set`/`file_write`/`upload`/`execve`/`shell`/`rm`/`kill_process`/`quarantine`/`yara`.
4. Cấm `LET`, gán động, gọi gián tiếp, và mọi cấu trúc không nằm trong grammar cho phép.
5. Trần: timeout, row cap, byte cap.

**Test bắt buộc:** side-effect-trong-SELECT, nested expression, alias, comment/obfuscation, dynamic
dispatch — tất cả phải bị từ chối. Nếu không xây được validator đủ tin cậy, **fallback**: chỉ dùng
template truy vấn cố định có tham số typed (không free VQL); ghi rõ lựa chọn ở plan P1.

## Guardrail SQL inventory (F4)

- **Pool riêng least-privilege** `chat_ro` (role `inventory_chat_ro`), tạo trong migration/seed;
  `GRANT SELECT` **chỉ** trên tập view đã data-minimize (ví dụ `v_chat_machines`,
  `v_chat_machine_detail`, `v_chat_org_stats`, `v_chat_software`). Không có quyền trên bảng gốc.
- **Loại trừ:** `users` (password_hash/totp_secret/backup_codes/PII — `models.py:175-197`),
  `llm_config`, `velociraptor_config`, `api_keys`, `audit_log`, `chat_*`, và system catalog
  (`pg_catalog`, `information_schema`, `pg_*`).
- **Không mask theo tên cột** làm biện pháp chính (SQL có thể alias/biến đổi giá trị); dữ liệu
  nhạy cảm bị loại/masking **ngay trong view**.
- **Grammar:** 1 statement `SELECT`/`CTE`; cấm `INSERT/UPDATE/DELETE/DDL/COPY/CALL/SET`;
  `search_path` an toàn; function allowlist.
- **Trần:** `statement_timeout = 5000ms`, row cap 5000, byte cap 2MB; vượt → từ chối + `truncated`.
- SQL ghi vào audit dưới dạng **sha256(normalized_sql)**, không lưu raw (F10 của review).
- Test: alias che PII, `JOIN pg_catalog`, function side-effect, multi-statement, timeout.

## Collection safety (F9)

- Danh sách artifact **cố định, đã review**, có `supported_platforms`; từ chối artifact ngoài danh sách.
- **Agent không truyền parameters/fields**: mọi argument do code sinh, mô hình không cung cấp
  (theo pattern DeepAgent `mcp_client.py:339-358`). Chỉ nhận tên artifact + time range bounded từ turn.
- Từ chối custom artifact trừ khi execution policy đã được xác minh độc lập (validator VQL hạ tầng
  của `velociraptor_artifacts.py:78-105` **không** chứng minh read-only).
- Trần tài nguyên collection (thời gian/row/số flow) tách khỏi trần truncation kết quả.

## Audit (F2/F6)

**F6 — hash-chain toàn cục.** Sửa `append_audit` (`core/audit.py:48-75`) để **serialize** việc đọc
`get_last_hash` + insert bằng `pg_advisory_xact_lock(<const>)` (một chỗ, mọi writer hưởng lợi), và
bổ sung cột **`details JSONB`** (hash-bound cùng `action/target/actor/ts`) để chứa metadata có cấu
trúc (query type, digest, IDs). `request_id`/`machine_id`/`details` phải nằm trong `content_hash`;
`target` giữ ≤255. Test thật trên PostgreSQL với nhiều transaction đồng thời; không dựa vào
`tool_trace` (có thể xoá) làm bằng chứng duy nhất.

**F2 — audit bền vững cho Velociraptor.** Vì tool chạy trong agent (không thể gọi `append_audit`),
agent gọi endpoint nội bộ:

1. `POST /api/internal/chat/audit/intent` → backend ghi hàng hash-chain `chat.query.velociraptor`
   với `phase=intent`, `tool_call_id`, `tool`, `client_id`/artifact, `args_digest`; trả `audit_id`.
2. Thực thi tool (VQL/collection).
3. `POST /api/internal/chat/audit/outcome` → backend ghi hàng `phase=outcome`, `ok`, `row_count`,
   `flow_id?`, `error_category?`, `audit_intent_id`.

Nếu bước intent fail → **không chạy tool**. Nếu outcome fail/agent crash/stream đứt → reconcile dựa
trên intent (ghi outcome `unknown`), không để truy vấn "vô hình". `append_audit` chỉ `flush`; route
phải **commit**.

**Bảng action audit:** `chat.conversation.create|update|delete`, `chat.turn.start|cancel|fail`,
`chat.query.inventory`, `chat.query.inventory.sql` (digest), `chat.query.velociraptor` (intent/outcome),
`chat.tool.denied` (guardrail). Actor **luôn** từ capability đã verify.

## Prompt-injection & privacy (F10)

- Output tool bọc trong `<untrusted_tool_output tool="…">…</untrusted_tool_output>`; catalog/allowlist
  do code quyết định, **không** suy ra từ output tool.
- **Không** để credential vào input/log của model. Mặc định **log metadata-only** (phase/tool/latency/
  row_count); nếu cần lưu prompt/response thì vào bảng riêng, có retention, và admin-gated (không log chung).
- Redaction trước khi vào prompt: regex secret (`(?i)(api[-_]?key|token|secret|password)\s*[:=]\s*\S+`),
  CCCD/SĐT theo pattern; không echo `api_client.yaml`.
- Egress theo `llm_config.allow_cloud`: khi `false`, từ chối LLM endpoint public (tái dùng kiểm tra
  private-host hiện có).
- Retention/access cho `chat_messages`/`chat_turns`/`chat_tool_calls` và bất kỳ prompt log; có xoá theo yêu cầu.
- Test injection âm: tool output chứa "ignore instructions" không đổi được tool policy/allowlist.

## Admission control (F11)

Cấu hình qua `CHATAGENT_*`/settings, có default; thực thi **phân tán** (Redis sẵn có) nơi cần:

| Key | Default | Phạm vi |
|---|---|---|
| `chat_rate_per_user_per_min` | 10 | per user |
| `chat_max_active_conversations_per_user` | 3 | per user |
| `chat_max_concurrent_sse_total` | 12 | toàn hệ thống |
| `chat_max_messages_per_conversation` | 100 | per conversation |
| `chat_max_tool_calls_per_turn` | 12 | per turn |
| `chat_wall_clock_seconds` | 300 | per turn |
| `chat_collection_per_machine_per_hour` | 6 | per machine |
| `chat_evidence_chars` | 120000 | per turn |
| `chat_daily_token_budget` | theo `llm_config.daily_token_budget` | chia sẻ chat + investigation, reserve/reconcile atomic |

Vượt trần → `429`/`error` với `retryable` + `Retry-After`. Đếm cả model retry và công việc collection ẩn.

## UI (Portal)

- `ChatRail` docked cố định (~400px) trong `(portal)/layout.tsx`, sibling cột nội dung; nội dung co
  lại; trạng thái mở/đóng `localStorage`; màn nhỏ → drawer.
- Trang `/machines/[id]`: đặt pending per-turn context; chip `Đang hỏi về: <hostname>` + gỡ/ghim.
- `ChatMessage` (markdown, tái dùng `investigation-markdown`), `ChatToolTrace` (chip, link máy/flow),
  `useChatStream` (fetch + `ReadableStream`, abort propagation), nút Dừng.
- Danh sách/lịch sử/xoá hội thoại; ownership như trên.
- Route proxy SSE riêng: set `Content-Type: text/event-stream`, `Cache-Control: no-store`,
  `X-Accel-Buffering: no`, refresh token **trước** khi pipe, propagate abort, **không** tự chạy lại sau khi stream bắt đầu.

## Kiểm thử

- **Agent:** validator VQL (side-effect/nested/alias), guardrail loop, injection, lỗi an toàn, mapping tool.
- **Backend:** ownership/404, authz SuperAdmin, turn state machine (409/active, idempotency, cancel,
  reconciliation), audit intent/outcome + hash-chain **concurrency test PostgreSQL**, guardrail SQL
  (PII alias, catalog escape, function, timeout), rate limit/budget, SSE schema.
- **Portal:** `ChatRail` docked, context chip lifecycle, `useChatStream` parse/resume/abort, proxy headers.
- **E2E:** compose smoke (tạo → hỏi → trả lời + audit + tool trace + cancel).

## Triển khai

- Container `chatagent/` (Dockerfile clone `mcp-velociraptor` **pin đúng SHA DeepAgent**
  `9b3c4b3a590029390e88049896a473d7f909c0ce`; **phải xác minh** tool surface tại SHA + có kế hoạch
  bù các adapter safeguard của DeepAgent nếu patch không tự kế thừa). Không publish port.
- Compose service `chatagent`: chỉ biến `CHATAGENT_*` (không `env_file: .env`). Thêm `.env.example`
  + `scripts/gen-env-example.py`.
- Migration 4 bảng + role/pool `chat_ro`; sửa `append_audit` (F6).
- Sửa: `server/app/main.py` (routers), `portal/lib/backend.ts` + route proxy SSE mới,
  `portal/app/(portal)/layout.tsx` (thêm `ChatRail`).

## Kế hoạch triển khai (2 plan, 1 spec)

1. **P1 — Security/integration foundation:** verify bridge capability, typed tools + mapping,
   validator VQL, pool/view SQL least-privilege, cô lập env, capability `chat_context`, audit intent/
   outcome + sửa hash-chain, turn lifecycle, admission control, schema API/SSE/error, sửa `append_audit`.
2. **P2 — Portal delivery:** proxy SSE, `ChatRail`, context lifecycle, conversation UX, cancel UX, test full-stack.

## Residual risks (không chứng minh được từ repo)

- Nguồn `mcp-velociraptor` clone lúc build, **không có trong repo**: schema tool, hành vi
  `ENABLE_DANGEROUS_TOOLS`, patch, khả năng huỷ flow, validate VQL, giới hạn tài nguyên — phải
  xác minh ở P1.
- Audit race được suy ra từ đọc source, chưa tái hiện bằng test đồng thời (sẽ làm ở P1).
- Collection read-only vẫn tạo flow và tiêu tốn tài nguyên endpoint — chấp nhận và ghi rõ, không
  hứa "zero state".
- Lưu lịch sử tạo thêm nơi chứa dữ liệu nhạy cảm → cần policy retention/xoá.

## Future work

- Mở cho vai trò khác theo phạm vi org; hợp nhất luồng điều tra theo lô; approval cho hành động nặng.
