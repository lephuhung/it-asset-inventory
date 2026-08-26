import { NextResponse } from "next/server";
import { API_BASE, setSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/login — proxy login, lưu JWT vào httpOnly cookie khi thành công. */
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Body không hợp lệ" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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