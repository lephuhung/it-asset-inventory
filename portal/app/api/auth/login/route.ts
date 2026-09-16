import { NextResponse } from "next/server";
import { API_BASE, forwardedIpHeaders, setSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/login — proxy login, lưu JWT vào httpOnly cookie khi thành công. */
export async function POST(request: Request) {
  // Chống login-CSRF: cross-site POST cũng ghi được httpOnly cookie (SameSite=Lax
  // không chặn Set-Cookie trên response) → attacker có thể ép victim đăng nhập
  // vào tài khoản attacker. Chỉ chấp nhận request same-origin.
  const origin = request.headers.get("origin");
  if (origin) {
    const host =
      request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    try {
      if (new URL(origin).host !== host) {
        return NextResponse.json({ detail: "Origin không hợp lệ" }, { status: 403 });
      }
    } catch {
      return NextResponse.json({ detail: "Origin không hợp lệ" }, { status: 403 });
    }
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Body không hợp lệ" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...forwardedIpHeaders(request) },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const data = (await upstream.json().catch(() => ({}))) as {
    access_token?: string;
    refresh_token?: string;
    requires_2fa?: boolean;
    detail?: string;
  };

  const response = NextResponse.json(data, { status: upstream.status });
  if (upstream.ok && data.access_token && data.refresh_token) {
    setSessionTokens(response, data.access_token, data.refresh_token);
  }
  return response;
}