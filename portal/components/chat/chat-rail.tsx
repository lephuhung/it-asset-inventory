"use client";

/**
 * Panel chat dock bên phải portal.
 *
 * - Là **sibling** của cột nội dung trong layout (không phải overlay), nên nội
 *   dung co lại thay vì bị che.
 * - Chỉ SuperAdmin thấy — cùng cổng vai trò như `/dfir`.
 * - Màn nhỏ chuyển thành drawer trượt từ phải.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { MessageSquare, PanelRightClose, Send, Square, X } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { ChatConversationList } from "@/components/chat/chat-conversation-list";
import { ChatContextChip } from "@/components/chat/chat-context-chip";
import { ChatMessage } from "@/components/chat/chat-message";
import { useChatPanel } from "@/components/chat/use-chat-panel";
import { useChatStream } from "@/components/chat/use-chat-stream";
import { decideComposerState, formatErrorBanner, nextRetryContent } from "@/components/chat/chat-ux";
import { api } from "@/lib/api";
import { chatApi } from "@/lib/chat";
import type { ChatConversation, ChatConversationDetail, SessionUser } from "@/lib/types";

const SUPER_ADMIN_ROLES: SessionUser["role"][] = ["super_admin", "admin_global"];

/**
 * Theo dõi media query để biết đang ở chế độ drawer hay docked.
 * Dùng useSyncExternalStore: matchMedia là nguồn sự thật bên ngoài React nên
 * không cần setState trong effect.
 */
function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}

function isSuperAdmin(user: SessionUser | null): boolean {
  return !!user && SUPER_ADMIN_ROLES.includes(user.role);
}

