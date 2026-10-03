"use client";

/**
 * Client SSE cho Chat Assistant.
 *
 * Vì sao không dùng `EventSource`? EventSource chỉ GET và không cho set header
 * (`Idempotency-Key`), còn lượt chat là POST có body. Nên ở đây dùng
 * `fetch` + `ReadableStream` và tự tách frame (parse SSE).
 *
 * Phần lõi nằm ở hai hàm thuần `parseSseFrame` / `reduceEvent` và một hàm
 * `runChatStream` không phụ thuộc React — nhờ vậy test được chạy bằng vitest ở
 * môi trường node, không cần jsdom.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "@/lib/chat";
import type {
  ChatErrorCategory,
  ChatMachineContext,
  ChatSseEvent,
  ChatToolCall,
} from "@/lib/types";

export interface ChatStreamError {
  category: ChatErrorCategory;
  hint: string;
  retryable: boolean;
  httpStatus?: number;
}

export type ChatStreamStatus = "idle" | "streaming" | "done" | "canceled" | "error";

export interface ChatStreamState {
  turnId: string | null;
  messageId: string | null;
  content: string;
  tools: ChatToolCall[];
  status: ChatStreamStatus;
  finishReason: string | null;
  usage: { input_tokens: number; output_tokens: number } | null;
  error: ChatStreamError | null;
  /** `seq` cao nhất đã xử lý — dùng để bỏ event đơn điệu bị lặp/nhảy về. */
  seq: number;
}

export function initialStreamState(): ChatStreamState {
  return {
    turnId: null,
    messageId: null,
    content: "",
    tools: [],
    status: "idle",
    finishReason: null,
    usage: null,
    error: null,
    // Spec chỉ yêu cầu `seq` đơn điệu, KHÔNG nói bắt đầu từ 1. Mốc -Infinity
    // để event đầu tiên dù seq 0 hay 1 đều được nhận; không đoán trước quy ước.
    seq: Number.NEGATIVE_INFINITY,
  };
}

/**
 * Tách một frame SSE ra object event.
 *
 * Frame heartbeat (`:hb`) và JSON hỏng trả `null` — client bỏ qua thay vì làm
 * sập cả stream. `data:` nhiều dòng được nối lại theo chuẩn SSE.
 */
export function parseSseFrame(frame: string): ChatSseEvent | null {
  const lines = frame.split(/\r?\n/);
  const dataLines: string[] = [];
  let eventName: string | null = null;

  for (const line of lines) {
    if (line.startsWith(":")) continue; // comment / heartbeat
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    } else if (line.startsWith("event:")) {
      eventName = line.slice(6).replace(/^ /, "");
    }
  }

  if (dataLines.length === 0) return null;
  const raw = dataLines.join("\n");
  if (!raw.trim()) return null;

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }

  // Payload luôn mang `type`; event name chỉ là dự phòng.
  const type = (parsed.type as ChatSseEvent["type"] | undefined) ?? (eventName as ChatSseEvent["type"] | undefined);
  if (!type) return null;
  return { ...parsed, type } as ChatSseEvent;
}

/** Áp một event vào state, trả về state MỚI (không mutate input). */
export function reduceEvent(state: ChatStreamState, event: ChatSseEvent): ChatStreamState {
  const seq = typeof event.seq === "number" ? event.seq : state.seq;
  // `seq` đơn diệu: event trùng hoặc nhảy ngược là replay → bỏ.
  if (seq <= state.seq) return state;

  switch (event.type) {
    case "start":
      return {
        ...state,
        seq,
        turnId: event.turn_id,
        messageId: event.message_id,
        status: "streaming",
      };

    case "token":
      return { ...state, seq, status: "streaming", content: state.content + event.text };

    case "tool_start": {
      if (state.tools.some((t) => t.tool_call_id === event.tool_call_id)) return { ...state, seq };
      const tool: ChatToolCall = {
        tool_call_id: event.tool_call_id,
        tool: event.tool,
        ok: null,
        row_count: null,
        byte_count: null,
        duration_ms: null,
        client_id: null,
        flow_id: null,
        error_category: null,
      };
      return { ...state, seq, tools: [...state.tools, tool] };
    }

    case "tool_result": {
      const patch = {
        ok: event.ok ?? null,
        row_count: event.row_count ?? null,
        byte_count: event.byte_count ?? null,
        duration_ms: event.duration_ms ?? null,
        client_id: event.client_id ?? null,
        flow_id: event.flow_id ?? null,
        error_category: event.error_category ?? null,
      };
      const existing = state.tools.find((t) => t.tool_call_id === event.tool_call_id);
      // tool_result về trước tool_start → tạo entry mới, không bị bỏ rơi.
      const tools = existing
        ? state.tools.map((t) => (t.tool_call_id === event.tool_call_id ? { ...t, ...patch } : t))
        : [
            ...state.tools,
            { tool_call_id: event.tool_call_id, tool: "", ...patch } as ChatToolCall,
          ];
      return { ...state, seq, tools };
    }

    case "usage":
      return {
        ...state,
        seq,
        usage: { input_tokens: event.input_tokens, output_tokens: event.output_tokens },
      };

    case "done":
      return {
        ...state,
        seq,
        messageId: event.message_id,
        finishReason: event.finish_reason,
        status:
          event.finish_reason === "canceled"
            ? "canceled"
            : event.finish_reason === "error"
              ? "error"
              : "done",
      };

    case "error":
      return {
        ...state,
        seq,
        status: "error",
        error: {
          category: event.category,
          hint: event.hint,
          retryable: event.retryable,
          ...(event.http_status !== undefined ? { httpStatus: event.http_status } : {}),
        },
      };

    default:
      return { ...state, seq };
  }
}

