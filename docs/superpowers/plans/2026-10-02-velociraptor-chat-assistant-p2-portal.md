# Chat Assistant — P2 Portal Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the docked right-side `ChatRail` chat panel in the portal: streaming SSE proxy, token-by-token rendering, tool-trace chips, conversation history, soft machine context, and cancel — for SuperAdmin only.

**Architecture:** `ChatRail` is a layout-level sibling of the portal content column, so the page content shrinks instead of being covered. A dedicated Next.js route proxies the backend SSE stream (the generic BFF buffers responses). A `useChatStream` hook parses SSE frames from `fetch` + `ReadableStream`. Conversation CRUD reuses the existing `api` client and `/api/proxy` BFF.

**Tech Stack:** Next.js App Router (React 19), TypeScript, Tailwind, lucide-react, vitest + react-dom/server.

**Spec:** `docs/superpowers/specs/2026-10-02-velociraptor-chat-assistant-design.md`
**Depends on:** P1 foundation (`chat` API + `chatagent`) must be implemented first.

## Global Constraints

- Only SuperAdmin sees/uses the rail (same role gate as `/dfir`).
- The rail is docked right, never modal; open/close persisted in `localStorage`; small screens → overlay drawer.
- SSE is non-resumable in P1/P2; on disconnect the client reloads conversation history.
- Machine context is a soft default: `/machines/[id]` sets a per-turn chip; it never silently mutates stored conversation context.
- Never render raw tool payloads; show only safe trace fields (tool, row count, duration, client_id/flow_id).
- Vietnamese UI copy; reuse `investigation-markdown` for assistant text.
- No new state library; use React context + hooks.

---

## File Structure

**Create:**
- `portal/lib/chat.ts` — chat API wrappers + types re-export.
- `portal/app/api/chat/stream/route.ts` — streaming SSE proxy.
- `portal/components/chat/use-chat-stream.ts` — SSE client hook.
- `portal/components/chat/use-chat-panel.ts` — open state + machine context derivation.
- `portal/components/chat/chat-rail.tsx` — panel shell.
- `portal/components/chat/chat-message.tsx` — message rendering.
- `portal/components/chat/chat-tool-trace.tsx` — tool-call chips.
- `portal/components/chat/chat-conversation-list.tsx` — history list.
- `portal/components/chat/chat-context-chip.tsx` — machine context chip.

**Modify:**
- `portal/lib/types.ts` — chat DTO types.
- `portal/app/(portal)/layout.tsx` — mount `<ChatRail />`.

**Tests:** `portal/__tests__/chat-*.test.ts(x)`.

---

## Task 1: Chat DTO types + API wrappers

**Files:**
- Modify: `portal/lib/types.ts`
- Create: `portal/lib/chat.ts`
- Test: `portal/__tests__/chat-api.test.ts`

**Interfaces:**
- Types: `ChatConversation`, `ChatMessage`, `ChatTurn`, `ChatToolCall`, `ChatConversationDetail`, `ChatSseEvent`.
- `chatApi.listConversations()`, `.getConversation(id)`, `.createConversation({title?, machine_id?})`, `.patchConversation(id, patch)`, `.deleteConversation(id)`, `.cancelTurn(id, turnId)`.

- [x] **Step 1: Write failing test** — wrappers hit the right paths via the mocked `api`.

```ts
// portal/__tests__/chat-api.test.ts
import { describe, it, expect, vi } from "vitest";
vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue(undefined),
  },
}));
import { api } from "@/lib/api";
import { chatApi } from "@/lib/chat";

describe("chatApi", () => {
  it("lists conversations", async () => {
    await chatApi.listConversations();
    expect(api.get).toHaveBeenCalledWith("/chat/conversations", expect.anything());
  });
  it("creates with machine context", async () => {
    await chatApi.createConversation({ machine_id: "m1" });
    expect(api.post).toHaveBeenCalledWith("/chat/conversations", { machine_id: "m1" });
  });
  it("cancels a turn", async () => {
    await chatApi.cancelTurn("c1", "t1");
    expect(api.post).toHaveBeenCalledWith("/chat/conversations/c1/cancel", { turn_id: "t1" });
  });
});
```

