# Chat Assistant truy vấn Inventory + Velociraptor — Design

- **Branch:** `research/velociraptor-chat-query`
- **Ngày:** 2026-10-02
- **Trạng thái:** design, chờ review trước khi lập implementation plan
- **Liên quan:** `docs/llm-dfir/*`, DeepAgent (`deepagent/`), `server/app/services/velociraptor.py`

## Problem

Hiện muốn dùng AI để truy vấn dữ liệu DFIR/Velociraptor, người dùng phải **tạo một
investigation mới** (theo máy, chạy theo lô, chờ báo cáo). Không có cách hỏi–đáp
tự do, nhiều lượt, để:

1. Truy vấn **thông tin trên hệ thống inventory** (thống kê, tìm kiếm máy, phần mềm,
   cấu hình, alert, EOL...).
2. Truy vấn thêm **thông tin từ Velociraptor** để đánh giá sâu.

Người dùng cần một **chat panel** thường trú, hỏi bất kỳ, agent tự chọn tool và chạy
nhiều bước; khi mở tại một máy thì mặc định lấy máy đó làm ngữ cảnh.

## Goals

1. Chat panel **docked cố định bên phải** portal, dùng được ở mọi trang; trang chi
   tiết máy tự gắn `machine_id` làm ngữ cảnh **mềm** (vẫn hỏi được máy khác).
2. Agent tự chọn tool, chạy nhiều bước (bounded), gồm hai miền dữ liệu:
   - **Inventory** — qua backend (có RBAC + audit).
   - **Velociraptor** — read-only VQL + thu thập read-only (tạo flow, không sửa endpoint).
3. **Chỉ truy vấn, không thay đổi trạng thái/thông tin**: không `kill_process`,
   quarantine, YARA, sửa/xoá dữ liệu, DDL/DML.
4. **Mọi truy vấn được audit** bằng hash-chain `append_audit` sẵn có, actor là người dùng chat.
5. Streaming (SSE) hiện tiến trình tool + token câu trả lời.
6. Chỉ **SuperAdmin** dùng trong giai đoạn này.

## Non-goals

- Không hành động có side-effect lên endpoint (kill/quarantine/YARA/upload) và không
  thu thập file tuỳ ý (`collect_file`). Read-only collection ở đây nghĩa là đọc artifact
  có sẵn (pslist/netstat/eventlog/prefetch...), không sửa dữ liệu endpoint.
- Không thay đổi DeepAgent hay luồng điều tra theo lô.
- Không mở quyền cho vai trò khác ngoài SuperAdmin.
- Không thay thế `MachineInvestigationPanel` / `InvestigationPromptModal` (giữ nguyên).
- Không hợp nhất BFF proxy hiện có; chỉ thêm route streaming riêng.

## Quyết định đã chốt

| # | Quyết định |
|---|---|
| 1 | Agent là **container riêng** (`chatagent/`), không nhúng vào backend, không sửa DeepAgent. |
| 2 | Velociraptor: **read-only VQL + read-only collection**, không tool thay đổi trạng thái. |
| 3 | Inventory: tool có cấu trúc + SQL ad-hoc, **backend thực thi** (audit + RBAC), agent không giữ credential DB. |
| 4 | Backend sở hữu lịch sử hội thoại (`chat_conversations`, `chat_messages`). |
| 5 | Trả lời bằng **SSE streaming**. |
| 6 | Ngữ cảnh máy là **mặc định mềm** (soft default). |
| 7 | Chỉ SuperAdmin; endpoint nội bộ bằng service token. |

## Kiến trúc

```
Portal (Next.js)
  • ChatRail docked phải (layout-level, mọi trang)
  • route proxy SSE mới (pipe res.body)
        │ session cookie (SuperAdmin)
        ▼
Backend (FastAPI) — chủ sở hữu
  • /api/chat/*                      — auth, hội thoại, SSE
  • chat_conversations / chat_messages
  • giữ llm_config + api_client.yaml (mã hoá)
  • audit mọi truy vấn (append_audit hash-chain)
  • /api/internal/chat/inventory/*   — read-only SQL + tool có cấu trúc
        │ service token + chat_context      │ DB role read-only
        ▼                                     ▼
ChatAgent container (mới)              PostgreSQL
  • ReAct loop (LangGraph)
  • inventory tool → callback backend (audited)
  • velociraptor tool → MCP read-only (VQL + collection)
        │ mcp stdio
        ▼
Velociraptor Server
```

**Ranh giới tin cậy**

- Portal → backend: cookie phiên, `require_super_admin`.
- Backend → agent: service token, mạng Docker nội bộ, agent **không publish port**.
- Agent → backend (inventory): service token + `chat_context` đã ký, backend kiểm tra rồi
  mới chạy + audit.