export interface RunChatStreamArgs {
  conversationId: string;
  content: string;
  machineContext?: ChatMachineContext | null;
  idempotencyKey?: string;
  signal?: AbortSignal;
  onState?: (state: ChatStreamState) => void;
  fetchImpl?: typeof fetch;
}

/** Người dùng bấm Dừng (abort có chủ ý) ≠ mất kết nối. */
function isAbort(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  return error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError");
}

const FRAME_SEPARATOR = /\r?\n\r?\n/;

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/**
 * Chạy một lượt chat và trả về state cuối. Không dùng React nên test được trực tiếp.
 *
 * - `signal` được truyền thẳng vào `fetch` (nút Dừng abort được cả request).
 * - Hết stream mà không có event `done` → `chat_stream_lost`; nếu người dùng đã
 *   bấm Dừng thì đó là hủy, không phải lỗi.
 */
export async function runChatStream(args: RunChatStreamArgs): Promise<ChatStreamState> {
  const doFetch = args.fetchImpl ?? fetch;
  const idempotencyKey = args.idempotencyKey ?? uuid();

  const body: Record<string, unknown> = {
    conversation_id: args.conversationId,
    content: args.content,
    idempotency_key: idempotencyKey,
  };
  if (args.machineContext) body.machine_context = args.machineContext;

  const init: RequestInit = {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
    ...(args.signal ? { signal: args.signal } : {}),
  };

  let res: Response;
  try {
    res = await doFetch("/api/chat/stream", init);
  } catch (error) {
    // Bấm Dừng trước khi có header ⇒ fetch reject AbortError. Đây KHÔNG phải
    // lỗi mạng — báo "canceled" để không dọi người dùng gọi cứu.
    if (isAbort(error, args.signal)) {
      const canceled: ChatStreamState = { ...initialStreamState(), status: "canceled" };
      args.onState?.(canceled);
      return canceled;
    }
    const failed: ChatStreamState = {
      ...initialStreamState(),
      status: "error",
      error: {
        category: "chat_internal",
        hint: "Không gửi được câu hỏi. Kiểm tra kết nối rồi thử lại.",
        retryable: true,
      },
    };
    args.onState?.(failed);
    return failed;
  }

  // Lỗi TRƯỚC khi stream bắt đầu: backend trả JSON kèm `category`.
  const contentType = res.headers.get("content-type") ?? "";
  if (!res.ok || !contentType.includes("text/event-stream")) {
    // Đọc `hint`/`retryable` nếu backend có gửi (spec error format). Nếu không
    // thì fallback sang câu chữ mặc định — không đoán bừa.
    let category: ChatErrorCategory = "chat_internal";
    let hint = "";
    let retryable = res.status >= 500;
    try {
      const data = (await res.json()) as {
        category?: string;
        detail?: string;
        hint?: string;
        retryable?: boolean;
      };
      if (typeof data.category === "string") category = data.category as ChatErrorCategory;
      if (typeof data.hint === "string") hint = data.hint;
      else if (typeof data.detail === "string") hint = data.detail;
      if (typeof data.retryable === "boolean") retryable = data.retryable;
    } catch {
      // không phải JSON → giữ giá trị mặc định
    }
    if (!hint) hint = `Dịch vụ chat trả về lỗi ${res.status}.`;
    const failed: ChatStreamState = {
      ...initialStreamState(),
      status: "error",
      error: { category, hint, retryable, httpStatus: res.status },
    };
    args.onState?.(failed);
    return failed;
  }

  if (!res.body) {
    const failed: ChatStreamState = {
      ...initialStreamState(),
      status: "error",
      error: { category: "chat_internal", hint: "Dịch vụ chat không trả về nội dung.", retryable: true },
    };
    args.onState?.(failed);
    return failed;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let state = initialStreamState();
  let buffer = "";

  const dispatch = (raw: string) => {
    const event = parseSseFrame(raw);
    if (!event) return;
    const next = reduceEvent(state, event);
    if (next !== state) {
      state = next;
      args.onState?.(state);
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let match: RegExpExecArray | null;
      while ((match = FRAME_SEPARATOR.exec(buffer)) !== null) {
        const raw = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        if (raw.trim()) dispatch(raw);
      }
    }
    // Frame cuối có thể không kịp nhận dòng trống phía sau.
    if (buffer.trim()) dispatch(buffer);
  } catch (error) {
    // Bấm Dừng giữa chừng ⇒ reader.read() ném AbortError. Giữ nguyên phần text đã
    // nhận và báo "canceled" — không phải mất kết nối.
    if (isAbort(error, args.signal)) {
      const canceled: ChatStreamState = { ...state, status: "canceled", error: null };
      args.onState?.(canceled);
      return canceled;
    }
    // Mất kết nối thật: giữ phần text đã nhận, báo mất stream.
    const interrupted: ChatStreamState = {
      ...state,
      status: "error",
      error: {
        category: "chat_stream_lost",
        hint: "Kết nối tới dịch vụ chat bị gián đoạn.",
        retryable: true,
      },
    };
    args.onState?.(interrupted);
    return interrupted;
  } finally {
    reader.releaseLock?.();
  }

  if (state.status === "streaming" || state.status === "idle") {
    // Không có `done`: hoặc người dùng bấm Dừng, hoặc stream đứt.
    const aborted = args.signal?.aborted ?? false;
    const final: ChatStreamState = aborted
      ? { ...state, status: "canceled", error: null }
      : {
          ...state,
          status: "error",
          error: {
            category: "chat_stream_lost",
            hint: "Luồng trả lời kết thúc bất thường.",
            retryable: true,
          },
        };
    args.onState?.(final);
    return final;
  }

  return state;
}

export interface UseChatStreamResult {
  state: ChatStreamState;
  streaming: boolean;
  /** Turn đang chạy ở SERVER (mở lại hội thoại cũ) — chưa từng stream cục bộ. */
  serverActiveTurnId: string | null;
  setServerActiveTurnId(turnId: string | null): void;
  /** Có turn nào đang chạy (cục bộ hoặc server) không → khoá nút Gửi. */
  hasActiveTurn: boolean;
  send(
    content: string,
    options?: { machineContext?: ChatMachineContext | null; conversationId?: string | null },
  ): Promise<void>;
  cancel(): Promise<void>;
  reset(): void;
}

/**
 * `generation` tăng mỗi lần bắt đầu stream MỚI hoặc `reset()`.
 *
 * Mọi callback của một request cũ đều so với generation đã chụp; lệch ⇒ request
 * đó đã bị thay thế ⇒ im lặng bỏ qua. Đây là chốt chặn race: nếu không có nó,
 * stream của hội thoại A abort về sau có thể hồi sinh nội dung đè lên B.
 */
export function useChatStream(conversationId: string | null): UseChatStreamResult {
  const [state, setState] = useState<ChatStreamState>(initialStreamState);
  const [serverActiveTurnId, setServerActiveTurnId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  // Ref (không state) để cancel luôn đọc được turn hiện tại: đọc qua state sẽ
  // kẹt closure cũ nếu setServerActiveTurnId vừa xong chưa kịp render lại.
  const serverTurnRef = useRef<string | null>(null);
  serverTurnRef.current = serverActiveTurnId;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Unmount: vô hiệu hoá mọi callback đang bay + huỷ request.
      generationRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const reset = useCallback(() => {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    if (mountedRef.current) setState(initialStreamState());
  }, []);

  const send = useCallback(
    async (
      content: string,
      options?: { machineContext?: ChatMachineContext | null; conversationId?: string | null },
    ) => {
      // `conversationId` truyền vào thắng biến đã chụp: khi rail vừa tạo hội
      // thoại mới, callback của render cũ vẫn giữ `null` và sẽ âm thầm bỏ câu hỏi.
      const target = options?.conversationId ?? conversationId;
      if (!target || !content.trim()) return;

      generationRef.current += 1;
      const generation = generationRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setState({ ...initialStreamState(), status: "streaming" });
      await runChatStream({
        conversationId: target,
        content,
        machineContext: options?.machineContext ?? null,
        signal: controller.signal,
        onState: (next) => {
          // Request đã bị thay thế / component unmount → bỏ qua im lặng.
          if (generationRef.current !== generation || !mountedRef.current) return;
          setState(next);
        },
      });
      if (abortRef.current === controller) abortRef.current = null;
    },
    [conversationId],
  );

  const cancel = useCallback(async () => {
    generationRef.current += 1;
    const generation = generationRef.current;
    abortRef.current?.abort();
    abortRef.current = null;

    // Ưu tiên turn từ stream cục bộ, không có thì dùng turn server đang báo.
    const turnId = state.turnId ?? serverTurnRef.current;
    if (conversationId && turnId) {
      // Server vẫn cần biết để chuyển turn sang `canceled` và hoàn tất ngân sách.
      await chatApi.cancelTurn(conversationId, turnId).catch(() => undefined);
    }
    // Trong lúc chờ, người dùng có thể đã gửi câu mới → không ghi đè state đó.
    if (generationRef.current !== generation || !mountedRef.current) return;
    setState((prev) => ({ ...prev, status: "canceled", error: null }));
    setServerActiveTurnId(null);
  }, [conversationId, state.turnId]);

  return {
    state,
    streaming: state.status === "streaming",
    serverActiveTurnId,
    setServerActiveTurnId,
    hasActiveTurn: state.status === "streaming" || serverActiveTurnId !== null,
    send,
    cancel,
    reset,
  };
}

export type { ChatSseEvent, ChatToolCall };