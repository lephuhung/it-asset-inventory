import { NextResponse } from "next/server";
import { API_BASE, getSessionTokens, setSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/refresh — dùng refresh cookie (httpOnly) để lấy cặp JWT mới (rotation). */
export async function POST() {
  const { refresh } = await getSessionTokens();
  if (!refresh) {
    return NextResponse.json({ detail: "Chưa đăng nhập" }, { status: 401 });
  }

  const upstream = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
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
  }
  return response;
}