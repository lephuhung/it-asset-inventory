import type { NextConfig } from "next";

const apiBase = process.env.API_BASE ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Cho phép HMR WebSocket (`/_next/hmr`) qua địa chỉ LAN khi dev.
  // Next 15.2+ chặn host lạ (chống DNS-rebinding) trừ khi khai báo ở đây.
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    "10.10.0.241",
  ],
  // install.ps1 sinh bởi server nhúng `$baseUrl = portal_url` (VD http://10.10.0.241:3003)
  // và tải MSI từ `$baseUrl/download/agent.msi`, còn lệnh cài là `irm <portal>/i/<token> | iex`.
  // Cả 2 đường này chỉ tồn tại ở API server (FastAPI), nên portal phải proxy sang đó —
  // nếu không `irm` và bước tải MSI đều dính 404 (xem server/app/api/routes/install.py,
  // downloads.py và template install.ps1.j2).
  async rewrites() {
    return [
      // irm http://<portal>/i/<token> | iex → render install.ps1
      { source: "/i/:token", destination: `${apiBase}/i/:token` },
      // install.ps1: $msiUrl = $baseUrl/download/agent.msi (+ .sha256, install-offline.*)
      { source: "/download/:path*", destination: `${apiBase}/download/:path*` },
    ];
  },
};

export default nextConfig;