- [x] **Step 2: Run test, verify it fails**

Run: `cd portal && pnpm test -- chat-api`
Expected: FAIL (module not found).

- [x] **Step 3: Implement types and wrappers**

```ts
// portal/lib/chat.ts
import { api } from "@/lib/api";
import type { ChatConversation, ChatConversationDetail } from "@/lib/types";

export const chatApi = {
  listConversations: (params?: { limit?: number; offset?: number; archived?: boolean }) =>
    api.get<{ items: ChatConversation[]; total: number }>("/chat/conversations", params),
  getConversation: (id: string) => api.get<ChatConversationDetail>(`/chat/conversations/${id}`),
  createConversation: (body: { title?: string | null; machine_id?: string | null }) =>
    api.post<ChatConversation>("/chat/conversations", body),
  patchConversation: (id: string, body: { title?: string | null; machine_id?: string | null }) =>
    api.patch<ChatConversation>(`/chat/conversations/${id}`, body),
  deleteConversation: (id: string) => api.delete<void>(`/chat/conversations/${id}`),
  cancelTurn: (id: string, turnId: string) =>
    api.post<{ status: string }>(`/chat/conversations/${id}/cancel`, { turn_id: turnId }),
};
```

Define the DTO types in `types.ts` exactly per spec: `ChatMessage = { id; role; content; turn_id: string | null; machine_id: string | null; error_category: string | null; created_at }`, `ChatConversationDetail` adds `messages: ChatMessage[]; active_turn_id: string | null`, `ChatSseEvent` = discriminated union of the seven event types.

- [x] **Step 4: Run test, verify it passes.**

- [x] **Step 5: Commit**

```bash
git add portal/lib/chat.ts portal/lib/types.ts portal/__tests__/chat-api.test.ts
git commit -m "feat(portal): chat API types and wrappers"
```

---

## Task 2: Streaming SSE proxy route

**Files:**
- Create: `portal/app/api/chat/stream/route.ts`
- Test: `portal/__tests__/chat-stream-route.test.ts`

**Interfaces:**
- `POST` body `{ conversation_id: string, content: string, machine_context?: { machine_id: string } | null, idempotency_key: string }`.
- Upstream: `POST {API_BASE}/api/chat/conversations/{id}/messages`; relays `text/event-stream` body.

- [x] **Step 1: Write failing test** — a mocked upstream SSE response is relayed with streaming headers.

```ts
// portal/__tests__/chat-stream-route.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/backend", () => ({
  API_BASE: "http://api.test",
  getSessionTokens: vi.fn().mockResolvedValue({ access: "tok", refresh: "ref" }),
  refreshTokens: vi.fn(),
  forwardedIpHeaders: vi.fn().mockReturnValue({}),
}));

import { POST } from "@/app/api/chat/stream/route";

describe("chat stream proxy", () => {
  it("relays SSE body and headers", async () => {
    const body = new ReadableStream({
      start(c) { c.enqueue(new TextEncoder().encode("event: token\ndata: {\"text\":\"hi\"}\n\n")); c.close(); },
    });
    global.fetch = vi.fn().mockResolvedValue(new Response(body, {
      status: 200, headers: { "content-type": "text/event-stream" },
    }));
    const res = await POST(new Request("http://localhost/api/chat/stream", {
      method: "POST", body: JSON.stringify({ conversation_id: "c1", content: "hi", idempotency_key: "k1" }),
    }));
    expect(res.headers.get("content-type")).toContain("text/event-stream");
    expect(res.headers.get("x-accel-buffering")).toBe("no");
    expect(await res.text()).toContain("event: token");
  });
});
```

