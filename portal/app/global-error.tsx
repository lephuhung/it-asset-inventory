"use client";

/**
 * Global error boundary — Next.js render dùng khi unhandled error trong route handlers.
 *
 * Phải đặt ở `app/global-error.tsx` (KHÔNG phải app/error.tsx) để Next.js dùng nó
 * thay cho auto-generated `/_global-error` (vống fallback vào React internal +
 * useContext mà thiếu AuthProvider → "Cannot read properties of null").
 *
 * KHÔNG import AuthContext, useAuth, hay bất kỳ client provider nào — page này
 * phải render được trong mọi trạng thái, kể cả khi session lỗi. Layout cũng
 * không wrap được (Next.js 16 wrapper layout cho _global-error khác route groups).
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="vi">
      <body>
        <div style={{
          display: "flex",
          minHeight: "100vh",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1.5rem",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600, color: "#0f172a" }}>
            Đã xảy ra lỗi không mong muốn
          </h1>
          <p style={{ color: "#64748b", maxWidth: "32rem", textAlign: "center" }}>
            Vui lòng thử lại hoặc liên hệ quản trị viên nếu lỗi tiếp tục.
            {error.digest && (
              <code style={{
                display: "block",
                marginTop: "0.5rem",
                fontSize: "0.75rem",
                color: "#94a3b8",
              }}>
                digest: {error.digest}
              </code>
            )}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              padding: "0.5rem 1rem",
              background: "#2563eb",
              color: "white",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
              fontSize: "0.875rem",
            }}
          >
            Thử lại
          </button>
        </div>
      </body>
    </html>
  );
}
