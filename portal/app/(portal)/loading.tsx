import { Spinner } from "@/components/ui";

/**
 * Loading UI cấp route group — hiện trong lúc Next.js nạp segment khi điều
 * hướng, thay cho khoảng trắng trống trước đây (các trang đều là client
 * component nên tự có spinner riêng sau khi mount; file này phủ khoảng lặng
 * giữa hai lần render).
 */
export default function PortalLoading() {
  return <Spinner label="Đang tải trang…" />;
}
