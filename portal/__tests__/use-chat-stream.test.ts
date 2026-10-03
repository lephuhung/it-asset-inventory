import { describe, it, expect, vi } from "vitest";

import { parseSseFrame, reduceEvent, initialStreamState, runChatStream } from "@/components/chat/use-chat-stream";
import type { ChatSseEvent } from "@/lib/types";

function frame(data: unknown, name?: string): string {
  const t = name ?? (data as { type: string }).type;
  return `event: ${t}\ndata: ${JSON.stringify(data)}\n\n`;
}

function chunked(chunks: string[]): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

describe("parseSseFrame", () => {
  it("parses a data frame", () => {
    const ev = parseSseFrame('event: token\ndata: {"v":1,"seq":2,"type":"token","text":"hi"}');
    expect(ev).toMatchObject({ type: "token", text: "hi" });
  });

  it("ignores heartbeat comments", () => {
    expect(parseSseFrame(":hb")).toBeNull();
    expect(parseSseFrame(": keep-alive 2026-10-02T00:00:00Z")).toBeNull();
  });

  it("returns null when there is no data line", () => {
    expect(parseSseFrame("event: token")).toBeNull();
    expect(parseSseFrame("")).toBeNull();
  });

  it("returns null on malformed JSON instead of throwing", () => {
    expect(parseSseFrame("event: token\ndata: {not json")).toBeNull();
  });

  it("joins multi-line data fields", () => {
    const ev = parseSseFrame('event: token\ndata: {"v":1,"seq":1,\ndata: "type":"token","text":"a"}');
    expect(ev).toMatchObject({ type: "token", text: "a" });
  });

  it("tolerates CRLF line endings and a missing leading space", () => {
    expect(parseSseFrame('event: token\r\ndata:{"v":1,"seq":1,"type":"token","text":"x"}')).toMatchObject({
      text: "x",
    });
  });

  it("falls back to the event name when the payload has no type", () => {
    expect(parseSseFrame('event: token\ndata: {"v":1,"seq":1,"text":"x"}')).toMatchObject({
      type: "token",
      text: "x",
    });
  });

  it("skips fields the payload does not declare (no fabrication)", () => {
    const ev = parseSseFrame('event: token\ndata: {"v":1,"seq":1,"type":"token","text":"x"}');
    expect(ev).not.toHaveProperty("tool_call_id");
  });
});

