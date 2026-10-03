/**
 * Proxy SSE dành riêng cho Chat Assistant.
 *
 * Vì sao không dùng `/api/proxy` (BFF chung)? Route đó đọc hết body rồi mới
 * trả về (`res.text()`), tức là **buffer toàn bộ** — token sẽ bị gom lại hết
 * rồi mới hiện, mất hẳn cảm giác streaming. Route này giữ nguyên
 * `ReadableStream` của upstream và chuyển thẳng xuống client.
 *
 * Hợp đồng với backend (spec §"Hợp đồng API" L292):
 *   `POST {API_BASE}/api/chat/conversations/{id}/messages`
 *   → body `{content, machine_context?}`, header `Idempotency-Key`, trả `text/event-stream`.
 *
 * Xem `docs/superpowers/plans/2026-10-02-p2-portal-contract-decisions.md` (D1, D5).
 */

import { NextResponse } from "next/server";
import {
  API_BASE,
  clearSessionTokens,
  forwardedIpHeaders,
  getSessionTokens,
  refreshTokens,
  setSessionTokens,
} from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Trần thời gian cho một lượt chat (LLM chậm + nhiều tool vẫn phải kịp). */
const STREAM_TIMEOUT_MS = 360_000;

interface ChatStreamRequest {
  conversation_id?: unknown;
  content?: unknown;
  machine_context?: unknown;
  idempotency_key?: unknown;
}

function errorBody(category: string, hint: string, httpStatus?: number) {
  return { category, hint, ...(httpStatus ? { http_status: httpStatus } : {}) };
}

