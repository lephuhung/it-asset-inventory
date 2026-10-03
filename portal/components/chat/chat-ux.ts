/**
 * Quyết định thuần cho tầng UX của rail (composer + banner lỗi).
 *
 * Tách khỏi JSX để test được bằng vitest ở môi trường node — không cần jsdom,
 * và "nút nào hiện khi nào" trở thành hợp đồng rõ ràng thay vì rơi vãi trong
 * component.
 */

import { chatErrorHint } from "@/components/chat/chat-message";
import type { ChatMessage } from "@/lib/types";

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
 * `hint` rỗng thì lấy câu chữ mặc định theo taxonomy — không bao giờ để trống.
 */
export function formatErrorBanner(error: ErrorLike | null | undefined): ErrorBanner | null {
  if (!error) return null;
  const hint = error.hint?.trim() || chatErrorHint(error.category);
  const status = error.httpStatus ? ` [HTTP ${error.httpStatus}]` : "";
  return {
    category: error.category,
    text: `[${error.category}] ${hint}${status}`,
    canRetry: Boolean(error.retryable),
  };
}

/** Câu hỏi gần nhất của người dùng để điền lại khi bấm "Thử lại". */
export function nextRetryContent(messages: ChatMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user" && messages[i].content.trim()) return messages[i].content;
  }
  return "";
}