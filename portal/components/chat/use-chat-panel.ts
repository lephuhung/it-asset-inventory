"use client";

/**
 * Trạng thái của panel chat + suy ra ngữ cảnh máy từ URL.
 *
 * Ngữ cảnh máy là **mềm**: mở `/machines/<id>` chỉ gợi ý chip "Đang hỏi về: …".
 * Nó KHÔNG tự ghi vào ngữ cảnh đã lưu của hội thoại — muốn ghi thì người dùng
 * phải bấm "Ghim" (xem `chat-context-chip.tsx`).
 */

import { useCallback, useDebugValue, useMemo, useState, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";

export const OPEN_STORAGE_KEY = "chat-rail-open";

/** Bắn khi state trong localStorage đổi (cùng tab) để panel cập nhật ngay. */
const OPEN_CHANGE_EVENT = "chat-rail-open-change";

/** UUID chuẩn — chặn rác trong URL. Chấp nhận mọi version nibble vì backend mới là nguồn sự thật. */
const UUID_SHAPE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const MACHINE_ROUTE = /^\/machines\/([^/]+)\/?$/;

/**
 * Lấy `machine_id` từ pathname, hoặc `null` nếu không ở trang chi tiết máy.
 *
 * Cố tình chỉ chấp nhận đúng một segment UUID sau `/machines/`: nếu lỏng tay,
 * route con (`/machines/<id>/software`) hoặc slug lạ sẽ gửi id rác lên backend.
 */
export function deriveMachineId(pathname: string): string | null {
  if (!pathname) return null;
  // Bỏ query/hash trước khi khớp — pathname từ router không có, nhưng vài
  // call site và test truyền URL đầy đủ.
  const path = pathname.split(/[?#]/, 1)[0];
  const match = MACHINE_ROUTE.exec(path);
  if (!match) return null;
  return UUID_SHAPE.test(match[1]) ? match[1] : null;
}

/** Đọc trạng thái mở/đóng đã lưu; mặc định đóng. Không bao giờ ném lỗi. */
export function readStoredOpen(store: Storage | null | undefined): boolean {
  try {
    return store?.getItem(OPEN_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/** Ghi trạng thái mở/đóng; im lặng bỏ qua nếu storage bị chặn. */
export function writeStoredOpen(store: Storage | null | undefined, open: boolean): void {
  try {
    store?.setItem(OPEN_STORAGE_KEY, open ? "true" : "false");
  } catch {
    // private mode / quota — trạng thái chỉ sống trong phiên hiện tại
  }
}

function setStoredOpen(open: boolean): void {
  writeStoredOpen(window.localStorage, open);
  window.dispatchEvent(new Event(OPEN_CHANGE_EVENT));
}

function subscribeOpen(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(OPEN_CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(OPEN_CHANGE_EVENT, onChange);
  };
}

export interface UseChatPanelResult {
  open: boolean;
  setOpen(open: boolean): void;
  toggle(): void;
  /** machine_id của trang chi tiết máy đang mở, hoặc null. */
  machineId: string | null;
  /** Ngữ cảnh máy áp dụng cho lượt kế tiếp (ghi đè mềm). */
  pendingMachineId: string | null;
  setPendingMachineId(id: string | null): void;
  /** Bỏ ghi đè mềm → quay về machine_id của trang đang mở. */
  clearPendingMachineId(): void;
}

export function useChatPanel(): UseChatPanelResult {
  const pathname = usePathname() ?? "";
  const machineId = useMemo(() => deriveMachineId(pathname), [pathname]);

  // localStorage là nguồn sự thật bên ngoài React → đọc qua
  // useSyncExternalStore thay vì setState trong effect. Server snapshot = false
  // nên render SSR không nháy panel rồi mới tắt, và đồng bị được cả tab khác.
  const open = useSyncExternalStore(
    subscribeOpen,
    () => readStoredOpen(window.localStorage),
    () => false,
  );

  // Ghi đè của người dùng gắn với pathname đã sinh ra nó: điều hướng sang máy
  // khác thì ghi đè tự rụng, tránh hỏi nhầm về một máy không còn mở.
  const [override, setOverride] = useState<{ pathname: string; machineId: string | null }>({
    pathname,
    machineId: null,
  });

  const pendingMachineId = override.pathname === pathname && override.machineId !== null
    ? override.machineId
    : machineId;

  const setOpen = useCallback((next: boolean) => setStoredOpen(next), []);
  const toggle = useCallback(() => setStoredOpen(!readStoredOpen(window.localStorage)), []);

  const setPendingMachineId = useCallback(
    (id: string | null) => setOverride({ pathname, machineId: id }),
    [pathname],
  );
  const clearPendingMachineId = useCallback(
    () => setOverride({ pathname, machineId: null }),
    [pathname],
  );

  useDebugValue(`open=${open} pending=${pendingMachineId ?? "none"}`);

  return {
    open,
    setOpen,
    toggle,
    machineId,
    pendingMachineId,
    setPendingMachineId,
    clearPendingMachineId,
  };
}