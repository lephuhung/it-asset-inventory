import { NextResponse } from "next/server";
import { fetchJsonWithAuth } from "@/lib/backend";
import type { SessionUser } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/auth/session — user hiện tại (dùng cho auth guard phía client). */
export async function GET() {
  const { status, data } = await fetchJsonWithAuth<SessionUser>("/api/auth/me");
  if (status === 200 && data) {
    return NextResponse.json({ user: data });
  }
  if (status === 401) {
    return NextResponse.json({ user: null }, { status: 401 });
  }
  return NextResponse.json(
    { user: null, detail: "Không lấy được thông tin phiên" },
    { status },
  );
}