import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Cho phép HMR WebSocket (`/_next/hmr`) qua địa chỉ LAN khi dev.
  // Next 15.2+ chặn host lạ (chống DNS-rebinding) trừ khi khai báo ở đây.
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    "10.10.0.241",
  ],
};

export default nextConfig;