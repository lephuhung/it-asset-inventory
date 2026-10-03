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
## Trạng thái thực thi (2026-10-03)

Branch `research/velociraptor-chat-assistant-p2`, worktree `.worktrees/p2-portal`.

| Task | Commit | Tests |
|---|---|---|
| T1 types + wrappers | `8d57bda` | 10 |
| T2 SSE proxy route | `c692cfb` | 15 |
| T3 `useChatStream` | `8f0f502` | 32 |
| T4 machine context | `f63df19` | 14 |
| T5 message + tool trace | `98b937b` | 16 |
| (refactor) rail state | `a34120c` | — |
| T6 conversation list | `ea05980` | 12 |
| T7+T8 rail + context chip | `13e1de3` | 16 |
| T9 cancel/error/retry | `49bb10d` | 17 |

Tổng: **162 test pass**, `tsc --noEmit` sạch, `next build` thành công, lint warning
102 → 103 (đúng bằng pattern fetch-trong-effect đã có sẵn ở `compliance-gate.tsx`).

### Sai lệch so với plan gốc (đã chủ động sửa)

1. **D1** — proxy route chuyển `idempotency_key` body → header `Idempotency-Key`.
2. **D3** — `reduceEvent` phủ đủ 7 event `chat.sse/1`, không chỉ `token`/`tool_start`.
3. Thêm `portal/components/chat/chat-ux.ts` — quyết định thuần cho composer/banner/retry
   để test được không cần jsdom (repo không cài jsdom).
4. `useSyncExternalStore` cho trạng thái mở/đóng rail thay vì `setState` trong effect.
5. `deriveMachineId` bỏ qua query/hash và chỉ nhận đúng một segment UUID.

### Còn lại

- **Task 9 Step 5 — manual smoke: BLOCKED.** Cần P1 xong T11 (public routes) +
  T15 (chatagent loop) + T16 (compose). Không thể chạy end-to-end với backend chưa có.
