/**
 * LogoMark — logo portal (SVG inline, dùng `currentColor` để linh hoạt màu nền).
 *
 * Ý tưởng: màn hình máy tính + đường "pulse/heartbeat" bên trong
 * → "theo dõi tài sản máy tính theo thời gian thực" (đúng bản chất hệ thống
 * agent–server heartbeat của portal).
 *
 * Dùng: sidebar (trắng trên nền brand), trang đăng nhập & enroll (trắng trên
 * nền brand), favicon. Không dùng thư viện icon — SVG tự vẽ, không phụ thuộc.
 */

export function LogoMark({ className = "", size = 20 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {/* Màn hình máy tính */}
      <rect x="2.5" y="3.5" width="19" height="13.5" rx="2.5" />
      {/* Đường heartbeat (pulse) bên trong màn hình */}
      <polyline points="4.5 10.6 8.2 10.6 9.8 8 12.4 13.4 14 10.6 19.5 10.6" />
      {/* Chân đế */}
      <path d="M8.5 20.5h7" />
      <path d="M12 17v3.5" />
    </svg>
  );
}
