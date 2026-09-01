/**
 * Helpers phía SERVER (chỉ chạy trong route handlers Next.js — BFF proxy).
 *
 * - Giữ JWT trong httpOnly cookie, trình duyệt không bao giờ đọc được token REST.
 * - Proxy trung gian → backend FastAPI; tự refresh token khi gặp 401 và retry 1 lần.
 * - Trình duyệt chỉ cần cookie/token WS riêng cho kết nối WebSocket.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const API_BASE: string = process.env.API_BASE ?? "http://localhost:8000";

export const ACCESS_COOKIE = "ai_access_token";
export const REFRESH_COOKIE = "ai_refresh_token";

export async function getSessionTokens(): Promise<{ access: string | null; refresh: string | null }> {
  const store = await cookies();
  return {
    access: store.get(ACCESS_COOKIE)?.value ?? null,
    refresh: store.get(REFRESH_COOKIE)?.value ?? null,
  };
}

function cookieOptions(expiresDays?: number) {
  // secure: chỉ true khi chạy sau HTTPS (prod). Dev truy cập qua HTTP → phải false
  // nếu không trình duyệt BỎ cookie → đăng nhập xong vẫn về login.
  // Bật qua env COOKIE_SECURE=1 (khi deploy sau nginx HTTPS).
  const secure = process.env.COOKIE_SECURE === "1" || process.env.COOKIE_SECURE === "true";
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure,
    path: "/",
    ...(expiresDays ? { maxAge: expiresDays * 86400 } : {}),
  };
}

export function setSessionTokens(
  res: NextResponse,
  access: string,
  refresh: string,
  accessExpireMinutes = 30,
  refreshExpireDays = 7,
) {
  res.cookies.set(ACCESS_COOKIE, access, {
    ...cookieOptions(),
    maxAge: accessExpireMinutes * 60,
  });
  res.cookies.set(REFRESH_COOKIE, refresh, cookieOptions(refreshExpireDays));
}

export function clearSessionTokens(res: NextResponse) {
  res.cookies.set(ACCESS_COOKIE, "", { ...cookieOptions(), maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...cookieOptions(), maxAge: 0 });
}

/**
 * Trích xuất headers IP của client từ incoming request, để forward xuống upstream.
 *
 * Backend (FastAPI) sẽ kiểm tra peer (request gửi từ đâu) có thuộc trusted_proxy_cidrs không
 * — mặc định portal + backend cùng host (127.0.0.1/10.10.0.241) → trusted → backend dùng IP
 * từ X-Forwarded-For. Nếu peer không trusted, backend BỎ QUA header (chống spoof).
 *
 * Trả về object rỗng nếu không có header nào (backend sẽ dùng peer IP).
 */
export function forwardedIpHeaders(request: Request): Record<string, string> {
  const out: Record<string, string> = {};
  const xff = request.headers.get("x-forwarded-for");
  const xri = request.headers.get("x-real-ip");
  if (xff) out["X-Forwarded-For"] = xff;
  if (xri) out["X-Real-IP"] = xri;
  return out;
}

/** Gọi upstream FastAPI; trả Response gốc (chưa xử lý refresh). */
export async function fetchUpstream(
  path: string,
  method: string,
  accessToken: string | null,
  body?: BodyInit,
  contentType?: string | null,
  extraHeaders?: Record<string, string>,
) {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (contentType) {
    headers["Content-Type"] = contentType;
  } else if (body !== undefined && typeof body === "string") {
    headers["Content-Type"] = "application/json";
  }
  if (extraHeaders) Object.assign(headers, extraHeaders);

  return fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
    cache: "no-store",
  });
}

/** Refresh token; trả cặp JWT mới hoặc null nếu thất bại. */
export async function refreshTokens(refresh: string): Promise<{ access: string; refresh: string } | null> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { access_token: string; refresh_token: string };
    if (!data.access_token) return null;
    return { access: data.access_token, refresh: data.refresh_token };
  } catch {
    return null;
  }
}

/**
 * Gọi proxy chính: forward request → upstream, tự refresh + retry 1 lần khi 401.
 * Trả NextResponse với cookie mới nếu có refresh. Hỗ trợ response nhị phân (Excel).
 */
