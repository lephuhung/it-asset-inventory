"use client";

/**
 * Panel chat dock bên phải portal.
 *
 * - Là **sibling** của cột nội dung trong layout (không phải overlay), nên nội
 *   dung co lại thay vì bị che.
 * - Chỉ SuperAdmin thấy — cùng cổng vai trò như `/dfir`.
 * - Màn nhỏ chuyển thành drawer trượt từ phải.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare, PanelRightClose, Send, Square, X } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { ChatConversationList } from "@/components/chat/chat-conversation-list";
import { ChatContextChip } from "@/components/chat/chat-context-chip";
import { ChatMessage } from "@/components/chat/chat-message";
import { useChatPanel } from "@/components/chat/use-chat-panel";
import { useChatStream } from "@/components/chat/use-chat-stream";
import { api } from "@/lib/api";
import { chatApi } from "@/lib/chat";
import type { ChatConversation, ChatConversationDetail, SessionUser } from "@/lib/types";

const SUPER_ADMIN_ROLES: SessionUser["role"][] = ["super_admin", "admin_global"];

function isSuperAdmin(user: SessionUser | null): boolean {
  return !!user && SUPER_ADMIN_ROLES.includes(user.role);
}

export function ChatRail() {
  const { user } = useAuth();
  const allowed = isSuperAdmin(user);
  const { open, toggle, pendingMachineId, clearPendingMachineId } = useChatPanel();

  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChatConversationDetail | null>(null);
  const [input, setInput] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  // hostname theo machine_id — tra cứu lười, không cần reset khi rời trang máy.
  const [hostnames, setHostnames] = useState<Record<string, string>>({});
  const hostname = pendingMachineId ? (hostnames[pendingMachineId] ?? null) : null;

  const { state, streaming, send, cancel, reset } = useChatStream(activeId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
    if (!pendingMachineId || hostnames[pendingMachineId]) return;
    let cancelled = false;
    void api
      .get<{ hostname?: string | null }>(`/machines/${pendingMachineId}`)
      .then((m) => {
        if (!cancelled && m?.hostname) {
          setHostnames((prev) => ({ ...prev, [pendingMachineId]: m.hostname as string }));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pendingMachineId, hostnames]);

  const openConversation = useCallback(async (id: string) => {
    reset();
    setActiveId(id);
    try {
      setDetail(await chatApi.getConversation(id));
    } catch {
      setDetail(null);
    }
  }, [reset]);

  const createConversation = useCallback(async (): Promise<string | null> => {
    try {
      const created = await chatApi.createConversation(
        pendingMachineId ? { machine_id: pendingMachineId } : {},
      );
      await refreshConversations();
      setActiveId(created.id);
      setDetail({ ...created, messages: [], active_turn_id: null });
      reset();
      return created.id;
    } catch {
      setLoadError("Không tạo được hội thoại mới.");
      return null;
    }
  }, [pendingMachineId, refreshConversations, reset]);

  const handleDelete = useCallback(
    async (id: string) => {
      // Xoá không hoàn tác được → hỏi lại trước.
      if (!window.confirm("Xoá hội thoại này? Không thể hoàn tác.")) return;
      try {
        await chatApi.deleteConversation(id);
        await refreshConversations();
        if (id === activeId) {
          reset();
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
    if (!content || streaming) return;

    let conversationId = activeId;
    if (!conversationId) {
      conversationId = await createConversation();
      if (!conversationId) return;
    }

    setInput("");
    await send(content, pendingMachineId ? { machine_id: pendingMachineId } : null);

    // Persist xong → đồng bộ tiêu đề/số tin nhắn và lịch sử vừa trả lời.
    await refreshConversations().catch(() => undefined);
    try {
      setDetail(await chatApi.getConversation(conversationId));
    } catch {
      // giữ nguyên tin nhắn đang hiển thị
    }
  }, [activeId, createConversation, input, pendingMachineId, refreshConversations, send, streaming]);

  const handleRetry = useCallback(() => {
    const last = detail?.messages.filter((m) => m.role === "user").at(-1);
    setInput(last?.content ?? "");
  }, [detail]);

  // "Ghim" = ghi ngữ cảnh vào hội thoại. Không có hội thoại thì không có chỗ để ghim.
  const handlePinContext = useCallback(
    async (machineId: string) => {
      if (!activeId) return;
      try {
        const updated = await chatApi.patchConversation(activeId, { machine_id: machineId });
        setDetail((prev) => (prev ? { ...prev, machine_id: updated.machine_id } : prev));
      } catch {
        setLoadError("Không ghim được ngữ cảnh máy.");
      }
    },
    [activeId],
  );

  // Không phải SuperAdmin → không render gì cả (kể cả nút bật/tắt).
  if (!allowed) return null;

  const messages = detail?.messages ?? [];
  const showStreamed =
    streaming || state.content !== "" || state.error !== null;

  return (
    <>
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
          aria-label="Trợ lý tra cứu"
          className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[400px] shrink-0 flex-col border-l border-slate-200 bg-white shadow-xl md:static md:z-auto md:w-[400px] md:max-w-none md:shadow-none"
        >
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 px-3">
            <MessageSquare size={17} className="text-slate-500" aria-hidden="true" />
            <h2 className="flex-1 text-sm font-semibold text-slate-800">Trợ lý tra cứu</h2>
            <button
              type="button"
              onClick={toggle}
              aria-label="Thu gọn trợ lý tra cứu"
              aria-expanded
              className="hidden w-9 cursor-pointer items-center justify-center rounded-md py-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:flex"
            >
              <PanelRightClose size={17} aria-hidden="true" />
            </button>
            <button
              type="button"
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
                {messages.map((m) => (
                  <ChatMessage
                    key={m.id}
                    role={m.role}
                    content={m.content}
                    errorCategory={m.error_category}
                    createdAt={m.created_at}
                  />
                ))}
                {showStreamed && (
                  <ChatMessage
                    role="assistant"
                    content={state.content}
                    tools={state.tools}
                    errorCategory={state.error?.category ?? null}
                    createdAt={new Date().toISOString()}
                    streaming={streaming}
                  />
                )}
              </div>
            )}
          </div>

          <ChatContextChip
            machineId={pendingMachineId}
            hostname={hostname}
            pinned={!!pendingMachineId && detail?.machine_id === pendingMachineId}
            onClear={clearPendingMachineId}
            onPin={(id) => void handlePinContext(id)}
          />

          {state.error && (
            <div className="shrink-0 px-3 pb-1">
              <p className="rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700">
                <span className="font-mono font-medium">{state.error.category}</span>
                <span className="mt-0.5 block">{state.error.hint}</span>
              </p>
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
              {streaming ? (
                <button
                  type="button"
                  onClick={() => void cancel()}
                  aria-label="Dừng trả lời"
                  className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200"
                >
                  <Square size={15} aria-hidden="true" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={!input.trim()}
                  aria-label="Gửi câu hỏi"
                  className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-blue-600 text-white disabled:cursor-not-allowed disabled:bg-slate-200"
                >
                  <Send size={15} aria-hidden="true" />
                </button>
              )}
            </div>
            {state.error?.retryable && (
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