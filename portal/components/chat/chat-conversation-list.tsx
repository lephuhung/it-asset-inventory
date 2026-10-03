"use client";

/**
 * Lịch sử hội thoại — bám theo thiết kế: nhóm theo ngày ("Hôm nay" / "Hôm qua"),
 * mỗi mục là một hàng có icon chip, tiêu đề đậm, phụ đề xám và giờ.
 *
 * Xoá luôn hỏi lại trước — xoá hội thoại là không hoàn tác được. Việc gọi API
 * thuộc về `ChatRail` (nơi có `chatApi`), ở đây chỉ phát `onDelete`.
 */

import { MessageSquarePlus, Search, Trash2 } from "lucide-react";
import { timeAgo } from "@/lib/format";
import { groupConversationsByDay } from "@/components/chat/chat-ux";
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
  const groups = groupConversationsByDay(items);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-4 pt-3">
        <button
          type="button"
          onClick={onCreate}
          className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-slate-200 bg-white py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
        >
          <MessageSquarePlus size={15} aria-hidden="true" />
          <span>Cuộc trò chuyện mới</span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-400">
              <Search size={18} aria-hidden="true" />
            </span>
            <p className="text-sm font-medium text-slate-600">Chưa có hội thoại nào</p>
            <p className="text-xs text-slate-400">
              Bắt đầu bằng một câu hỏi về máy, phần mềm hoặc cảnh báo.
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mt-5 first:mt-4">
              <h3 className="mb-1.5 px-0.5 text-[13px] font-semibold text-slate-700">
                {group.label}
              </h3>
              <ul className="flex flex-col">
                {group.items.map((c) => (
                  <ConversationRow
                    key={c.id}
                    item={c}
                    active={c.id === activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}

function ConversationRow({
  item,
  active,
  onSelect,
  onDelete,
}: {
  item: ChatConversation;
  active: boolean;
  onSelect(id: string): void;
  onDelete(id: string): void;
}) {
  const title = item.title ?? "Hội thoại mới";
  const subtitle = item.archived
    ? "Đã lưu trữ"
    : item.message_count === 0
      ? "Chưa có tin nhắn"
      : `${item.message_count} tin nhắn`;

  return (
    <li className="group flex items-start gap-2.5 rounded-xl px-1 py-1.5 transition-colors hover:bg-slate-50">
      <span
        aria-hidden="true"
        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
          active ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-500"
        }`}
      >
        <Search size={15} />
      </span>

      <button
        type="button"
        onClick={() => onSelect(item.id)}
        aria-current={active ? "true" : undefined}
        className="min-w-0 flex-1 cursor-pointer text-left"
      >
        <span className="block truncate text-sm font-semibold text-slate-800">{title}</span>
        <span className="block truncate text-xs text-slate-500">
          {subtitle}
          {item.last_message_at ? ` · ${timeAgo(item.last_message_at)}` : ""}
        </span>
      </button>

      <button
        type="button"
        onClick={() => onDelete(item.id)}
        aria-label={`Xoá hội thoại: ${title}`}
        className="mt-1 shrink-0 cursor-pointer rounded-md p-1.5 text-slate-300 opacity-0 transition-colors hover:bg-red-50 hover:text-red-600 focus:opacity-100 focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Trash2 size={14} aria-hidden="true" />
      </button>
    </li>
  );
}