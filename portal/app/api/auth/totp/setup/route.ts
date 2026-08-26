import { NextResponse } from "next/server";
import { API_BASE, getSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/totp/setup — proxy sang backend (admin only). */
export async function POST() {
  const { access } = await getSessionTokens();
  const upstream = await fetch(`${API_BASE}/api/auth/totp/setup`, {
    method: "POST",
    headers: { Authorization: `Bearer ${access ?? ""}` },
    cache: "no-store",
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}