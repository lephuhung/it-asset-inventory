import { NextResponse } from "next/server";
import { fetchJsonWithAuthAndIp } from "@/lib/backend";
import type { SessionUser } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/auth/session — user hiện tại (dùng cho auth guard phía client). */
export async function GET(request: Request) {
  const { status, data } = await fetchJsonWithAuthAndIp<SessionUser>("/api/auth/me", request);
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