- [x] **Step 2: Run test, verify it fails.**

- [x] **Step 3: Implement the route**

```ts
// portal/app/api/chat/stream/route.ts
import { API_BASE, getSessionTokens, refreshTokens, forwardedIpHeaders } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function upstream(path: string, method: string, access: string | null, body: string, extra: Record<string, string>) {
  return fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "content-type": "application/json",
      ...(access ? { authorization: `Bearer ${access}` } : {}),
      accept: "text/event-stream",
      ...extra,
    },
    body,
    redirect: "manual",
    signal: AbortSignal.timeout(360_000),
  });
}

export async function POST(request: Request) {
  const payload = await request.text();
  const { conversation_id } = JSON.parse(payload) as { conversation_id: string };
  const { access, refresh } = await getSessionTokens();
  const extra = forwardedIpHeaders(request);
  const path = `/api/chat/conversations/${encodeURIComponent(conversation_id)}/messages`;

  let res = await upstream(path, "POST", access, payload, extra);
  let newPair: { access: string; refresh: string } | null = null;
  if (res.status === 401 && refresh) {
    newPair = await refreshTokens(refresh);
    if (newPair) res = await upstream(path, "POST", newPair.access, payload, extra);
  }
  if (!res.body) return new Response(JSON.stringify({ category: "chat_internal", hint: "No upstream stream" }), { status: 502 });

  const headers = new Headers({
    "content-type": "text/event-stream",
    "cache-control": "no-store, no-transform",
    connection: "keep-alive",
    "x-accel-buffering": "no",
  });
  if (newPair) {
    // reuse setSessionTokens on a NextResponse in the real implementation (copy cookie pattern from lib/backend.ts)
  }
  return new Response(res.body, { status: res.status, headers });
}
```

- [x] **Step 4: Run test, verify it passes.**

- [x] **Step 5: Commit** `feat(portal): dedicated SSE streaming proxy route`.

---

## Task 3: `useChatStream` hook (SSE parser)

**Files:**
- Create: `portal/components/chat/use-chat-stream.ts`
- Test: `portal/__tests__/use-chat-stream.test.ts`

**Interfaces:**
- `useChatStream(conversationId)` → `{ messages, streaming, activeTurnId, error, send(content, machineContext?), cancel(), reset() }`.
- Exported pure helper `parseSseFrame(frame: string): ChatSseEvent | null` (unit-testable).

- [x] **Step 1: Write failing tests** — parse frames, accumulate tokens, persist on done, abort.

```ts
// portal/__tests__/use-chat-stream.test.ts
import { describe, it, expect } from "vitest";
import { parseSseFrame, reduceEvent } from "@/components/chat/use-chat-stream";

describe("parseSseFrame", () => {
  it("parses a data frame", () => {
    const ev = parseSseFrame('event: token\ndata: {"v":1,"seq":2,"type":"token","text":"hi"}');
    expect(ev).toMatchObject({ type: "token", text: "hi" });
  });
  it("ignores heartbeat comments", () => {
    expect(parseSseFrame(":hb")).toBeNull();
  });
});

describe("reduceEvent", () => {
  it("appends token deltas and records tool traces", () => {
    let s = { content: "", tools: [] as unknown[], done: false };
    s = reduceEvent(s, { type: "token", text: "Hel" });
    s = reduceEvent(s, { type: "tool_start", tool: "inventory_search", tool_call_id: "t1" });
    s = reduceEvent(s, { type: "token", text: "lo" });
    expect(s.content).toBe("Hello");
    expect(s.tools).toHaveLength(1);
  });
});
```

- [x] **Step 2: Run tests, verify they fail.**

- [x] **Step 3: Implement**

```ts
export function parseSseFrame(frame: string): ChatSseEvent | null {
  const data = frame.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("");
  if (!data) return null;
  try { return JSON.parse(data) as ChatSseEvent; } catch { return null; }
}
```

