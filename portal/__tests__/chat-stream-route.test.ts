import { describe, it, expect, vi, beforeEach } from "vitest";

const tokens = { access: "tok", refresh: "ref" };

vi.mock("@/lib/backend", () => ({
  API_BASE: "http://api.test",
  getSessionTokens: vi.fn(async () => tokens),
  refreshTokens: vi.fn(async () => null),
  forwardedIpHeaders: vi.fn(() => ({ "X-Forwarded-For": "203.0.113.9" })),
  setSessionTokens: vi.fn(),
  clearSessionTokens: vi.fn(),
}));

import { API_BASE, getSessionTokens, refreshTokens, setSessionTokens } from "@/lib/backend";
import { POST } from "@/app/api/chat/stream/route";

function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const chunk of chunks) c.enqueue(enc.encode(chunk));
      c.close();
    },
  });
}

function upstreamSse(chunks: string[] = ['event: token\ndata: {"v":1,"seq":2,"type":"token","text":"hi"}\n\n']) {
  return new Response(sseBody(chunks), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function clientRequest(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://localhost/api/chat/stream", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  tokens.access = "tok";
  tokens.refresh = "ref";
  fetchMock = vi.fn().mockResolvedValue(upstreamSse());
  vi.stubGlobal("fetch", fetchMock);
});

describe("chat stream proxy", () => {
  it("relays the SSE body with anti-buffering headers", async () => {
    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi", idempotency_key: "k1" }));

    expect(res.headers.get("content-type")).toContain("text/event-stream");
    expect(res.headers.get("x-accel-buffering")).toBe("no");
    expect(res.headers.get("cache-control")).toContain("no-store");
    expect(await res.text()).toContain("event: token");
  });

  it("calls the messages endpoint upstream", async () => {
    await POST(clientRequest({ conversation_id: "c1", content: "hi", idempotency_key: "k1" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/chat/conversations/c1/messages`);
    expect(init.method).toBe("POST");
    expect(init.headers.authorization).toBe("Bearer tok");
    expect(init.headers.accept).toBe("text/event-stream");
  });

  it("moves idempotency_key from the body into the Idempotency-Key header (D1)", async () => {
    await POST(clientRequest({ conversation_id: "c1", content: "hi", idempotency_key: "k1" }));

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["Idempotency-Key"]).toBe("k1");
    expect(JSON.parse(init.body)).toEqual({ content: "hi" });
  });

  it("omits Idempotency-Key when the client sent none", async () => {
    await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["Idempotency-Key"]).toBeUndefined();
    expect(JSON.parse(init.body)).toEqual({ content: "hi" });
  });

  it("strips client-supplied fields out of machine_context (D2)", async () => {
    await POST(
      clientRequest({
        conversation_id: "c1",
        content: "kiểm tra",
        // Client tự khai client_id — backend phải tự resolve, không tin client.
        machine_context: { machine_id: "m1", hostname: "WS-01", client_id: "C.SPOOF", evil: "x" },
      }),
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body).machine_context).toEqual({ machine_id: "m1", hostname: "WS-01" });
  });

  it("forwards the soft machine context per turn", async () => {
    await POST(
      clientRequest({
        conversation_id: "c1",
        content: "kiểm tra",
        machine_context: { machine_id: "m1", hostname: "WS-01" },
      }),
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body).machine_context).toEqual({ machine_id: "m1", hostname: "WS-01" });
  });

  it("encodes the conversation id", async () => {
    await POST(clientRequest({ conversation_id: "a/b", content: "hi" }));
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/api/chat/conversations/a%2Fb/messages`);
  });

  it("rejects a missing conversation_id before touching upstream", async () => {
    const res = await POST(clientRequest({ content: "hi" }));

    expect(res.status).toBe(400);
    expect(await res.json()).toMatchObject({ category: "chat_validation" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an empty message body", async () => {
    const res = await POST(clientRequest({ conversation_id: "c1" }));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refreshes once on 401 and retries the stream", async () => {
    vi.mocked(refreshTokens).mockResolvedValueOnce({ access: "tok2", refresh: "ref2" });
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(upstreamSse());

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    expect(refreshTokens).toHaveBeenCalledWith("ref");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1].headers.authorization).toBe("Bearer tok2");
    expect(setSessionTokens).toHaveBeenCalledTimes(1);
    expect(res.headers.get("content-type")).toContain("text/event-stream");
  });

  it("sets refreshed cookies even when the retry fetch throws", async () => {
    vi.mocked(refreshTokens).mockResolvedValueOnce({ access: "tok2", refresh: "ref2" });
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockRejectedValueOnce(new Error("socket hang up"));

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    expect(res.status).toBe(502);
    // Không có thì browser giữ token cũ đã bị thu hồi (rotation) → 401 vĩnh viễn.
    expect(setSessionTokens).toHaveBeenCalledTimes(1);
  });

  it("sets refreshed cookies on a 502 with no upstream body", async () => {
    vi.mocked(refreshTokens).mockResolvedValueOnce({ access: "tok2", refresh: "ref2" });
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 200, headers: { "content-type": "text/event-stream" } }));

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    expect(res.status).toBe(502);
    expect(setSessionTokens).toHaveBeenCalledTimes(1);
  });

  it("does not retry more than once when the refresh token is also rejected", async () => {
    vi.mocked(refreshTokens).mockResolvedValueOnce(null);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(setSessionTokens).not.toHaveBeenCalled();
    expect(res.status).toBe(401);
  });

  it("passes a pre-stream JSON error through without inventing an SSE stream", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "chat_conflict_active_turn" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    expect(res.status).toBe(409);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(await res.json()).toEqual({ detail: "chat_conflict_active_turn" });
  });

  it("returns 502 when the upstream declares a stream but sends no body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 200, headers: { "content-type": "text/event-stream" } }),
    );

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ category: "chat_internal" });
  });

  it("forwards client IP headers for audit", async () => {
    await POST(clientRequest({ conversation_id: "c1", content: "hi" }));
    expect(fetchMock.mock.calls[0][1].headers["X-Forwarded-For"]).toBe("203.0.113.9");
  });

  it("sends no Authorization header when there is no session", async () => {
    tokens.access = null as unknown as string;
    await POST(clientRequest({ conversation_id: "c1", content: "hi" }));
    expect(fetchMock.mock.calls[0][1].headers.authorization).toBeUndefined();
  });

  it("streams every frame the upstream emits", async () => {
    fetchMock.mockResolvedValueOnce(
      upstreamSse([
        'event: start\ndata: {"v":1,"seq":1,"type":"start","turn_id":"t1","message_id":"m1"}\n\n',
        'event: token\ndata: {"v":1,"seq":2,"type":"token","text":"Hel"}\n\n',
        'event: token\ndata: {"v":1,"seq":3,"type":"token","text":"lo"}\n\n',
        'event: done\ndata: {"v":1,"seq":4,"type":"done","message_id":"m1","finish_reason":"stop"}\n\n',
      ]),
    );

    const res = await POST(clientRequest({ conversation_id: "c1", content: "hi" }));
    const text = await res.text();

    expect(text.match(/event: token/g)).toHaveLength(2);
    expect(text).toContain("finish_reason");
  });
});