- Agent → Velociraptor: `mcp-velociraptor` (stdio), `api_client.yaml` truyền per-request.
- Backend là nơi **duy nhất** chạm DB inventory.

## Luồng một lượt hỏi

1. Người dùng gửi tin trong `ChatRail`.
2. Backend lưu `user` message; nạp history + `LlmConfig` + `VelociraptorConfig`.
3. Backend gọi `POST /v1/chat` (SSE) sang ChatAgent, kèm `chat_context` (đã ký),
   `llm_runtime`, `velociraptor_api_client_yaml`, `machine_context` (nếu có).
4. Agent chạy tool loop:
   - inventory → `POST /api/internal/chat/inventory/*` (backend chạy read-only + audit);
   - Velociraptor → MCP read-only (VQL server-side hoặc collection read-only).
5. Agent stream event; backend **relay về portal** và **ghi audit** cho từng truy vấn.
6. Kết thúc: backend lưu `assistant` message + `tool_trace`.

## Hợp đồng

### DB (2 bảng mới, 1 migration Alembic)

```sql
CREATE TABLE chat_conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title           VARCHAR(200),
  machine_id      UUID REFERENCES machines(id),        -- ngữ cảnh mềm, nullable
  created_by      UUID NOT NULL REFERENCES users(id),
  message_count   INTEGER NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  archived        BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE chat_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  role            VARCHAR(16) NOT NULL,               -- user | assistant | system
  content         TEXT NOT NULL,
  tool_trace      JSONB,                              -- [{tool, params, ok, rows, duration_ms, flow_id, machine_id}]
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  error           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Route công khai — `/api/chat` (session auth, `require_super_admin`)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/chat/conversations` | Tạo hội thoại (optional `machine_id`) |
| GET | `/api/chat/conversations` | List của tôi (phân trang) |
| GET | `/api/chat/conversations/{id}` | Chi tiết + messages |
| DELETE | `/api/chat/conversations/{id}` | Xoá hội thoại |
| POST | `/api/chat/conversations/{id}/messages` | Gửi tin → **SSE stream** |
| POST | `/api/chat/conversations/{id}/cancel` | Dừng sinh |

### Route nội bộ — `/api/internal/chat` (service token; chỉ agent gọi)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/internal/chat/inventory/query` | Dispatch tool inventory có cấu trúc |
| POST | `/api/internal/chat/inventory/sql` | SQL ad-hoc read-only có guardrail |

Cả hai yêu cầu header `Authorization: Bearer <service-token>` và `X-Chat-Context`
(HMAC, chứa `conversation_id`, `actor_id`, `request_id`, hết hạn ngắn). Backend verify,
chạy read-only, rồi `append_audit` trong cùng luồng trước khi trả kết quả.

### Agent API — `POST /v1/chat` (service token, SSE)

```jsonc
{
  "schema_version": "chat.assistant.request/1.0",
  "conversation_id": "…",
  "machine_context": { "machine_id": "…", "hostname": "WS-01" }, // nullable
  "messages": [ { "role": "user|assistant", "content": "…" } ],
  "chat_context": "<HMAC token>",
  "llm_runtime": { "base_url": "…", "api_key": "…", "model": "…",
                   "temperature": 0.2, "timeout_seconds": 120, "max_tokens": 4096,
                   "system_prompt": "…" },
  "velociraptor_api_client_yaml": "…",
  "limits": { "max_tool_calls": 12 }
}
```

SSE event types: `start`, `tool_start`, `tool_result`, `token`, `done`, `error`.

### Catalog tool

**Inventory (qua backend, audit):**
`inventory_search`, `inventory_machine_detail`, `inventory_resolve_machine`
(hostname/IP → machine_id + client_id), `inventory_stats` (group_by: org/OS/status/EOL),
`inventory_software`, `inventory_hardware`, `inventory_alerts`, `inventory_sql`.

**Velociraptor (read-only, MCP):**
`velo_list_clients`, `velo_search_clients`, `velo_client_metadata`, `velo_list_flows`,
`velo_flow_results`, `velo_vql` (VQL server-side, plugin allowlist),
`velo_collect_read` (thu thập read-only artifact: pslist/netstat/eventlog/prefetch...;
không nhận đường dẫn file tuỳ ý).

### Policy VQL an toàn

- Chỉ chấp nhận `SELECT ... FROM <plugin>` với `plugin` ∈ **allowlist đọc**
  (`pslist`, `netstat`, `glob`, `parse_evtx`, `clients`, `flows`, `hunts`, `labels`,
  `artifacts`, `source`...). Danh sách allowlist cuối cùng được chốt ở bước
  implementation và phải có test riêng cho từng plugin.
- Deny mọi plugin/function side-effect: `execve`, `shell`, `wmi` (mutating),
  `file_write`/`upload`/`rm`/`cp`, `kill_process`, `quarantine`, `yara`, `timeline` ghi...
