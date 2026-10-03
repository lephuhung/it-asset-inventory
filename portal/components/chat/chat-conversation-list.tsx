"use client";

/**
 * Danh sách hội thoại (lịch sử) của rail.
 *
 * Xoá luôn hỏi lại trước — xoá hội thoại là không hoàn tác được, nên không
 * được vô tình kích bởi một cú click. Việc gọi `onDelete` để quyết định còn là
 * việc của `ChatRail` (nơi có quyền gọi API).
 */

import { MessageSquarePlus, Trash2 } from "lucide-react";
import { timeAgo } from "@/lib/format";
import type { ChatConversation } from "@/lib/types";

export interface ChatConversationListProps {
  items: ChatConversation[];
  activeId?: string | null;
  onSelect(id: string): void;
  onCreate(): void;
  onDelete(id: string): void;
}

export function ChatConversationList({
  items,
  activeId = null,
  onSelect,
  onCreate,
  onDelete,
}: ChatConversationListProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-3 pt-3">
        <button
          type="button"
          onClick={onCreate}
          className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
        >
          <MessageSquarePlus size={15} aria-hidden="true" />
          <span>Cuộc trò chuyện mới</span>
        </button>
      </div>

      <nav aria-label="Danh sách hội thoại" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {items.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-slate-400">Chưa có hội thoại nào.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {items.map((c) => {
              const active = c.id === activeId;
              return (
                <li key={c.id} className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    aria-current={active ? "true" : undefined}
                    className={`min-w-0 flex-1 cursor-pointer rounded-lg px-2 py-2 text-left transition-colors ${
                      active ? "bg-blue-50 text-blue-700" : "text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <span className="block truncate text-sm font-medium">
                      {c.title ?? "Hội thoại mới"}
                    </span>
                    <span className="block text-[11px] text-slate-400">
                      {c.archived ? "Lưu trữ" : `${c.message_count} tin nhắn`}
                      {c.last_message_at ? ` · ${timeAgo(c.last_message_at)}` : ""}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(c.id)}
                    aria-label={`Xoá hội thoại: ${c.title ?? "Hội thoại mới"}`}
                    className="shrink-0 cursor-pointer rounded-md p-1.5 text-slate-300 opacity-0 transition-colors hover:bg-red-50 hover:text-red-600 focus:opacity-100 group-hover:opacity-100"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </div>
  );
}