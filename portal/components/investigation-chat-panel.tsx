"use client";

import { memo, useEffect, useRef, useState } from "react";
import { Loader2, Send } from "lucide-react";
import { Button, Card, Textarea } from "@/components/ui";
import type { DfirInvestigationMessage, InvestigationStatus } from "@/lib/types";
import { InvestigationMarkdown } from "@/components/investigation-markdown";

/**
 * Panel "Hỏi tiếp AI" cho investigation.
 *
 * Tách khỏi `InvestigationDetailPage` để:
 *  - State `chatInput`/`chatting` nằm local → gõ ký tự không render lại
 *    page detail (không parse lại report, không render lại messages khác).
 *  - Auto-scroll `chatEndRef` và layout khóa chiều cao cũng giữ trong panel.
 *  - Component được memo, props không đổi → không re-render khi parent rerender.
 *
 * KHÔNG gọi API trực tiếp: parent truyền `onSend(message)` và chịu trách
 * nhiệm optimistic update + POST `/admin/llm-dfir/investigations/{id}/chat`.
 */
export interface InvestigationChatPanelProps {
  investigationId: string;
  status: InvestigationStatus;
  messages: DfirInvestigationMessage[];
  onSend: (message: string) => Promise<void>;
}

function InvestigationChatPanelInner({
  status,
  messages,
  onSend,
}: InvestigationChatPanelProps) {
  // State input — local. Gõ 20 ký tự chỉ re-render component này.
  const [chatInput, setChatInput] = useState("");
  const [chatting, setChatting] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll khi có message mới (chỉ re-run khi `messages` đổi).
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const submit = async () => {
    const msg = chatInput.trim();
    if (!msg || chatting) return;
    setChatting(true);
    // Clear input NGAY khi bắt đầu gửi để UX phản hồi tức thì.
    setChatInput("");
    try {
      await onSend(msg);
    } finally {
      setChatting(false);
    }
  };

  return (
    <Card title="Hỏi tiếp AI" className="flex flex-col" bodyClass="flex flex-1 flex-col min-h-0">
      <div className="min-h-[400px] max-h-[600px] flex-1 space-y-3 overflow-y-auto pr-2">
        {messages.length === 0 && status === "completed" && (
          <p className="text-sm text-slate-500">
            Đặt câu hỏi tiếp về cuộc điều tra này. AI sẽ trả lời dựa trên dữ liệu đã thu thập.
          </p>
        )}
        {messages.length === 0 && status !== "completed" && (
          <p className="text-sm text-slate-500">
            Chat khả dụng sau khi cuộc điều tra hoàn thành.
          </p>
        )}
        {messages
          .filter((m) => m.role !== "system")
          .map((m) => (
            <div
              key={m.id}
              className={`rounded-lg p-3 ${
                m.role === "user"
                  ? "ml-10 bg-brand-100"
                  : "mr-10 bg-slate-100"
              }`}
            >
              <div className="mb-1 text-xs text-slate-400">
                {m.role === "user" ? "Bạn" : "AI Assistant"}
              </div>
              {m.role === "assistant" ? (
                // Memoized parser — chỉ render khi `content` đổi.
                <div className="max-w-none">
                  <InvestigationMarkdown content={m.content} />
                </div>
              ) : (
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                  {m.content}
                </div>
              )}
            </div>
          ))}
        <div ref={chatEndRef} />
      </div>
      <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
        <Textarea
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={2}
          disabled={status !== "completed" || chatting}
          aria-label="Câu hỏi tiếp về cuộc điều tra"
          placeholder="VD: Có dấu hiệu crypto miner không? Có kết nối ra ngoài đáng ngờ không?"
          className="min-h-0 resize-none"
        />
        <Button
          onClick={() => void submit()}
          disabled={!chatInput.trim() || chatting || status !== "completed"}
          className="w-full"
        >
          {chatting && <Loader2 className="size-4 animate-spin" />}
          <Send className="size-4" />
          Gửi (Ctrl+Enter)
        </Button>
      </div>
    </Card>
  );
}

/**
 * Memo để parent rerender (ví dụ `load()` xong) nhưng messages/status không
 * đổi → panel không re-render → input vẫn giữ focus và không parse lại report.
 */
export const InvestigationChatPanel = memo(InvestigationChatPanelInner);