export async function proxyRequest(
  request: Request,
  path: string,
  method: string,
  body?: BodyInit,
  contentType?: string | null,
): Promise<NextResponse> {
  // Forward client IP headers — backend dùng để ghi audit log đúng IP user
  // (không phải IP loopback của portal BFF). Backend chỉ tin header nếu peer
  // (chính portal server) thuộc trusted_proxy_cidrs — mặc định đã OK vì
  // Portal + Backend cùng host (10.10.0.241 / 127.0.0.1).
  const extraHeaders: Record<string, string> = {};
  const xff = request.headers.get("x-forwarded-for");
  const xri = request.headers.get("x-real-ip");
  if (xff) extraHeaders["X-Forwarded-For"] = xff;
  if (xri) extraHeaders["X-Real-IP"] = xri;

  const { access, refresh } = await getSessionTokens();
  let res = await fetchUpstream(path, method, access, body, contentType, extraHeaders);
  let newPair: { access: string; refresh: string } | null = null;

  // Access hết hạn → thử refresh một lần, retry request gốc.
  if (res.status === 401 && refresh) {
    newPair = await refreshTokens(refresh);
    if (newPair) {
      res = await fetchUpstream(path, method, newPair.access, body, contentType, extraHeaders);
    }
  }

  const headers = new Headers();
  const respContentType = res.headers.get("content-type");
  if (respContentType) headers.set("content-type", respContentType);
  const disposition = res.headers.get("content-disposition");
  if (disposition) headers.set("content-disposition", disposition);
  headers.set("cache-control", "no-store");

  const isJson = (contentType ?? "").includes("application/json");
  const isBinary = (contentType ?? "").includes("octet-stream") || Boolean(disposition);

  const payload = isBinary ? await res.arrayBuffer() : await res.text();
  // 204/205/304 không được phép kèm body theo HTTP spec → NextResponse cũng throw
  // nếu cố truyền cả status 204 + payload. Chuyển sang null body cho các status này.
  const useNullBody = res.status === 204 || res.status === 205 || res.status === 304;
  const response = new NextResponse(useNullBody ? null : payload, {
    status: res.status,
    headers,
  });

  if (newPair) {
    setSessionTokens(response, newPair.access, newPair.refresh);
  }
  // Nếu không có refresh được và đây là 401 → xóa cookie để client đăng nhập lại.
  if (res.status === 401 && !newPair) {
    clearSessionTokens(response);
  }
  void isJson;
  return response;
}

/** Gọi 1 API có auth (dùng trong route handler), trả JSON đã parse. */
export async function fetchJsonWithAuth<T>(path: string): Promise<{ status: number; data: T | null; detail?: string }> {
  const { access, refresh } = await getSessionTokens();
  let res = await fetchUpstream(path, "GET", access);
  if (res.status === 401 && refresh) {
    const newPair = await refreshTokens(refresh);
    if (newPair) res = await fetchUpstream(path, "GET", newPair.access);
  }
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  if (!isJson) return { status: res.status, data: null };
  const data = (await res.json()) as T;
  if (res.ok) return { status: res.status, data };
  const detail = typeof (data as { detail?: unknown }).detail === "string"
    ? ((data as { detail: string }).detail)
    : undefined;
  return { status: res.status, data: null, detail };
}

/**
 * Variant của `fetchJsonWithAuth` có kèm forwarded IP headers — dùng cho các route
 * handler có `request` để truyền IP user xuống backend (ghi audit log).
 */
export async function fetchJsonWithAuthAndIp<T>(
  path: string,
  request: Request,
): Promise<{ status: number; data: T | null; detail?: string }> {
  const { access, refresh } = await getSessionTokens();
  const extra = forwardedIpHeaders(request);
  let res = await fetchUpstream(path, "GET", access, undefined, undefined, extra);
  if (res.status === 401 && refresh) {
    const newPair = await refreshTokens(refresh);
    if (newPair) res = await fetchUpstream(path, "GET", newPair.access, undefined, undefined, extra);
  }
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  if (!isJson) return { status: res.status, data: null };
  const data = (await res.json()) as T;
  if (res.ok) return { status: res.status, data };
  const detail = typeof (data as { detail?: unknown }).detail === "string"
    ? ((data as { detail: string }).detail)
    : undefined;
  return { status: res.status, data: null, detail };
}