- Không `LET`/control tạo side-effect; chặn nhiều câu lệnh.
- Trần thời gian chạy, trần số dòng, trần ký tự kết quả.

### Guardrail SQL inventory

`SET TRANSACTION READ ONLY`; chỉ 1 câu `SELECT`/CTE (`WITH`); allowlist bảng/view;
`statement_timeout`; row cap; mask cột nhạy cảm (SĐT, CCCD); không `INSERT/UPDATE/
DELETE/DDL/COPY/CALL`. Chạy bằng role DB read-only, không qua ORM ghi.

## Audit

| Action | Nội dung |
|---|---|
| `chat.conversation.create` | actor, conversation_id, machine_id |
| `chat.conversation.delete` | actor, conversation_id |
| `chat.query.inventory` | actor, conversation_id, tool, tham số rút gọn, số dòng, thời lượng |
| `chat.query.velociraptor` | actor, conversation_id, loại truy vấn, client_id, flow_id (nếu có), số dòng |

Mỗi truy vấn → 1 dòng hash-chain. `actor` lấy từ `chat_context` đã ký.

## An toàn & bảo mật

1. **Read-only nhiều lớp:** catalog chỉ tool đọc; MCP `ENABLE_DANGEROUS_TOOLS=false`
   + policy VQL; SQL read-only role + guardrail; không DDL/DML.
2. **Không credential DB trong agent**; backend là nơi duy nhất chạm DB inventory.
3. **Secret:** `api_client.yaml` + LLM key giải mã ở backend, gửi per-request, agent ghi
   file tạm rồi xoá ngay (như DeepAgent); không log secret.
4. **Chống prompt injection:** mọi output tool là dữ liệu không tin cậy; output không
   đổi được tool policy; redact secret trước khi vào prompt; log prompt/response.
5. **AuthZ & mạng:** chỉ SuperAdmin; endpoint nội bộ cần service token + `chat_context`;
   ChatAgent không publish port, chỉ trong `inventory-net`.
6. **Chi phí/tài nguyên:** trần lượt/phút/người; ≤12 tool-call/lượt; trần tần suất
   collection/giờ/máy; theo `llm_config.daily_token_budget`.
7. **Lỗi an toàn:** không rò raw exception/prompt/evidence; format
   `[<category>] <hint> [HTTP <code>]` như DeepAgent; có nút Dừng.

## UI (Portal)

- `ChatRail` — rail phải **docked cố định** (~400px) trong `(portal)/layout.tsx`, sibling
  của cột nội dung; nội dung trang co lại (không đè); trạng thái mở/đóng lưu `localStorage`;
  màn nhỏ → drawer phủ.
- Trang `/machines/[id]`: tự tạo/đính `machine_id`; chip `Đang hỏi về: <hostname>` + nút gỡ.
- `ChatMessage` (markdown, tái dùng `investigation-markdown`), `ChatToolTrace` (chip
  gập/mở, link tới máy/flow), `useChatStream` (fetch + `ReadableStream` vì `EventSource`
  không POST được), nút Dừng.
- Danh sách hội thoại + xem lại + xoá.
- Proxy SSE mới trong portal (`pipe res.body`) giữ cookie + refresh token.

## Kiểm thử

- **Agent:** policy VQL (allow/deny), guardrail (loop ≤12, truncation, timeout),
  prompt-injection, lỗi an toàn; integration MCP giả + LLM giả.
- **Backend:** auth SuperAdmin, CRUD hội thoại, **audit được ghi**, SSE; endpoint nội bộ
  (service token + `chat_context`), guardrail SQL (chặn DML/DDL/nhiều câu), rate limit.
- **Portal:** vitest cho `ChatRail` (docked/co layout), context chip, `useChatStream` parse SSE.
- **E2E:** smoke trên compose stack (tạo → hỏi → câu trả lời + audit + tool trace).

## Triển khai

- Container `chatagent/` (Dockerfile clone `mcp-velociraptor` ở commit pin, như DeepAgent),
  không publish port; thêm vào `docker-compose.yml` + `build-all.sh`.
- Env `CHATAGENT_*` vào `.env.example` + `scripts/gen-env-example.py`.
- Migration Alembic cho 2 bảng.
- Sửa: `server/app/main.py` (router), `portal/lib/backend.ts` + route proxy SSE mới,
  `portal/app/(portal)/layout.tsx` (thêm `ChatRail`).
- Log có cấu trúc theo pattern `observability`; bật/tắt bằng cờ cấu hình; pilot SuperAdmin.

## Future work

- Mở cho vai trò admin/officer theo phạm vi org.
- Hợp nhất với luồng điều tra theo lô.
- Tool phê duyệt (approval) cho hành động nặng nếu sau này cho phép.
