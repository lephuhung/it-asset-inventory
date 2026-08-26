import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "IT Asset Inventory",
    template: "%s | IT Asset Inventory",
  },
  description: "Hệ thống quản lý tài sản máy tính — dashboard, token triển khai, báo cáo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}