describe("reduceEvent", () => {
  it("appends token deltas and records tool traces", () => {
    let s = initialStreamState();
    s = reduceEvent(s, { v: 1, seq: 1, type: "token", text: "Hel" });
    s = reduceEvent(s, { v: 1, seq: 2, type: "tool_start", tool_call_id: "t1", tool: "inventory_search", params_digest: null, summary: null });
    s = reduceEvent(s, { v: 1, seq: 3, type: "token", text: "lo" });
    expect(s.content).toBe("Hello");
    expect(s.tools).toHaveLength(1);
  });

  it("captures the turn from the start event", () => {
    const s = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "start", turn_id: "t1", message_id: "m1",
    });
    expect(s.turnId).toBe("t1");
    expect(s.messageId).toBe("m1");
    expect(s.status).toBe("streaming");
  });

  it("merges tool_result into the matching tool call", () => {
    let s = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "tool_start", tool_call_id: "t1", tool: "inventory_search", params_digest: null, summary: null,
    });
    s = reduceEvent(s, {
      v: 1, seq: 2, type: "tool_result", tool_call_id: "t1", ok: true,
      row_count: 3, byte_count: 128, duration_ms: 12, client_id: "C.1", flow_id: "F.1",
    });
    expect(s.tools[0]).toMatchObject({ ok: true, row_count: 3, duration_ms: 12, client_id: "C.1", flow_id: "F.1" });
  });

  it("adds a tool entry when tool_result arrives without tool_start", () => {
    const s = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "tool_result", tool_call_id: "t9", ok: false,
      row_count: null, byte_count: null, duration_ms: 5, error_category: "chat_timeout_tool",
    });
    expect(s.tools).toHaveLength(1);
    expect(s.tools[0]).toMatchObject({ tool_call_id: "t9", ok: false, error_category: "chat_timeout_tool" });
  });

  it("ignores duplicate tool_start for the same tool_call_id", () => {
    let s = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "tool_start", tool_call_id: "t1", tool: "a", params_digest: null, summary: null,
    });
    s = reduceEvent(s, {
      v: 1, seq: 2, type: "tool_start", tool_call_id: "t1", tool: "a", params_digest: null, summary: null,
    });
    expect(s.tools).toHaveLength(1);
  });

  it("records usage", () => {
    const s = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "usage", input_tokens: 10, output_tokens: 20,
    });
    expect(s.usage).toEqual({ input_tokens: 10, output_tokens: 20 });
  });

  it("records the error category and hint without losing streamed text", () => {
    let s = reduceEvent(initialStreamState(), { v: 1, seq: 1, type: "token", text: "partial" });
    s = reduceEvent(s, {
      v: 1, seq: 2, type: "error", category: "chat_timeout_llm", hint: "Mô hình phản hồi quá lâu.", retryable: true,
    });
    expect(s.error).toMatchObject({ category: "chat_timeout_llm", retryable: true });
    expect(s.content).toBe("partial");
    expect(s.status).toBe("error");
  });

  it("maps finish_reason to a terminal status", () => {
    const stopped = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "done", message_id: "m1", finish_reason: "stop",
    });
    expect(stopped.status).toBe("done");

    const canceled = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "done", message_id: "m1", finish_reason: "canceled",
    });
    expect(canceled.status).toBe("canceled");

    const failed = reduceEvent(initialStreamState(), {
      v: 1, seq: 1, type: "done", message_id: "m1", finish_reason: "error",
    });
    expect(failed.status).toBe("error");
  });

  it("drops out-of-order and replayed events by seq", () => {
    let s = reduceEvent(initialStreamState(), { v: 1, seq: 1, type: "token", text: "A" });
    s = reduceEvent(s, { v: 1, seq: 1, type: "token", text: "A-replayed" });
    s = reduceEvent(s, { v: 1, seq: 0, type: "token", text: "old" });
    expect(s.content).toBe("A");
  });

  it("never mutates the input state", () => {
    const before = initialStreamState();
    const snapshot = JSON.stringify(before);
    reduceEvent(before, { v: 1, seq: 1, type: "token", text: "x" });
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});

