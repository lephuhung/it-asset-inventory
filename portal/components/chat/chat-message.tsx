"use client";

/**
 * Một tin nhắn trong rail: nội dung + dấu vết tool + nhãn lỗi.
 *
 * Nội dung assistant đi qua `InvestigationMarkdown` (tái dùng renderer sẵn có).
 * Nội dung user/system hiển thị nguyên văn — người dùng gõ gì thì thấy bấy nhiêu,
 * không tự biến `**...**` thành định dạng.
 */

import { InvestigationMarkdown } from "@/components/investigation-markdown";
import { ChatToolTrace } from "@/components/chat/chat-tool-trace";
import { formatDateTime } from "@/lib/format";
import type { ChatErrorCategory, ChatRole, ChatToolCall } from "@/lib/types";

const ROLE_LABEL: Record<ChatRole, string> = {
  user: "Bạn",
  assistant: "Trợ lý",
  system: "Hệ thống",
};

/**
 * Gợi ý tiếng Việt cho từng `category` (spec §SSE error taxonomy).
 * Chỉ là câu chữ thân thiện — không bao giờ chứa exception/prompt/evidence thô.
 */
export const CHAT_ERROR_HINTS: Record<ChatErrorCategory, string> = {
  chat_validation: "Câu hỏi không hợp lệ. Hãy thử lại với nội dung khác.",
  chat_authz: "Bạn không có quyền dùng trợ lý này.",
  chat_not_found: "Không tìm thấy hội thoại.",
  chat_conflict_active_turn: "Đang có một câu hỏi khác chưa trả lời xong. Hãy đợi hoặc dừng câu đó.",
  chat_conflict_idempotency: "Câu hỏi này vừa được gửi lại. Hãy thử lại sau.",
  chat_rate_limited: "Bạn gửi hơi nhanh. Vui lòng chờ một chút rồi thử lại.",
  chat_budget_exceeded: "Đã hết hạn mức token hôm nay. Hãy thử lại vào ngày mai.",
  chat_budget_unavailable: "Không kiểm tra được hạn mức token. Thử lại sau.",
  chat_guardrail_sql: "Câu truy vấn không được phép. Trợ lý chỉ được đọc, không được thay đổi dữ liệu.",
  chat_guardrail_vql: "Câu truy vấn Velociraptor không được phép.",
  chat_collection_denied: "Không được phép thu thập dữ liệu trên máy này.",
  chat_timeout_llm: "Mô hình phản hồi quá lâu. Hãy thử lại.",
  chat_timeout_tool: "Công cụ phản hồi quá lâu. Hãy thử lại.",
  chat_upstream_llm: "Dịch vụ mô hình đang bận. Hãy thử lại sau.",
  chat_upstream_velo: "Không kết nối được tới Velociraptor. Hãy thử lại sau.",
  chat_mcp_bridge: "Cầu nối công cụ đang bận. Hãy thử lại sau.",
  chat_canceled: "Đã dừng câu trả lời.",
  chat_stream_lost: "Kết nối bị gián đoạn. Hãy thử lại.",
  chat_dispatch_stuck: "Yêu cầu bị treo. Hãy thử lại.",
  chat_internal: "Đã xảy ra lỗi. Hãy thử lại.",
};

/** Câu chữ an toàn cho một `error_category` bất kỳ (kể cả loại chưa biết). */
export function chatErrorHint(category: string): string {
  return CHAT_ERROR_HINTS[category as ChatErrorCategory] ?? CHAT_ERROR_HINTS.chat_internal;
}

export interface ChatMessageProps {
  role: ChatRole;
  content: string;
  tools?: ChatToolCall[];
  errorCategory?: ChatErrorCategory | string | null;
  createdAt: string;
  /** Đang stream — dùng để hiện con trỏ nhấp nháy. */
  streaming?: boolean;
}

export function ChatMessage({
  role,
  content,
  tools = [],
  errorCategory,
  createdAt,
  streaming = false,
}: ChatMessageProps) {
  const isUser = role === "user";

  return (
    // `data-role` để test/đọc màn hình xác định được bong bóng nào thuộc vai
    // trò nào — nhãn hiển thị có kèm giờ nên không assert được bằng text thô.
    <div
      data-role={role}
      className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={
          isUser
            ? "max-w-[92%] rounded-2xl rounded-br-sm bg-blue-600 px-3 py-2 text-sm whitespace-pre-wrap text-white"
            : "w-full max-w-[92%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
        }
      >
        {role === "assistant" ? (
          <>
            {content ? (
              <div className="text-sm leading-relaxed">
                <InvestigationMarkdown content={content} />
              </div>
            ) : null}
            <ChatToolTrace tools={tools} />
            {errorCategory ? (
              <p className="mt-2 rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700">
                <span className="font-mono font-medium">{errorCategory}</span>
                <span className="mt-0.5 block">{chatErrorHint(errorCategory)}</span>
              </p>
            ) : null}
            {streaming ? (
              <span className="ml-1 inline-block h-3.5 w-1.5 animate-pulse rounded-full bg-slate-400" aria-hidden="true" />
            ) : null}
          </>
        ) : (
          <span className="whitespace-pre-wrap break-words">{content}</span>
        )}
      </div>

      <span className="px-1 text-[11px] text-slate-400">
        {ROLE_LABEL[role]} · {formatDateTime(createdAt)}
      </span>
    </div>
  );
}