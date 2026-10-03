# P2 Portal — Contract Decisions (đóng băng trước khi code)

Nguồn chân lý: `docs/superpowers/specs/2026-10-02-velociraptor-chat-assistant-design.md` §"Hợp đồng API" (L281–393).

Nhằm loại conflict khi P1 (backend) và P2 (portal) chạy song song.

## D1 — Idempotency đi qua header, không nằm trong body

- **Spec L292/L116:** `POST /api/chat/conversations/{id}/messages` nhận header `Idempotency-Key`;
  DB có `UNIQUE (conversation_id, idempotency_key)`.
- **P2 plan Task 2** (bản gốc) gửi `idempotency_key` trong JSON body → **sai contract**, sẽ bị P1
  T11 (`schemas/chat.py`) bỏ qua, mỗi lần retry sinh turn trùng.
- **Chốt:** proxy route nhận `idempotency_key` trong body từ client (tiện cho `useChatStream`),
  **bóc ra khỏi body** và chuyển thành header `Idempotency-Key` khi pipe lên upstream.
  Body upstream chỉ còn `{content, machine_context?}` → tương thích Pydantic `extra=forbid`.

## D2 — `machine_context` shape

Spec L359: `{ machine_id, client_id?, hostname? }`. P2 chỉ gửi `{ machine_id, hostname? }`
(`client_id` do backend resolve, không phải client tự khai).

## D3 — `reduceEvent` phải phủ đủ 7 event của `chat.sse/1`

Spec L375–390: `start | tool_start | tool_result | token | usage | done | error`.
- P2 plan Task 3 (bản gốc) mới xử lý `token` + `tool_start` → thiếu `error`/`usage`/`tool_result`,
  nhưng Task 9 cần `error.category`.
- **Chốt:** `reduceEvent` xử lý đủ 7 loại. `done` mang `finish_reason` + `message_id`
  (không phải boolean). `tool_result` là nguồn duy nhất của `row_count`/`duration_ms`/`client_id`.

## D4 — Ranh giới render an toàn

Chỉ render field an toàn trong `ChatToolTrace`: `tool`, `ok`, `row_count`, `byte_count`,
`duration_ms`, `client_id`, `flow_id`, `error_category`.
**Không** render `params_digest`, `args_digest`, `summary`, hay payload thô.

## D5 — Lỗi trong stream

Spec L392: lỗi **trước** stream → HTTP JSON; lỗi **trong** stream → event `error` rồi đóng.
Proxy route **không** tự retry sau khi stream đã bắt đầu (spec §UI L572).

## D6 — Ranh giới chạy song song

P1 chạm `server/`, `chatagent/`, `docker-compose.yml`, `.env.example`, `scripts/`, `build-all.sh`.
P2 chỉ chạm `portal/`. Worktree riêng: `.worktrees/p2-portal` trên branch
`research/velociraptor-chat-assistant-p2`.

**Task 9 Step 5 (smoke test tay) bị block** cho tới khi P1 xong T11 + T15 + T16.