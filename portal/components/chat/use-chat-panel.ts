"use client";

/**
 * Trạng thái của panel chat + suy ra ngữ cảnh máy từ URL.
 *
 * Ngữ cảnh máy là **mềm**: mở `/machines/<id>` chỉ gợi ý chip "Đang hỏi về: …".
 * Nó KHÔNG tự ghi vào ngữ cảnh đã lưu của hội thoại — muốn ghi thì người dùng
 * phải bấm "Ghim" (xem Task 8 / `chat-context-chip.tsx`).
 */

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";

export const OPEN_STORAGE_KEY = "chat-rail-open";

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
  // Bỏ query/hash trước khi khớp — pathname từ router không có, nhưng test
  // và vài call site truyền URL đầy đủ.
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

export interface UseChatPanelResult {
  /** `null` ở render đầu (SSR) cho tới khi đọc được localStorage. */
  open: boolean;
  setOpen(open: boolean): void;
  toggle(): void;
  /** machine_id của trang chi tiết máy đang mở, hoặc null. */
  machineId: string | null;
  /** Ngữ cảnh máy áp dụng cho lượt tiếp theo (ghi đè mềm). */
  pendingMachineId: string | null;
  setPendingMachineId(id: string | null): void;
  /** Bỏ ghi đè mềm → quay về machine_id đã lưu của hội thoại. */
  clearPendingMachineId(): void;
}

export function useChatPanel(): UseChatPanelResult {
  const pathname = usePathname();
  const [open, setOpenState] = useState(false);
  // Đã hydrate từ localStorage chưa — tránh render nháy panel rồi mới tắt.
  const [hydrated, setHydrated] = useState(false);
  const [pendingMachineId, setPendingMachineIdState] = useState<string | null>(null);

  const machineId = deriveMachineId(pathname ?? "");

  useEffect(() => {
    setOpenState(readStoredOpen(window.localStorage));
    setHydrated(true);
  }, []);

  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
    writeStoredOpen(window.localStorage, next);
  }, []);

  const toggle = useCallback(() => {
    setOpenState((prev) => {
      writeStoredOpen(window.localStorage, !prev);
      return !prev;
    });
  }, []);

  const setPendingMachineId = useCallback((id: string | null) => {
    setPendingMachineIdState(id);
  }, []);

  const clearPendingMachineId = useCallback(() => setPendingMachineIdState(null), []);

  // Điều hướng sang trang chi tiết máy → gợi ý máy đó cho lượt kế tiếp.
  // Điều hướng ra khỏi trang máy → bỏ gợi ý (đừng giữ mã máy cũ).
  useEffect(() => {
    if (!hydrated) return;
    setPendingMachineIdState(machineId);
  }, [machineId, hydrated]);

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