The hook uses `fetch("/api/chat/stream", { method: "POST", body, signal })`, reads `res.body!.getReader()`, buffers text, splits on `\n\n`, and dispatches via `parseSseFrame` + `reduceEvent`. `cancel()` calls `chatApi.cancelTurn` with the current `active_turn_id`.

- [x] **Step 4: Run tests, verify they pass.**

- [x] **Step 5: Commit** `feat(portal): useChatStream SSE client hook`.

---

## Task 4: Machine-context derivation utility

**Files:**
- Create: `portal/components/chat/use-chat-panel.ts`
- Test: `portal/__tests__/chat-context-derive.test.ts`

**Interfaces:**
- `deriveMachineId(pathname: string): string | null`
- `useChatPanel()` → `{ open, setOpen, machineId, pendingMachineId, setPendingMachineId }` (open state in `localStorage` key `chat-rail-open`).

- [x] **Step 1: Write failing tests**

```ts
import { describe, it, expect } from "vitest";
import { deriveMachineId } from "@/components/chat/use-chat-panel";

describe("deriveMachineId", () => {
  it("extracts id on the machine detail route", () => {
    expect(deriveMachineId("/machines/11111111-1111-4111-8111-111111111111"))
      .toBe("11111111-1111-4111-8111-111111111111");
  });
  it("returns null elsewhere", () => {
    expect(deriveMachineId("/dashboard")).toBeNull();
    expect(deriveMachineId("/machines")).toBeNull();
  });
});
```

- [x] **Step 2–4: Run fail → implement → run pass.** Implementation: regex `^/machines/([0-9a-f-]{36})$` case-insensitive; `useChatPanel` reads/writes `localStorage` in an effect (SSR-safe guard), and sets `pendingMachineId` from `usePathname()` whenever it changes while the rail is open.

- [x] **Step 5: Commit** `feat(portal): chat panel state and machine context derivation`.

---

## Task 5: Message + tool-trace components

**Files:**
- Create: `portal/components/chat/chat-message.tsx`, `portal/components/chat/chat-tool-trace.tsx`
- Test: `portal/__tests__/chat-message.test.tsx`

**Interfaces:**
- `<ChatMessage role content tools errorCategory createdAt />`
- `<ChatToolTrace tools />` where `tools: ChatToolCall[]`.

- [x] **Step 1: Write failing SSR tests**

```tsx
import { renderToString } from "react-dom/server";
import { ChatMessage } from "@/components/chat/chat-message";

it("renders assistant markdown and tool chips", () => {
  const html = renderToString(<ChatMessage role="assistant" content="**bold**" createdAt={new Date().toISOString()}
    tools={[{ tool_call_id: "t1", tool: "inventory_search", ok: true, row_count: 3, duration_ms: 12 } as never]} />);
  expect(html).toContain("inventory_search");
  expect(html).toContain("3");
});
it("renders error category safely", () => {
  const html = renderToString(<ChatMessage role="assistant" content="" errorCategory="chat_timeout_llm" createdAt={new Date().toISOString()} tools={[]} />);
  expect(html).toContain("chat_timeout_llm");
});
```

- [x] **Step 2–4: Run fail → implement → pass.** Reuse `InvestigationMarkdown` for assistant content. `ChatToolTrace` renders collapsible chips; never renders raw payloads.

- [x] **Step 5: Commit** `feat(portal): chat message and tool trace components`.

---

## Task 6: Conversation list + history

**Files:**
- Create: `portal/components/chat/chat-conversation-list.tsx`
- Test: `portal/__tests__/chat-conversation-list.test.tsx`

**Interfaces:**
- `<ChatConversationList items activeId onSelect onCreate onDelete />`.

