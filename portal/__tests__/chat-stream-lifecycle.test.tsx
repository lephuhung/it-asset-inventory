/**
 * Regression tests cho các bug reviewer tìm ra — những đường mà bộ test cũ
 * (chỉ renderToString shell đóng) không thể chạm tới.
 *
 * Dùng jsdom + @testing-library/react để MOUNT thật hook/component, nên mới
 * kiểm được vòng đời, race giữa các promise, và hành vi khi stream abort thật.
 *
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, waitFor, cleanup, screen, fireEvent } from "@testing-library/react";
import { renderHook } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));

import { api } from "@/lib/api";
import { chatApi } from "@/lib/chat";
import { useChatStream } from "@/components/chat/use-chat-stream";

const enc = new TextEncoder();
const frame = (d: Record<string, unknown>) => `event: ${d.type}\ndata: ${JSON.stringify(d)}\n\n`;
const capturedSignals: (AbortSignal | undefined)[] = [];

function sseStream(): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      c.enqueue(enc.encode(frame({ v: 1, seq: 1, type: "start", turn_id: "t1", message_id: "m1" })));
      c.enqueue(enc.encode(frame({ v: 1, seq: 2, type: "token", text: "Xin chào" })));
      c.close();
    },
  });
}

function sseResponse(): Response {
  return new Response(sseStream(), { status: 200, headers: { "content-type": "text/event-stream" } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("B4 — hủy thật phải ra 'canceled', không phải lỗi", () => {
  it("bấm Dừng khi fetch đang chờ header → canceled, không phải chat_internal", async () => {
    // Browser thật: abort trước khi có header ⇒ fetch reject AbortError.
    const fetchImpl = vi.fn((_u: string, init: RequestInit) => {
      capturedSignals.push(init.signal ?? undefined);
      return new Promise<Response>((_res, rej) => {
        const fail = () => {
          const e = new Error("The operation was aborted.");
          e.name = "AbortError";
          rej(e);
        };
        if (init.signal?.aborted) fail();
        else init.signal?.addEventListener("abort", fail);
      });
    });
    vi.stubGlobal("fetch", fetchImpl);

    const { result } = renderHook(() => useChatStream("c1"));

    act(() => {
      void result.current.send("câu hỏi");
    });
    expect(capturedSignals.length).toBe(1);
    await act(async () => {
      await result.current.cancel();
    });

    await waitFor(() => {
      expect(result.current.state.status).toBe("canceled");
    });
    expect(result.current.state.error).toBeNull();
    expect(capturedSignals[0]?.aborted).toBe(true);
  });

  it("abort giữa lúc đọc stream → canceled và GIỮ NỘI DUNG DỞ", async () => {
    let pushed = false;
    const body = new ReadableStream<Uint8Array>({
      pull(c) {
        if (!pushed) {
          pushed = true;
          c.enqueue(enc.encode(frame({ v: 1, seq: 1, type: "token", text: "dở dang" })));
          return;
        }
        const e = new Error("aborted");
        e.name = "AbortError";
        c.error(e);
      },
    });
    vi.stubGlobal("fetch", (async (_u: string, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => {
        const e = new Error("aborted");
        e.name = "AbortError";
        try {
          (body as ReadableStream).cancel?.();
        } catch {
          /* ignore */
        }
        void e;
      });
      return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
    }) as unknown as typeof fetch);

    const { result } = renderHook(() => useChatStream("c1"));

    act(() => {
      void result.current.send("x");
    });
    await waitFor(() => {
      expect(result.current.state.content).toBe("dở dang");
    });
    await act(async () => {
      await result.current.cancel();
    });

    await waitFor(() => {
      expect(result.current.state.status).toBe("canceled");
    });
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.content).toBe("dở dang");
  });

  it("mất kết nối thật (không phải do người dùng hủy) vẫn phải báo chat_stream_lost", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.error(new Error("socket reset"));
      },
    });
    vi.stubGlobal("fetch", (async () =>
      new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } })) as unknown as typeof fetch);

    const { result } = renderHook(() => useChatStream("c1"));
    await act(async () => {
      await result.current.send("x");
    });

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.error?.category).toBe("chat_stream_lost");
  });
});

describe("B2 — stream cũ không được ghi đè state mới", () => {
  it("reset() rồi stream cũ abort về sau KHÔNG hồi sinh nội dung cũ", async () => {
    let release!: (v: Response) => void;
    const pending = new Promise<Response>((res) => {
      release = res;
    });
    const fetchImpl = vi.fn(() => pending) as unknown as typeof fetch;

    const { result } = renderHook(() => useChatStream("c1"));

    act(() => {
      void result.current.send("câu cũ");
    });
    // Stream cũ đã bắt đầu nhưng chưa trả token nào.
    act(() => {
      result.current.reset();
    });
    // Giải phóng request cũ muộn mới.
    await act(async () => {
      release(
        new Response(
          new ReadableStream({
            start(c) {
              c.enqueue(enc.encode(frame({ v: 1, seq: 1, type: "token", text: "NỘI DUNG CŨ" })));
              c.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        ),
      );
      await pending;
    });

    expect(result.current.state.content).not.toContain("NỘI DUNG CŨ");
    expect(result.current.state.status).toBe("idle");
  });

  it("cancel() bị trễ KHÔNG được ghi đè state của stream mới", async () => {
    const cancelDeferred = { resolve: (_v: unknown) => {} };
    vi.spyOn(chatApi, "cancelTurn").mockReturnValue(
      new Promise((res) => {
        cancelDeferred.resolve = res;
      }) as never,
    );

    let release!: (v: Response) => void;
    const pending = new Promise<Response>((res) => {
      release = res;
    });
    const fetchImpl = vi.fn(() => pending) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);

    const { result } = renderHook(() => useChatStream("c1"));

    await act(async () => {
      void result.current.send("câu một");
      await Promise.resolve();
    });

    // Bấm Dừng (cancelTurn đang bay), rồi gửi câu mới.
    let cancelPromise!: Promise<void>;
    act(() => {
      cancelPromise = result.current.cancel();
    });
    await act(async () => {
      void result.current.send("câu hai");
    });

    // cancelTurn trả về muộn mới.
    await act(async () => {
      cancelDeferred.resolve({ status: "canceled" });
      await cancelPromise;
    });

    expect(result.current.state.status).not.toBe("canceled");
  });

  it("unmount không phát sinh cập nhật state (React cảnh báo)", async () => {
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...a) => {
      errors.push(a[0]);
    });
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(sseResponse())) as unknown as typeof fetch);

    const { unmount } = renderHook(() => useChatStream("c1"));
    await act(async () => {
      unmount();
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(errors.filter((e) => String(e).includes("unmounted"))).toHaveLength(0);
    spy.mockRestore();
  });
});

describe("B6 — active_turn_id từ server phải dùng được", () => {
  it("cancel() dùng được turn đang chạy ở server khi không có stream cục bộ", async () => {
    const cancelSpy = vi.spyOn(chatApi, "cancelTurn").mockResolvedValue({ status: "canceled" });

    const { result } = renderHook(() => useChatStream("c1"));
    // Giả lập server báo có turn đang chạy, client chưa từng stream nó.
    act(() => {
      result.current.setServerActiveTurnId("turn-from-server");
    });

    await act(async () => {
      await result.current.cancel();
    });

    expect(cancelSpy).toHaveBeenCalledWith("c1", "turn-from-server");
  });
});