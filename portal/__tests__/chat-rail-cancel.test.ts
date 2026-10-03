/**
 * Task 9 — cancel / error / retry.
 *
 * Test ở tầng hành vi thuần (không cần DOM): quyết định "nút nào hiện, banner
 * nói gì, retry gửi lại câu nào" được tách ra khỏi JSX để kiểm chứng được.
 */
import { describe, it, expect } from "vitest";

import {
  decideComposerState,
  formatErrorBanner,
  isNearBottom,
  nextRetryContent,
} from "@/components/chat/chat-ux";
import type { ChatMessage } from "@/lib/types";

const NOW = "2026-10-02T09:30:00Z";

function msg(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m1",
    role: "user",
    content: "câu hỏi",
    turn_id: "t1",
    machine_id: null,
    error_category: null,
    created_at: NOW,
    ...over,
  };
}

describe("decideComposerState", () => {
  it("shows the stop button while streaming", () => {
    expect(decideComposerState({ streaming: true, input: "" }).mode).toBe("stop");
  });

  it("shows the stop button even when the composer is empty while streaming", () => {
    expect(decideComposerState({ streaming: true, input: "" }).stopDisabled).toBe(false);
  });

  it("shows the send button when idle", () => {
    expect(decideComposerState({ streaming: false, input: "xin chào" }).mode).toBe("send");
  });

  it("disables send on an empty composer", () => {
    expect(decideComposerState({ streaming: false, input: "" }).sendDisabled).toBe(true);
  });

  it("treats a whitespace-only composer as empty", () => {
    expect(decideComposerState({ streaming: false, input: "   \n " }).sendDisabled).toBe(true);
  });

  it("keeps the typed text visible while streaming", () => {
    expect(decideComposerState({ streaming: true, input: "abc" }).keepInput).toBe(true);
  });

  it("clears the composer after send", () => {
    expect(decideComposerState({ streaming: false, input: "", justSent: true }).keepInput).toBe(false);
  });
});

describe("formatErrorBanner", () => {
  it("renders the category and hint together", () => {
    const banner = formatErrorBanner({
      category: "chat_budget_exceeded",
      hint: "Đã hết hạn mức token hôm nay.",
      retryable: true,
      httpStatus: 429,
    });
    expect(banner?.category).toBe("chat_budget_exceeded");
    expect(banner?.text).toContain("Đã hết hạn mức token hôm nay.");
  });

  it("surfaces the HTTP status when the backend sent one", () => {
    expect(
      formatErrorBanner({
        category: "chat_rate_limited",
        hint: "Chậm thôi.",
        retryable: true,
        httpStatus: 429,
      })?.text,
    ).toContain("429");
  });

  it("omits the status suffix when there is none", () => {
    expect(
      formatErrorBanner({ category: "chat_stream_lost", hint: "Mất kết nối.", retryable: true })?.text,
    ).not.toContain("HTTP");
  });

  it("returns null when there is no error", () => {
    expect(formatErrorBanner(null)).toBeNull();
  });

  it("marks a non-retryable error so the UI can hide the retry action", () => {
    expect(
      formatErrorBanner({
        category: "chat_guardrail_sql",
        hint: "Câu truy vấn không được phép.",
        retryable: false,
      })?.canRetry,
    ).toBe(false);
  });
});

describe("nextRetryContent", () => {
  it("restores the last user message for retry", () => {
    expect(
      nextRetryContent([
        msg({ id: "m1", role: "user", content: "câu một" }),
        msg({ id: "m2", role: "assistant", content: "trả lời một" }),
      ]),
    ).toBe("câu một");
  });

  it("uses the most recent user message, not the first", () => {
    expect(
      nextRetryContent([
        msg({ id: "m1", role: "user", content: "câu một" }),
        msg({ id: "m2", role: "user", content: "câu hai" }),
      ]),
    ).toBe("câu hai");
  });

  it("skips assistant and system messages", () => {
    expect(
      nextRetryContent([
        msg({ id: "m1", role: "system", content: "bối cảnh hệ thống" }),
        msg({ id: "m2", role: "assistant", content: "trả lời" }),
        msg({ id: "m3", role: "user", content: "câu thật" }),
      ]),
    ).toBe("câu thật");
  });

  it("returns an empty string when there is nothing to retry", () => {
    expect(nextRetryContent([])).toBe("");
    expect(nextRetryContent([msg({ role: "assistant", content: "chỉ có trợ lý" })])).toBe("");
  });

  it("does not retry a failed message as if it were the question", () => {
    expect(nextRetryContent([msg({ role: "user", content: "hỏi", error_category: "chat_timeout_llm" })])).toBe("hỏi");
  });
});
describe("banner không bọc trùng khi hint đã có sẵn format của backend", () => {
  it("giữ nguyên hint đã kèm [category] ... [HTTP code]", () => {
    const banner = formatErrorBanner({
      category: "chat_guardrail_sql",
      hint: "[chat_guardrail_sql] thiếu tham số hostname [HTTP 400]",
      retryable: false,
      httpStatus: 400,
    });
    // Bọc thêm lần nữa sẽ thành [cat] [cat] ... [HTTP 400] [HTTP 400].
    expect(banner?.text).toBe("[chat_guardrail_sql] thiếu tham số hostname [HTTP 400]");
  });

  it("vẫn bọc khi hint trần (chưa có format)", () => {
    const banner = formatErrorBanner({
      category: "chat_timeout_llm",
      hint: "Mô hình phản hồi quá lâu.",
      retryable: true,
      httpStatus: 504,
    });
    expect(banner?.text).toBe("[chat_timeout_llm] Mô hình phản hồi quá lâu. [HTTP 504]");
  });
});

describe("isNearBottom — quyết định có bám đáy hay không", () => {
  const metrics = (scrollTop: number, clientHeight: number, scrollHeight: number) => ({
    scrollTop,
    clientHeight,
    scrollHeight,
  });

  it("đang ở đáy → bám theo", () => {
    expect(isNearBottom(metrics(0, 500, 500))).toBe(true);
  });

  it("cách đáy dưới ngưỡng → vẫn coi là bám (vừa cuộn xuống)", () => {
    expect(isNearBottom(metrics(0, 500, 540))).toBe(true);
  });

  it("đã cuộn lên xa → KHÔNG bám", () => {
    expect(isNearBottom(metrics(0, 500, 1200))).toBe(false);
  });

  it("giữa khung, cách đáy quá ngưỡng → KHÔNG bám", () => {
    expect(isNearBottom(metrics(100, 500, 1200))).toBe(false);
  });

  it("nội dung chưa dài hơn khung → coi như đang ở đáy", () => {
    expect(isNearBottom(metrics(0, 500, 300))).toBe(true);
  });

  it("scrollHeight = 0 (chưa render) → không kẹt vào trạng thái không bám", () => {
    expect(isNearBottom(metrics(0, 0, 0))).toBe(true);
  });

  it("ngưỡng tuỳ chỉnh", () => {
    expect(isNearBottom(metrics(0, 500, 700), 50)).toBe(false);
    expect(isNearBottom(metrics(0, 500, 700), 250)).toBe(true);
  });
});
