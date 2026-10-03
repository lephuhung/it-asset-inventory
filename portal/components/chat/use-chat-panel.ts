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

/**
 * Lấy localStorage an toàn: jsdom, private mode, hay một getter bị chặn đều không
 * được làm sập component.
 */
function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Đọc trạng thái mở/đóng đã lưu; mặc định đóng. Không bao giờ ném lỗi. */
export function readStoredOpen(store: Storage | null | undefined): boolean {
  try {
    return store?.getItem(OPEN_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/**
 * Ghi trạng thái mở/đóng. Nếu storage bị chặn/quota đầy, giữ trong bộ nhớ để rail
 * vẫn dùng được trong phiên (thay vì bấm mở không ăn).
 */
let memoryFallbackOpen = false;
export function writeStoredOpen(store: Storage | null | undefined, open: boolean): void {
  try {
    if (store) {
      store.setItem(OPEN_STORAGE_KEY, open ? "true" : "false");
      return;
    }
  } catch {
    // rơi xuống bộ nhớ
  }
  memoryFallbackOpen = open;
}

/** Đọc trạng thái mở/đóng, kể cả khi phải dùng bộ nhớ. */
export function currentOpen(): boolean {
  const store = safeStorage();
  if (store) {
    const stored = readStoredOpen(store);
    if (stored || store.getItem(OPEN_STORAGE_KEY) === "false") return stored;
  }
  return memoryFallbackOpen;
}

function setStoredOpen(open: boolean): void {
  writeStoredOpen(safeStorage(), open);
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
  /**
   * Bỏ ghi đè mềm → quay về `machine_id` đã lưu của hội thoại.
   * Khác `setPendingMachineId(null)`: lệnh này **chặn** luôn ngữ cảnh của trang,
   * nên bấm “Gỡ” thật sự gỡ được (trước đây null bị hiểu là “lùi về máy của URL”).
   */
  clearPendingMachineId(): void;
  /**
   * Bỏ ghi đè cũ khi chuyển hội thoại.
   *
   * KHÔNG chặn ngữ cảnh của trang: spec L273 quy định rõ “đã có hội thoại →
   * chip là override per-turn”, nên khi đang ở `/machines/<id>` thì máy đó vẫn
   * áp cho lượt tiếp theo bất kể đang mở hội thoại nào. Xem contract D7.
   */
  resetPendingMachineContext(): void;
}

/**
 * Trạng thái ghi đè ngữ cảnh, gắn với pathname đã sinh ra nó.
 * `cleared` tách bạch với `machineId: null` — nếu gộp, bấm “Gỡ” sẽ bị hiểu là
 * “không có override” và lùi về máy của trang, tức là Gỡ không bao giờ có tác dụng.
 */
interface ContextOverride {
  pathname: string;
  /** Ghi đè tường minh (vd chọn máy khác). */
  machineId: string | null;
  /** Người dùng đã bấm “Gỡ” → phải chặn ngữ cảnh của trang. */
  cleared: boolean;
}

export function useChatPanel(): UseChatPanelResult {
  const pathname = usePathname() ?? "";
  const machineId = useMemo(() => deriveMachineId(pathname), [pathname]);

  // localStorage là nguồn sự thật bên ngoài React → đọc qua
  // useSyncExternalStore thay vì setState trong effect. Server snapshot = false
  // nên render SSR không nháy panel rồi mới tắt, và đồng bị được cả tab khác.
  const open = useSyncExternalStore(
    subscribeOpen,
    currentOpen,
    () => false,
  );

  // Ghi đè gắn với pathname đã sinh ra nó: điều hướng sang máy khác thì ghi đè
  // tự rụng, tránh hỏi nhầm về một máy không còn mở.
  const [override, setOverride] = useState<ContextOverride>({
    pathname,
    machineId: null,
    cleared: false,
  });

  const overrideIsCurrent = override.pathname === pathname;
  const pendingMachineId = overrideIsCurrent
    ? override.cleared
      ? null
      : (override.machineId ?? machineId)
    : machineId;

  const setOpen = useCallback((next: boolean) => setStoredOpen(next), []);
  const toggle = useCallback(() => setStoredOpen(!currentOpen()), []);

  const setPendingMachineId = useCallback(
    (id: string | null) => setOverride({ pathname, machineId: id, cleared: id === null }),
    [pathname],
  );
  const clearPendingMachineId = useCallback(
    () => setOverride({ pathname, machineId: null, cleared: true }),
    [pathname],
  );

  /**
   * Đóng băng ngữ cảnh khi người dùng chuyển hội thoại: ghi đè cũ (kể cả `cleared`)
   * không được sống tiếp, nếu không quay lại máy cũ sẽ thấy “đã gỡ” từ hôm trước.
   * Sau reset, ngữ cảnh áp dụng là `machine_id` ĐÃ LƯU của hội thoái (xem `storedMachineId`).
   */
  const resetPendingMachineContext = useCallback(
    () => setOverride({ pathname, machineId: null, cleared: false }),
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
    resetPendingMachineContext,
  };
}