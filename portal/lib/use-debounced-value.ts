"use client";

import { useEffect, useState } from "react";

/**
 * Trả về giá trị đã debounced sau `delayMs` kể từ lần thay đổi cuối cùng.
 *
 * Dùng cho input gõ phím kích hoạt request mạng: chỉ phát giá trị ổn định
 * sau khi user ngừng gõ, kết hợp `AbortController` ở consumer để hủy
 * request cũ.
 *
 * Không tốn thêm dependency — chỉ dùng hook chuẩn của React.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