async function jsonError(
  status: number,
  category: string,
  hint: string,
  httpStatus?: number,
  newPair?: { access: string; refresh: string } | null,
) {
  const response = new NextResponse(JSON.stringify(errorBody(category, hint, httpStatus)), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
  // Token đã refresh xong mà response này vẫn phải mang cookie mới, nếu không
  // browser giữ token cũ đã bị thu hồi (rotation) → mọi request sau đều 401.
  if (newPair) setSessionTokens(response, newPair.access, newPair.refresh);
  return response;
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

async function fetchUpstreamStream(args: {
  path: string;
  access: string | null;
  body: string;
  idempotencyKey: string | null;
  extraHeaders: Record<string, string>;
  signal: AbortSignal;
}) {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "text/event-stream",
    ...(args.access ? { authorization: `Bearer ${args.access}` } : {}),
    ...(args.idempotencyKey ? { "Idempotency-Key": args.idempotencyKey } : {}),
    ...args.extraHeaders,
  };
  return fetch(`${API_BASE}${args.path}`, {
    method: "POST",
    headers,
    body: args.body,
    cache: "no-store",
    redirect: "manual",
    signal: args.signal,
  });
}

export async function POST(request: Request) {
  let payload: ChatStreamRequest;
  try {
    payload = (await request.json()) as ChatStreamRequest;
  } catch {
    return jsonError(400, "chat_validation", "Body phải là JSON hợp lệ.");
  }
  // `null` là JSON hợp lệ nhưng không phải object → phải chặn trước khi đọc thuộc tính.
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return jsonError(400, "chat_validation", "Body phải là một JSON object.");
  }

  if (!isNonEmptyString(payload.conversation_id)) {
    return jsonError(400, "chat_validation", "Thiếu conversation_id.");
  }
  if (!isNonEmptyString(payload.content)) {
    return jsonError(400, "chat_validation", "Nội dung tin nhắn không được rỗng.");
  }
  if (
    payload.machine_context !== undefined &&
    payload.machine_context !== null &&
    !(typeof payload.machine_context === "object" && isNonEmptyString((payload.machine_context as { machine_id?: unknown }).machine_id))
  ) {
    return jsonError(400, "chat_validation", "machine_context phải có machine_id.");
  }
  if (payload.idempotency_key !== undefined && payload.idempotency_key !== null && typeof payload.idempotency_key !== "string") {
    return jsonError(400, "chat_validation", "idempotency_key phải là chuỗi.");
  }

  // `conversation_id` chỉ dùng để dựng path; `Idempotency-Key` đi qua header (D1).
  // D2: chỉ chuyển tiếp `machine_id` + `hostname`; bỏ mọi trường lạ (vd `client_id`
  // do client tự khai) vì đó là việc của backend phải tự resolve.
  const upstreamBody: Record<string, unknown> = { content: payload.content };
  if (payload.machine_context) {
    const ctx = payload.machine_context as { machine_id: string; hostname?: unknown };
    upstreamBody.machine_context = {
      machine_id: ctx.machine_id,
      ...(typeof ctx.hostname === "string" ? { hostname: ctx.hostname } : {}),
    };
  }
  const body = JSON.stringify(upstreamBody);

  const idempotencyKey = isNonEmptyString(payload.idempotency_key) ? payload.idempotency_key : null;
  const path = `/api/chat/conversations/${encodeURIComponent(payload.conversation_id)}/messages`;
  const extraHeaders = forwardedIpHeaders(request);

  // Ngắt khi client đóng tab (abort) hoặc hết trần thời gian.
  const signal = AbortSignal.any([request.signal, AbortSignal.timeout(STREAM_TIMEOUT_MS)]);

  const { access, refresh } = await getSessionTokens();

  let res: Response;
  try {
    res = await fetchUpstreamStream({ path, access, body, idempotencyKey, extraHeaders, signal });
  } catch {
    return jsonError(502, "chat_upstream_llm", "Không kết nối được tới dịch vụ chat.", 502);
  }

  // Access token hết hạn → refresh rồi thử lại ĐÚNG MỘT LẦN (chưa có byte nào
  // nào về client nên retry ở đây vẫn an toàn).
  let newPair: { access: string; refresh: string } | null = null;
  if (res.status === 401 && refresh) {
    newPair = await refreshTokens(refresh);
    if (newPair) {
      // Thả body 401 cũ: không dùng nữa, không nên giữ connection mở.
      void res.body?.cancel().catch(() => undefined);
      try {
        res = await fetchUpstreamStream({
          path,
          access: newPair.access,
          body,
          idempotencyKey,
          extraHeaders,
          signal,
        });
      } catch {
        return jsonError(502, "chat_upstream_llm", "Không kết nối được tới dịch vụ chat.", 502, newPair);
      }
    }
  }

  const contentType = res.headers.get("content-type") ?? "";
  const isEventStream = contentType.includes("text/event-stream");

  // Lỗi TRƯỚC khi stream bắt đầu → trả nguyên JSON của backend (spec L392),
  // không bịa ra một stream rỗng để client tưởng đang chờ token.
  if (!isEventStream) {
    // `res.text()` cũng có thể ném (đọc body lỗi / client ngắt) — phải trả
    // cookie đã refresh, không thì browser giữ token cũ đã bị thu hồi.
    let text: string;
    try {
      text = await res.text();
    } catch {
      return jsonError(502, "chat_upstream_llm", "Dịch vụ chat trả về lỗi không đọc được.", 502, newPair);
    }
    const headers = new Headers({ "cache-control": "no-store" });
    if (contentType) headers.set("content-type", contentType);
    else headers.set("content-type", "application/json");
    const response = new NextResponse(text, { status: res.status, headers });
    if (newPair) setSessionTokens(response, newPair.access, newPair.refresh);
    if (res.status === 401 && !newPair) clearSessionTokens(response);
    return response;
  }

  if (!res.body) {
    return jsonError(502, "chat_internal", "Dịch vụ chat không trả về nội dung stream.", 502, newPair);
  }

  const response = new NextResponse(res.body, {
    status: res.status,
    headers: {
      "content-type": "text/event-stream",
      // no-transform: chặn proxy/compressor biến stream thành buffer.
      "cache-control": "no-store, no-transform",
      connection: "keep-alive",
      // nginx dừng buffer ở đây, nếu không token sẽ đến theo cả cục.
      "x-accel-buffering": "no",
    },
  });

  if (newPair) setSessionTokens(response, newPair.access, newPair.refresh);
  // Từ đây stream đã chạy: KHÔNG retry, KHÔNG tự gọi lại (spec D5).
  return response;
}