- [x] **Step 1: Write failing SSR test** — renders titles, calls `onCreate`/`onDelete` props exist, empty state copy.
- [x] **Step 2–4: Run fail → implement → pass.** List shows `title ?? "Hội thoại mới"`, relative `last_message_at`; delete asks confirm.
- [x] **Step 5: Commit** `feat(portal): chat conversation list`.

---

## Task 7: `ChatRail` shell + dock in layout

**Files:**
- Create: `portal/components/chat/chat-rail.tsx`
- Modify: `portal/app/(portal)/layout.tsx`
- Test: `portal/__tests__/chat-rail.test.tsx`

**Interfaces:**
- `<ChatRail />` consumes `useChatPanel`, `useChatStream`, `chatApi`, `useAuth`.

- [x] **Step 1: Write failing SSR tests** — closed by default renders nothing (or a toggle button); when `open` renders panel header, conversation list, input; non-SuperAdmin renders nothing.
- [x] **Step 2–4: Run fail → implement → pass.**

```tsx
// portal/app/(portal)/layout.tsx (inside Shell root flex, after the content column)
<ChatRail />
```

Rail styles: `w-[400px] shrink-0 border-l border-slate-200 bg-white hidden md:flex flex-col` when open; `md:hidden` overlay drawer when small. Toggle button lives in the header; open state from `useChatPanel`.

- [x] **Step 5: Commit** `feat(portal): docked ChatRail mounted in portal layout`.

---

## Task 8: Machine context chip behavior

**Files:**
- Create: `portal/components/chat/chat-context-chip.tsx`
- Modify: `portal/components/chat/chat-rail.tsx`
- Test: `portal/__tests__/chat-context-chip.test.tsx`

**Interfaces:**
- `<ChatContextChip machineId hostname pinned onClear onPin />`.

- [x] **Step 1: Write failing SSR tests** — shows `Đang hỏi về: <hostname>`; clear button; pin button.
- [x] **Step 2–4: Run fail → implement → pass.** Send flow: if no active conversation, `createConversation({ machine_id })`; else pass `machine_context` per-turn. "Ghim" calls `patchConversation(id, { machine_id })`. Clear resets to stored `machine_id` (if any).
- [x] **Step 5: Commit** `feat(portal): machine context chip with soft per-turn override`.

---

## Task 9: Cancel, error, and retry UX + final wiring

**Files:**
- Modify: `portal/components/chat/chat-rail.tsx`, `portal/components/chat/use-chat-stream.ts`
- Test: `portal/__tests__/chat-rail-cancel.test.tsx`

**Interfaces:**
- Stop button calls `cancel()`; error banner renders `[category] hint`; retry re-sends last content.

- [x] **Step 1: Write failing tests** — stop button disabled when not streaming; error banner shows category; retry restores input.
- [x] **Step 2–4: Run fail → implement → pass.**
- [x] **Step 5: Manual smoke** — ĐÃ CHẠY e2e qua curl + proxy SSE thật (start/token/usage/done/tool_start/tool_result, idempotency, cancel 409/404, audit chain v2). Phần UI click tay trên trình duyệt vẫn cần người dùng xác nhận.
- [x] **Step 6: Commit** `feat(portal): chat cancel/error/retry UX and final wiring` (49bb10d).

---

## Self-Review

- **Spec coverage:** docked UI → T7; SSE proxy + non-buffer headers → T2; streaming hook → T3; soft machine context → T4,T8; conversation history/list → T6; markdown + tool trace → T5; cancel/error → T9; ownership/role gate → T7. Backend persistence/audit/limits are P1.
- **Placeholders:** none intentionally; DTO shapes must match the P1 schema in the spec §"Hợp đồng API".
- **Type consistency:** `active_turn_id`, `machine_context`, `tool_call_id`, error `category` names match the spec SSE taxonomy.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-02-velociraptor-chat-assistant-p2-portal.md`.

Execute P1 first (backend/chatagent), then P2. Two execution options per plan: **Subagent-Driven (recommended)** or **Inline Execution**.
