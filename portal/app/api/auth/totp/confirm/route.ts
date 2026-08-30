import { NextResponse } from "next/server";
import { API_BASE, clearSessionTokens, forwardedIpHeaders, getSessionTokens, setSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/totp/confirm — xác nhận mã 2FA; thành công → cấp JWT + lưu cookie. */
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Body không hợp lệ" }, { status: 400 });
  }

  const { access } = await getSessionTokens();
  const upstream = await fetch(`${API_BASE}/api/auth/totp/confirm`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${access ?? ""}`,
      "Content-Type": "application/json",
      ...forwardedIpHeaders(request),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = (await upstream.json().catch(() => ({}))) as {
    access_token?: string;
    refresh_token?: string;
    detail?: string;
  };
  const response = NextResponse.json(data, { status: upstream.status });
  if (upstream.ok && data.access_token && data.refresh_token) {
    setSessionTokens(response, data.access_token, data.refresh_token);
  } else if (upstream.status === 401) {
    clearSessionTokens(response);
  }
  return response;
}