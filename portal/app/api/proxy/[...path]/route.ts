import { NextResponse } from "next/server";
import { proxyRequest } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Proxy tổng BFF: `/api/proxy/[...path]` → `{API_BASE}/api/[...path]`.
 * Mọi request từ trình duyệt đi qua đây (đã đính httpOnly cookie).
 * Hỗ trợ tự refresh access token và truyền qua response nhị phân (Excel).
 */

/**
 * Ghép path an toàn từ catch-all segments. Segments đã bị decode → một segment
 * ".." (từ URL dạng `%2e%2e`) sẽ cho request thoát khỏi prefix `/api/` trên
 * upstream sau khi fetch normalize. Chặn ".." và encode lại từng segment.
 */
function upstreamPath(segments: string[]): string | null {
  if (segments.some((s) => s === "" || s === "." || s === "..")) return null;
  return `/api/${segments.map(encodeURIComponent).join("/")}`;
}

async function handle(request: Request, segments: string[], method: string) {
  const base = upstreamPath(segments);
  if (!base) return new NextResponse("Bad Request", { status: 400 });
  const search = new URL(request.url).search;
  let body: BodyInit | undefined;
  const contentType = request.headers.get("content-type");

  if (method !== "GET" && method !== "HEAD") {
    if (contentType && contentType.includes("multipart/form-data")) {
      body = await request.arrayBuffer();
    } else {
      body = await request.text();
    }
  }
  return proxyRequest(request, `${base}${search}`, method, body || undefined, contentType);
}

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handle(request, path ?? [], "GET");
}

export async function POST(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handle(request, path ?? [], "POST");
}

export async function PUT(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handle(request, path ?? [], "PUT");
}

export async function PATCH(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handle(request, path ?? [], "PATCH");
}

export async function DELETE(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handle(request, path ?? [], "DELETE");
}