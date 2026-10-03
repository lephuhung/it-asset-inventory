/**
 * Quyết định thuần cho tầng UX của rail (composer + banner lỗi).
 *
 * Tách khỏi JSX để test được bằng vitest ở môi trường node — không cần jsdom,
 * và "nút nào hiện khi nào" trở thành hợp đồng rõ ràng thay vì rơi vãi trong
 * component.
 */

import { chatErrorHint } from "@/components/chat/chat-message";
import type { ChatConversation, ChatMessage } from "@/lib/types";

export type ComposerMode = "send" | "stop";

export interface ComposerInput {
  streaming: boolean;
  input: string;
  /** Vừa gửi xong → xoá ô nhập. */
  justSent?: boolean;
}

export interface ComposerState {
  mode: ComposerMode;
  sendDisabled: boolean;
  stopDisabled: boolean;
  /** Giữ hay xoá nội dung ô nhập. */
  keepInput: boolean;
}

export function decideComposerState(input: ComposerInput): ComposerState {
  const streaming = input.streaming;
  return {
    // Khi đang stream, ô nhập bị chiếm bởi nút Dừng — không cho gửi chồng.
    mode: streaming ? "stop" : "send",
    sendDisabled: !streaming && input.input.trim().length === 0,
    // Nút Dừng luôn dùng được trong lúc stream; ngoài stream không có gì để dừng.
    stopDisabled: !streaming,
    keepInput: !(input.justSent ?? false),
  };
}

export interface ErrorLike {
  category: string;
  hint: string;
  retryable: boolean;
  httpStatus?: number;
}

export interface ErrorBanner {
  category: string;
  /** Câu chữ hoàn chỉnh: `[<category>] <hint> [HTTP <code>]`. */
  text: string;
  canRetry: boolean;
}

/**
 * Định dạng lỗi theo spec: `[<category>] <hint> [HTTP <code>]`.
 *
 * Backend đã gửi `hint` ở đúng format đó (route chat.py bọc sẵn), nếu bọc thêm
 * lần nữa sẽ thành `[cat] [cat] ... [HTTP 400] [HTTP 400]`. Vì vậy chỉ bọc khi
 * hint trần; hint đã có tiền tố `[` thì giữ nguyên.
 */
export function formatErrorBanner(error: ErrorLike | null | undefined): ErrorBanner | null {
  if (!error) return null;
  const hint = error.hint?.trim() || chatErrorHint(error.category);
  const alreadyFormatted = hint.startsWith("[");
  const status = error.httpStatus && !alreadyFormatted ? ` [HTTP ${error.httpStatus}]` : "";
  return {
    category: error.category,
    text: alreadyFormatted ? hint : `[${error.category}] ${hint}${status}`,
    canRetry: Boolean(error.retryable),
  };
}

/** Câu hỏi gần nhất của người dùng để điền lại khi bấm “Thử lại”. */
export function nextRetryContent(messages: ChatMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user" && messages[i].content.trim()) return messages[i].content;
  }
  return "";
}

// ── Gom lịch sử theo ngày ───────────────────────────────────────────────────

export interface ConversationDayGroup {
  /** Nhãn nhóm: `Hôm nay` / `Hôm qua` / `Trước đó`. */
  label: string;
  items: ChatConversation[];
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/**
 * Gom hội thoại theo ngày để hiển thị như danh sách "Today / Yesterday" của
 * bản thiết kế. Mốc thời gian lấy `last_message_at`, thiếu thì `created_at`.
 *
 * Nhóm "Trước đó" gộp mọi thứ cũ hơn hôm qua — tránh sinh hàng chục header
 * "dd/MM/yyyy" khi lịch sử dài.
 */
export function groupConversationsByDay(
  items: ChatConversation[],
  now: Date = new Date(),
): ConversationDayGroup[] {
  const today = startOfDay(now);
  const yesterday = today - 86_400_000;
  const buckets = new Map<string, ChatConversation[]>();

  const ordered = [...items].sort((a, b) => {
    const at = a.last_message_at ?? a.updated_at ?? a.created_at;
    const bt = b.last_message_at ?? b.updated_at ?? b.created_at;
    return new Date(bt).getTime() - new Date(at).getTime();
  });

  for (const item of ordered) {
    const stamp = item.last_message_at ?? item.updated_at ?? item.created_at;
    const day = startOfDay(new Date(stamp));
    const label = day === today ? "Hôm nay" : day === yesterday ? "Hôm qua" : "Trước đó";
    const bucket = buckets.get(label);
    if (bucket) bucket.push(item);
    else buckets.set(label, [item]);
  }

  const order = ["Hôm nay", "Hôm qua", "Trước đó"];
  return order
    .filter((label) => buckets.has(label))
    .map((label) => ({ label, items: buckets.get(label) as ChatConversation[] }));
}