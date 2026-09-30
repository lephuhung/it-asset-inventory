import { NextResponse } from "next/server";
import { API_BASE, forwardedIpHeaders } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Proxy download cho MSI/SHA256/install-offline.ps1 từ server.
 * Server's `/download/*` là public (không cần JWT), nên route này KHÔNG yêu cầu
 * auth cookie — để trình duyệt gọi được trực tiếp từ `<a href>` / `fetch`.
 *
 * Lý do vẫn proxy: tránh CORS khi dev portal (3003) gọi server (8000); giữ 1 host
 * duy nhất phía trình duyệt.
 */
/**
 * Ghép path an toàn từ catch-all segments — chặn path traversal tương tự
 * proxy chính (segment ".." cho phép thoát khỏi prefix `/download/` trên
 * upstream). Route này KHÔNG cần auth cookie nên phải siết chặt hơn nữa.
 */
function upstreamPath(segments: string[]): string | null {
  if (segments.some((s) => s === "" || s === "." || s === "..")) return null;
  return `/download/${segments.map(encodeURIComponent).join("/")}`;
}

async function handle(request: Request, segments: string[]): Promise<Response> {
  const path = upstreamPath(segments);
  if (!path) return new NextResponse("Bad Request", { status: 400 });
  const upstream = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    cache: "no-store",
    headers: forwardedIpHeaders(request),
    // Không kèm Authorization — endpoint upstream public.
  });

  // Chuyển nguyên body + content-type để trình duyệt xử lý đúng (binary/text).
  const headers = new Headers();
  const ct = upstream.headers.get("content-type");
  const cd = upstream.headers.get("content-disposition");
  if (ct) headers.set("content-type", ct);
  if (cd) headers.set("content-disposition", cd);

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  });
}

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  return handle(request, path ?? []);
}