export function ChatRail() {
  const { user } = useAuth();
  const allowed = isSuperAdmin(user);
  const { open, toggle, pendingMachineId, clearPendingMachineId, resetPendingMachineContext } =
    useChatPanel();

  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChatConversationDetail | null>(null);
  const [input, setInput] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  // hostname theo machine_id — tra cứu lười, không cần reset khi rời trang máy.
  const [hostnames, setHostnames] = useState<Record<string, string>>({});
  // Ngữ cảnh máy THỰC SỰ gửi đi: ưu tiên ghi đè mềm, không có thì dùng máy đã lưu
  // của hội thoại (spec L269-276: chuyển hội thoại → quay về ngữ cảnh đã lưu).
  const effectiveMachineId = pendingMachineId ?? detail?.machine_id ?? null;
  const hostname = effectiveMachineId ? (hostnames[effectiveMachineId] ?? null) : null;

  const { state, streaming, send, cancel, reset, serverActiveTurnId, setServerActiveTurnId, hasActiveTurn } =
    useChatStream(activeId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  // Drawer (màn nhỏ) che nội dung → giam focus + Escape đóng. Màn rộng thì rail
  // chỉ là một cột cạnh nội dung, không được giam.
  const isDrawer = useMediaQuery("(max-width: 767px)");

  // Chặn response chậm ghi đè nhầm hội thoại đang chọn (B3).
  const selectionRef = useRef(0);
  // Khoá submit trong lúc tạo hội thoại để không tạo trùng (B1).
  const sendingRef = useRef(false);
  // Câu hỏi vừa gửi — giữ riêng vì lỗi trước khi persist sẽ không có trong lịch sử.
  const lastAttemptRef = useRef<{ content: string } | null>(null);
  // Timer hỏi lại turn đang chạy — phải huỷ khi chuyển hội thoại / unmount.
  const pollTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  // Turn server đang theo dõi; đổi turn ⇒ snapshot của turn cũ không được áp.
  const trackedTurnRef = useRef<string | null>(null);
  const beginTracking = useCallback((turnId: string | null) => {
    trackedTurnRef.current = turnId;
  }, []);
  // false sau unmount: continuation của create/send không được tạo request mới.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    // Chụp Set vào biến cục bộ: effect cleanup đóng băng đúng Set lúc mount.
    const timers = pollTimersRef.current;
    return () => {
      mountedRef.current = false;
      for (const t of timers) clearTimeout(t);
      timers.clear();
    };
  }, []);
  // activeId mới nhất, đọc được trong callback bất đồng bộ mà không stale.
  const activeIdRef = useRef<string | null>(activeId);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  const refreshConversations = useCallback(async () => {
    try {
      const res = await chatApi.listConversations({ limit: 50 });
      setConversations(res.items ?? []);
      return res.items ?? [];
    } catch {
      setLoadError("Không tải được danh sách hội thoại.");
      return [];
    }
  }, []);

  // Chỉ tải lịch sử khi rail mở — user không mở thì không đụng API.
  useEffect(() => {
    if (!allowed || !open) return;
    void refreshConversations();
  }, [allowed, open, refreshConversations]);

  // Cuộn xuống đáy mỗi khi có token mới.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [state.content, state.tools.length]);

  // Tên máy để chip ngữ cảnh đọc được. Chỉ cần hostname — không kéo cả object máy.
  // Ghi vào map theo machine_id nên rời trang máy không cần reset.
  useEffect(() => {
    if (!effectiveMachineId || hostnames[effectiveMachineId]) return;
    let cancelled = false;
    void api
      .get<{ hostname?: string | null }>(`/machines/${effectiveMachineId}`)
      .then((m) => {
        if (!cancelled && m?.hostname) {
          setHostnames((prev) => ({ ...prev, [effectiveMachineId]: m.hostname as string }));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [effectiveMachineId, hostnames]);

  /** Khoảng nghỉ giữa các lần hỏi lại turn đang chạy (ms). */
const ACTIVE_TURN_POLL_MS = 3000;
/** Số lần hỏi lại tối đa — sau đó bỏ, đừng đốt pin vô ích. */
const ACTIVE_TURN_POLL_MAX = 100;

/**
 * Hỏi lại hội thoại cho tới khi turn server về trạng thái cuối, rồi nạp lại lịch sử.
 * Turn được tạo từ phiên trước không có stream cục bộ để theo dõi; không thì nút
 * Dừng treo vĩnh viễn và câu trả lời không bao giờ hiện.
 */
const pollUntilTerminal = useCallback(
  (id: string, selection: number, trackedTurnId: string, attempt = 0) => {
    if (!mountedRef.current || selectionRef.current !== selection || attempt >= ACTIVE_TURN_POLL_MAX) return;
    const timer = setTimeout(() => {
      pollTimersRef.current.delete(timer);
      // Kiểm tra TRƯỚC khi gọi: nếu không, một timer đã hẹn vẫn bắn thêm một
      // request sau khi người dùng đã chuyển hội thoại.
      if (!mountedRef.current || selectionRef.current !== selection) return;
      void (async () => {
        try {
          const loaded = await chatApi.getConversation(id);
          if (!mountedRef.current || selectionRef.current !== selection) return;
          // Turn đã đổi (vừa hủy rồi gửi câu mới trong CÙNG hội thoại — selection
          // không đổi) → snapshot của turn cũ không được đè lên lịch sử mới hơn.
          if (trackedTurnRef.current !== trackedTurnId) return;
          if (loaded.active_turn_id) {
            pollUntilTerminal(id, selection, trackedTurnId, attempt + 1);
            return;
          }
          // Turn đã kết thúc → nạp lại lịch sử và mở lại composer.
          setDetail(loaded);
          setServerActiveTurnId(null);
        } catch {
          pollUntilTerminal(id, selection, trackedTurnId, attempt + 1);
        }
      })();
    }, ACTIVE_TURN_POLL_MS);
    pollTimersRef.current.add(timer);
  },
  [setServerActiveTurnId],
);

const openConversation = useCallback(async (id: string) => {
    // Mỗi lần chọn = generation mới; response của lần cũ bị bỏ qua.
    selectionRef.current += 1;
    const selection = selectionRef.current;

    reset();
    setServerActiveTurnId(null);
    setActiveId(id);
    setDetail(null); // xoá ngay, không để nội dung hội thoại cũ lóe lên
    // Chuyển hội thoại → ngữ cảnh mềm quay về máy đã lưu của hội thoại mới.
    resetPendingMachineContext();
    try {
      const loaded = await chatApi.getConversation(id);
      if (selectionRef.current !== selection) return;
      setDetail(loaded);
      // Turn đang chạy ở server (mở lại hội thoại cũ) → hiện nút Dừng, khoá Gửi.
      setServerActiveTurnId(loaded.active_turn_id);
      beginTracking(loaded.active_turn_id);
      if (loaded.active_turn_id) pollUntilTerminal(id, selection, loaded.active_turn_id);
    } catch {
      if (selectionRef.current === selection) setDetail(null);
    }
  }, [beginTracking, pollUntilTerminal, reset, setServerActiveTurnId]);

  const createConversation = useCallback(async (): Promise<string | null> => {
    try {
      // KHÔNG ghi machine_id vào hội thoại: ngữ cảnh là mềm, chỉ lưu khi bấm “Ghim”.
      const created = await chatApi.createConversation({});
      await refreshConversations();
      selectionRef.current += 1;
      setActiveId(created.id);
      setDetail({ ...created, messages: [], active_turn_id: null });
      reset();
      resetPendingMachineContext();
      return created.id;
    } catch {
      setLoadError("Không tạo được hội thoại mới.");
      return null;
    }
  }, [refreshConversations, reset, resetPendingMachineContext]);

  const handleDelete = useCallback(
    async (id: string) => {
      // Xoá không hoàn tác được → hỏi lại trước.
      if (!window.confirm("Xoá hội thoại này? Không thể hoàn tác.")) return;
      try {
        await chatApi.deleteConversation(id);
        await refreshConversations();
        // So sánh với activeId HIỆN TẠI (không phải giá trị đã chụp): người dùng có
        // thể đã chuyển sang hội thoại khác trong lúc chờ xoá.
        if (id === activeIdRef.current) {
          // Vô hiệu hoá selection TRƯỚC khi xoá, nếu không một response đang bay
          // của chính hội thoại này vẫn có thể quay lại điền lại lịch sử đã xoá.
          selectionRef.current += 1;
          reset();
          setServerActiveTurnId(null);
          setActiveId(null);
          setDetail(null);
        }
      } catch {
        setLoadError("Không xoá được hội thoại.");
      }
    },
    [activeId, refreshConversations, reset],
  );

  const handleSend = useCallback(async () => {
    const content = input.trim();
    // `hasActiveTurn` (không chỉ `streaming`): turn đang chạy ở SERVER cũng phải
    // chặn, nếu không nút Gửi bị ẩn nhưng phím Enter vẫn gửi được → 409.
    if (!content || hasActiveTurn || sendingRef.current) return;
    sendingRef.current = true;

    try {
      let conversationId = activeId;
      if (!conversationId) {
        conversationId = await createConversation();
        if (!conversationId || !mountedRef.current) return;
      }

      // Truyền `conversationId` tường minh: callback `send` của render cũ vẫn giữ
      // null và sẽ âm thầm bỏ câu hỏi đầu tiên.
      lastAttemptRef.current = { content };
      setInput("");

      await send(content, {
        conversationId,
        machineContext: effectiveMachineId ? { machine_id: effectiveMachineId } : null,
      });
      // Thả khoá TRƯỚC khi đồng bộ lịch sử: đó là việc nền, không được biến nút
      // Gửi thành im lặng không phản ứi.
      sendingRef.current = false;

      // Persist xong → đồng bộ tiêu đề/số tin nhắn và lịch sử vừa trả lời.
      const selection = selectionRef.current;
      await refreshConversations().catch(() => undefined);
      try {
        const loaded = await chatApi.getConversation(conversationId);
        // Người dùng đã chuyển hội thoại lúc chờ → đừng đè lịch sử lên nhau.
        if (selectionRef.current === selection && activeIdRef.current === conversationId) {
          setDetail(loaded);
          setServerActiveTurnId(loaded.active_turn_id);
          // Stream có thể bị bỏ giữa chừng (mất mạng, người dùng đóng tab) → server
          // vẫn còn turn chạy thì phải hỏi lại, nếu không nút Dừng treo vĩnh viễn.
          beginTracking(loaded.active_turn_id);
          if (loaded.active_turn_id) pollUntilTerminal(conversationId, selection, loaded.active_turn_id);
        }
      } catch {
        // giữ nguyên tin nhắn đang hiển thị
      }
    } finally {
      sendingRef.current = false;
    }
  }, [activeId, beginTracking, createConversation, effectiveMachineId, hasActiveTurn, input, pollUntilTerminal, refreshConversations, send, setServerActiveTurnId]);

  // Nút Dừng: báo lỗi nếu server KHÔNG nhận yêu cầu hủy. Nuốt lỗi rồi báo
  // "canceled" sẽ khiến UI mở nút Gửi trong khi backend vẫn đang chạy.
  const handleCancel = useCallback(async () => {
    try {
      await cancel();
      await refreshConversations().catch(() => undefined);
    } catch {
      setLoadError("Không dừng được câu trả lời. Thử lại hoặc tải lại trang.");
    }
  }, [cancel, refreshConversations]);

  const handleRetry = useCallback(() => {
    // Ưu tiên câu vừa gửi thật — lỗi trước khi persist sẽ không có trong lịch sử.
    setInput(lastAttemptRef.current?.content ?? nextRetryContent(detail?.messages ?? []));
  }, [detail]);

  // "Ghim" = ghi ngữ cảnh vào hội thoại. Không có hội thoại thì không có chỗ để ghim.
  const handlePinContext = useCallback(
    async (machineId: string) => {
      const conversationId = activeIdRef.current;
      if (!conversationId) return;
      const selection = selectionRef.current;
      try {
        const updated = await chatApi.patchConversation(conversationId, { machine_id: machineId });
        // Trong lúc chờ người dùng có thể đã chuyển hội thoại — PATCH của A không
        // được áp lên detail của B.
        if (selectionRef.current !== selection || activeIdRef.current !== conversationId) return;
        setDetail((prev) => (prev ? { ...prev, machine_id: updated.machine_id } : prev));
      } catch {
        setLoadError("Không ghim được ngữ cảnh máy.");
      }
    },
    [],
  );

  // Không phải SuperAdmin → không render gì cả (kể cả nút bật/tắt).
  if (!allowed) return null;

  const messages = detail?.messages ?? [];
  // Khi stream đã persist, tin nhắn trong lịch sử và bản stream là MỘT câu trả lời.
  // MessageOut không mang tools → gắn tools của turn hiện tại vào đó thay vì render
  // thêm một bản (render 2 lần) hoặc ẩn hẳn (mất dấu vết tool).
  const persistedIndex =
    state.messageId !== null ? messages.findIndex((m) => m.id === state.messageId) : -1;
  const streamedAlreadyPersisted = persistedIndex !== -1;
  // Lỗi đã hiển thị ở banner bên dưới → không cần render lại trong khối stream.
  const showStreamed =
    !streamedAlreadyPersisted && (streaming || state.content !== "" || state.tools.length > 0);
  const composer = decideComposerState({ streaming: hasActiveTurn, input });
  const banner = formatErrorBanner(state.error);

  // Thông báo cho trình đọc màn hình: chỉ đổi ở mốc quan trọng, không theo từng token.
  const liveMessage = state.error
    ? `Đã xảy ra lỗi: ${banner?.text ?? state.error.category}`
    : streaming
      ? state.tools.length > 0
        ? `Đang trả lời. Đã dùng ${state.tools.length} công cụ.`
        : "Đang trả lời."
      : state.status === "done"
        ? "Đã có câu trả lời."
        : state.status === "canceled"
          ? "Đã dừng trả lời."
          : "";

  // Mở panel → đưa focus vào ô nhập (drawer) hoặc về nút đóng (docked) để bàn phím
  // không bị bỏ rơi vào vùng đã bị thay thế bởi panel.
  const wasOpenRef = useRef(open);
  useEffect(() => {
    if (!wasOpenRef.current && open) {
      (isDrawer ? inputRef.current : closeButtonRef.current)?.focus();
    }
    wasOpenRef.current = open;
  }, [open, isDrawer]);

  return (
    <>
      {/* Vùng thông báo cho trình đọc màn hình: chỉ đổi khi trạng thái đổi, không
          đọc từng token. aria-live="polite" để không cắt ngang. */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {liveMessage}
      </div>

      {/* Nút bật/tắt — nằm trong cột nội dung, không phải trong panel. */}
      {!open && (
        <button
          type="button"
          onClick={toggle}
          aria-label="Mở trợ lý tra cứu"
          aria-expanded={false}
          className="fixed right-4 bottom-4 z-30 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full bg-blue-600 text-white shadow-lg transition-colors hover:bg-blue-700 md:right-6"
        >
          <MessageSquare size={19} aria-hidden="true" />
        </button>
      )}

      {open && (
        <aside
          ref={panelRef}
          role="dialog"
          aria-modal="false"
          aria-label="Trợ lý tra cứu"
          onKeyDown={(e) => {
            // Escape đóng panel khi đang ở chế độ drawer (mobile che nội dung).
            if (e.key === "Escape" && isDrawer) {
              e.stopPropagation();
              toggle();
            }
          }}
          onBlur={(e) => {
            // Focus trap cho drawer: Tab cuối ra khỏi panel sẽ quay về ô nhập.
            // Dùng blur vì relatedTarget chỉ có trên FocusEvent, không có trên
            // KeyboardEvent.
            if (!isDrawer) return;
            if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
            inputRef.current?.focus();
          }}
          className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[400px] shrink-0 flex-col border-l border-slate-200 bg-white shadow-xl md:static md:z-auto md:w-[400px] md:max-w-none md:shadow-none"
        >
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 px-3">
            <MessageSquare size={17} className="text-slate-500" aria-hidden="true" />
            <h2 className="flex-1 text-sm font-semibold text-slate-800">Trợ lý tra cứu</h2>
            <button
              type="button"
              ref={closeButtonRef}
              onClick={toggle}
              aria-label="Thu gọn trợ lý tra cứu"
              aria-expanded
              className="hidden w-9 cursor-pointer items-center justify-center rounded-md py-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:flex"
            >
              <PanelRightClose size={17} aria-hidden="true" />
            </button>
            <button
              type="button"
              ref={closeButtonRef}
              onClick={toggle}
              aria-label="Đóng trợ lý tra cứu"
              className="flex w-9 cursor-pointer items-center justify-center rounded-md py-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:hidden"
            >
              <X size={17} aria-hidden="true" />
            </button>
          </header>

          <ChatConversationList
            items={conversations}
            activeId={activeId}
            onSelect={(id) => void openConversation(id)}
            onCreate={() => void createConversation()}
            onDelete={(id) => void handleDelete(id)}
          />

          {loadError && (
            <p className="shrink-0 px-3 pb-1 text-xs text-red-600">{loadError}</p>
          )}

          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto border-t border-slate-200 px-3 py-3">
            {messages.length === 0 && !showStreamed ? (
              <p className="mt-6 text-center text-xs text-slate-400">
                Hỏi về máy, phần mềm, cảnh báo hoặc dữ liệu Velociraptor.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {messages.map((m, i) => (
                  <ChatMessage
                    key={m.id}
                    role={m.role}
                    content={m.content}
                    errorCategory={m.error_category}
                    createdAt={m.created_at}
                    // Dấu vết tool chỉ tồn tại trong stream, không có trong MessageOut.
                    tools={i === persistedIndex ? state.tools : []}
                  />
                ))}
                {showStreamed && (
                  <ChatMessage
                    role="assistant"
                    content={state.content}
                    tools={state.tools}
                    // Lỗi đã hiển thị ở banner bên dưới — không lặp lại ở đây.
                    errorCategory={null}
                    createdAt={new Date().toISOString()}
                    streaming={streaming}
                  />
                )}
              </div>
            )}
          </div>

          <ChatContextChip
            machineId={effectiveMachineId}
            hostname={hostname}
            pinned={!!effectiveMachineId && detail?.machine_id === effectiveMachineId}
            onClear={clearPendingMachineId}
            onPin={(id) => handlePinContext(id)}
          />

          {banner && (
            <div className="shrink-0 px-3 pb-1">
              <p className="rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700">{banner.text}</p>
            </div>
          )}

          <div className="shrink-0 border-t border-slate-200 p-2">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void handleSend();
                  }
                }}
                rows={2}
                placeholder="Hỏi về máy hoặc dữ liệu…"
                aria-label="Nội dung câu hỏi"
                className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-blue-400"
              />
              {composer.mode === "stop" ? (
                <button
                  type="button"
                  onClick={() => void handleCancel()}
                  disabled={composer.stopDisabled}
                  aria-label="Dừng trả lời"
                  className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Square size={15} aria-hidden="true" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={composer.sendDisabled}
                  aria-label="Gửi câu hỏi"
                  className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-blue-600 text-white disabled:cursor-not-allowed disabled:bg-slate-200"
                >
                  <Send size={15} aria-hidden="true" />
                </button>
              )}
            </div>
            {banner?.canRetry && (
              <button
                type="button"
                onClick={handleRetry}
                className="mt-1 cursor-pointer text-xs text-blue-600 underline"
              >
                Thử lại câu hỏi vừa rồi
              </button>
            )}
          </div>
        </aside>
      )}
    </>
  );
}