describe("runChatStream", () => {
  const args = (res: Response, onState = vi.fn()) => ({
    conversationId: "c1",
    content: "xin chào",
    idempotencyKey: "k1",
    signal: undefined as AbortSignal | undefined,
    onState,
    fetchImpl: vi.fn().mockResolvedValue(res) as unknown as typeof fetch,
  });

  it("streams every event through onState", async () => {
    const onState = vi.fn();
    const state = await runChatStream({
      ...args(chunked([frame({ v: 1, seq: 1, type: "start", turn_id: "t1", message_id: "m1" }), frame({ v: 1, seq: 2, type: "token", text: "Chào" }), frame({ v: 1, seq: 3, type: "token", text: " bạn" }), frame({ v: 1, seq: 4, type: "done", message_id: "m1", finish_reason: "stop" })]), onState),
    });

    expect(state.content).toBe("Chào bạn");
    expect(state.status).toBe("done");
    expect(onState).toHaveBeenCalled();
  });

  it("posts the body, machine context and idempotency key to the local stream route", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(chunked([]));
    await runChatStream({
      conversationId: "c1",
      content: "kiểm tra",
      machineContext: { machine_id: "m1", hostname: "WS-01" },
      idempotencyKey: "k1",
      onState: vi.fn(),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/chat/stream");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      conversation_id: "c1",
      content: "kiểm tra",
      machine_context: { machine_id: "m1", hostname: "WS-01" },
      idempotency_key: "k1",
    });
  });

  it("reassembles frames split across chunk boundaries", async () => {
    const whole = frame({ v: 1, seq: 1, type: "token", text: "Hello" });
    const res = chunked([whole.slice(0, 12), whole.slice(12, 30), whole.slice(30)]);
    const state = await runChatStream(args(res));
    expect(state.content).toBe("Hello");
  });

  it("processes a trailing frame that never got its blank line", async () => {
    const res = chunked(['event: token\ndata: {"v":1,"seq":1,"type":"token","text":"tail"}']);
    const state = await runChatStream(args(res));
    expect(state.content).toBe("tail");
  });

  it("surfaces a pre-stream JSON error as an error state", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ category: "chat_conflict_active_turn", hint: "Đang có lượt chạy." }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );

    const state = await runChatStream({
      conversationId: "c1", content: "hi", onState: vi.fn(),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(state.status).toBe("error");
    expect(state.error?.category).toBe("chat_conflict_active_turn");
  });

  it("reports a lost stream when the body ends without a done event", async () => {
    const res = chunked([frame({ v: 1, seq: 1, type: "start", turn_id: "t1", message_id: "m1" }), frame({ v: 1, seq: 2, type: "token", text: "dở" })]);
    const state = await runChatStream(args(res));

    expect(state.status).toBe("error");
    expect(state.error?.category).toBe("chat_stream_lost");
    expect(state.content).toBe("dở");
  });

  it("reports cancellation instead of a lost stream when the user aborts", async () => {
    const controller = new AbortController();
    const enc = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode(frame({ v: 1, seq: 1, type: "token", text: "dở" })));
        // Người dùng bấm Dừng giữa chừng.
        controller.abort();
        c.close();
      },
    });
    const res = new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });

    const state = await runChatStream({ ...args(res), signal: controller.signal });

    expect(state.status).toBe("canceled");
    expect(state.error).toBeNull();
    expect(state.content).toBe("dở");
  });

  it("keeps the server error category when the stream carries an error event", async () => {
    const res = chunked([frame({ v: 1, seq: 1, type: "error", category: "chat_budget_exceeded", hint: "Hết hạn mức.", retryable: false })]);
    const state = await runChatStream(args(res));
    expect(state.error).toMatchObject({ category: "chat_budget_exceeded", retryable: false });
  });

  it("ignores heartbeat frames mid-stream", async () => {
    const res = chunked([
      ": hb\n\n",
      frame({ v: 1, seq: 1, type: "token", text: "ok" }),
      ": keep-alive\n\n",
      frame({ v: 1, seq: 2, type: "done", message_id: "m", finish_reason: "stop" }),
    ]);
    const state = await runChatStream(args(res));
    expect(state.content).toBe("ok");
    expect(state.error).toBeNull();
    expect(state.status).toBe("done");
  });

  it("reports a network failure as chat_internal", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("socket hang up"));
    const state = await runChatStream({
      conversationId: "c1", content: "hi", onState: vi.fn(),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(state.error?.category).toBe("chat_internal");
  });

  it("generates an idempotency key when the caller does not supply one", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(chunked([]));
    await runChatStream({
      conversationId: "c1", content: "hi", onState: vi.fn(),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body).idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("propagates the abort signal to fetch", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn().mockResolvedValue(chunked([]));
    await runChatStream({
      conversationId: "c1", content: "hi", signal: controller.signal, onState: vi.fn(),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it("emits partial state as tokens arrive", async () => {
    const seen: string[] = [];
    const res = chunked([
      frame({ v: 1, seq: 1, type: "token", text: "A" }),
      frame({ v: 1, seq: 2, type: "token", text: "B" }),
      frame({ v: 1, seq: 3, type: "done", message_id: "m", finish_reason: "stop" }),
    ]);
    await runChatStream({
      ...args(res),
      onState: (s) => {
        if (s.content) seen.push(s.content);
      },
    });
    expect(seen).toEqual(["A", "AB", "AB"]);
  });
});

describe("ChatSseEvent typing", () => {
  it("keeps the seven spec event types", () => {
    const types: ChatSseEvent["type"][] = [
      "start", "tool_start", "tool_result", "token", "usage", "done", "error",
    ];
    expect(types).toHaveLength(7);
  });
});
describe("seq khởi đầu bằng 0 (contract mở, spec chỉ yêu cầu đơn điệu)", () => {
  it("nhận event đầu tiên có seq = 0", () => {
    const s = reduceEvent(initialStreamState(), { v: 1, seq: 0, type: "token", text: "A" });
    expect(s.content).toBe("A");
  });

  it("vẫn loại event lặp sau đó khi bắt đầu từ 0", () => {
    let s = reduceEvent(initialStreamState(), { v: 1, seq: 0, type: "token", text: "A" });
    s = reduceEvent(s, { v: 1, seq: 0, type: "token", text: "A-again" });
    expect(s.content).toBe("A");
  });

  it("nhận event đầu tiên có seq = 1", () => {
    const s = reduceEvent(initialStreamState(), { v: 1, seq: 1, type: "token", text: "A" });
    expect(s.content).toBe("A");
  });
});
