import { NextResponse } from "next/server";
import { API_BASE, clearSessionTokens, forwardedIpHeaders, getSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/logout — xóa cookie phiên + báo backend (audit logout). */
export async function POST(request: Request) {
  const { access } = await getSessionTokens();
  if (access) {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access}`, ...forwardedIpHeaders(request) },
        cache: "no-store",
      });
    } catch {
      // backend không reachable — vẫn xóa cookie cục bộ
    }
  }
  const response = NextResponse.json({ ok: true });
  clearSessionTokens(response);
  return response;
}