import { NextResponse } from "next/server";
import { API_BASE, clearSessionTokens, getSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/auth/logout — xóa cookie phiên + báo backend (audit logout). */
export async function POST() {
  const { access } = await getSessionTokens();
  if (access) {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access}` },
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