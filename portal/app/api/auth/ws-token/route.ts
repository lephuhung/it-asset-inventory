import { NextResponse } from "next/server";
import { getSessionTokens } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/auth/ws-token — trả access token cho kết nối WebSocket (backend yêu cầu
 * `?token=` ở query vì trình duyệt không set header trên WS).
 * Access token ngắn hạn (30 phút) nên việc lộ cho JS của chính chúng ta là chấp nhận được;
 * mọi REST API khác vẫn giữ token trong httpOnly cookie.
 */
export async function GET() {
  const { access } = await getSessionTokens();
  if (!access) {
    return NextResponse.json({ detail: "Chưa đăng nhập" }, { status: 401 });
  }
  return NextResponse.json({ token: access });
}