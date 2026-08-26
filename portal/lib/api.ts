/**
 * API client phía TRÌNH DUYỆT — mọi request đi qua `/api/proxy/...` (BFF),
 * không gọi thẳng backend. Token nằm trong httpOnly cookie, tự động đính kèm.
 */

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function buildQuery(params?: Record<string, string | number | boolean | null | undefined>): string {
  if (!params) return "";
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = `Lỗi ${res.status}`;
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") detail = data.detail;
  } catch {
    // không phải JSON
  }
  return new ApiError(res.status, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get<T>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<T> {
    return request<T>(`${path}${buildQuery(params)}`);
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) });
  },
  delete<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: "DELETE", body: body === undefined ? undefined : JSON.stringify(body) });
  },
};

/** Tải file nhị phân (báo cáo Excel) qua proxy và bấm download. */
export async function downloadFromApi(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
  method: "GET" | "POST" = "GET",
): Promise<void> {
  const res = await fetch(`/api/proxy${path}${buildQuery(params)}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition");
  const match = disposition?.match(/filename="?([^";]+)"?/);
  const filename = match?.[1] ?? "bao-cao.xlsx";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}