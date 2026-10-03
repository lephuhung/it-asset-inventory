import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";

import { ChatMessage } from "@/components/chat/chat-message";
import { ChatToolTrace } from "@/components/chat/chat-tool-trace";
import type { ChatToolCall } from "@/lib/types";

const NOW = "2026-10-02T09:30:00Z";

function render(element: React.ReactElement): string {
  return renderToString(element);
}

describe("ChatToolTrace", () => {
  const okTool: ChatToolCall = {
    tool_call_id: "t1",
    tool: "inventory_search",
    ok: true,
    row_count: 3,
    byte_count: 256,
    duration_ms: 12,
    client_id: "C.12345",
    flow_id: "F.678",
    error_category: null,
  };

  it("renders the safe trace fields", () => {
    const html = render(<ChatToolTrace tools={[okTool]} />);
    expect(html).toContain("inventory_search");
    expect(html).toContain("3");
    expect(html).toContain("12");
  });

  it("renders the Velociraptor client and flow ids", () => {
    const html = render(<ChatToolTrace tools={[okTool]} />);
    expect(html).toContain("C.12345");
    expect(html).toContain("F.678");
  });

  it("marks a failed tool without inventing a reason", () => {
    const html = render(
      <ChatToolTrace
        tools={[{ ...okTool, ok: false, row_count: null, error_category: "chat_timeout_tool" }]}
      />,
    );
    expect(html).toContain("chat_timeout_tool");
    expect(html).toContain("inventory_search");
  });

  it("shows a running state while the tool has no result yet", () => {
    const html = render(<ChatToolTrace tools={[{ ...okTool, ok: null }]} />);
    expect(html).toContain("inventory_search");
    expect(html).not.toContain("chat_timeout_tool");
  });

  it("renders nothing when there are no tools", () => {
    expect(render(<ChatToolTrace tools={[]} />)).toBe("");
  });

  it("never renders raw payload or digest fields", () => {
    // `params_digest`/`args_digest` chỉ tồn tại ở event tool_start, không được
    // đẩy vào DTO hiển thị (contract D4).
    const html = render(
      <ChatToolTrace
        tools={[{ ...okTool, tool: "x", row_count: null } as unknown as ChatToolCall]}
      />,
    );
    expect(html).not.toContain("params_digest");
    expect(html).not.toContain("args_digest");
    expect(html).not.toContain("undefined");
  });

  it("labels the trace in Vietnamese for the super admin", () => {
    const html = render(<ChatToolTrace tools={[okTool]} />);
    expect(html).toMatch(/công cụ|truy vấn|Tool|Dữ liệu/i);
  });
});

describe("ChatMessage", () => {
  it("renders assistant markdown", () => {
    const html = render(<ChatMessage role="assistant" content="**bold**" createdAt={NOW} tools={[]} />);
    expect(html).toContain("<strong>bold</strong>");
  });

  it("renders user content as plain text, not markdown", () => {
    const html = render(<ChatMessage role="user" content="**không in đậm**" createdAt={NOW} tools={[]} />);
    expect(html).toContain("**không in đậm**");
    expect(html).not.toContain("<strong>");
  });

  it("includes tool chips alongside the answer", () => {
    const html = render(
      <ChatMessage
        role="assistant"
        content="Có 3 máy."
        createdAt={NOW}
        tools={[
          {
            tool_call_id: "t1",
            tool: "inventory_search",
            ok: true,
            row_count: 3,
            byte_count: null,
            duration_ms: 12,
            client_id: null,
            flow_id: null,
            error_category: null,
          },
        ]}
      />,
    );
    expect(html).toContain("inventory_search");
    expect(html).toContain("3");
    expect(html).toContain("Có 3 máy.");
  });

  it("renders the error category safely", () => {
    const html = render(
      <ChatMessage role="assistant" content="" errorCategory="chat_timeout_llm" createdAt={NOW} tools={[]} />,
    );
    expect(html).toContain("chat_timeout_llm");
  });

  it("shows the Vietnamese error hint alongside the category", () => {
    const html = render(
      <ChatMessage role="assistant" content="" errorCategory="chat_timeout_llm" createdAt={NOW} tools={[]} />,
    );
    expect(html).toMatch(/[Hh]ết thời gian|quá lâu|thử lại|không thành công/);
  });

  it("renders a Vietnamese role label per role", () => {
    expect(render(<ChatMessage role="user" content="a" createdAt={NOW} tools={[]} />)).toContain("Bạn");
    expect(render(<ChatMessage role="assistant" content="b" createdAt={NOW} tools={[]} />)).toContain("Trợ lý");
    expect(render(<ChatMessage role="system" content="c" createdAt={NOW} tools={[]} />)).toContain("Hệ thống");
  });

  it("renders the timestamp", () => {
    const html = render(<ChatMessage role="user" content="a" createdAt={NOW} tools={[]} />);
    expect(html).toContain("2026");
  });

  it("survives an empty assistant body without crashing", () => {
    expect(() => render(<ChatMessage role="assistant" content="" createdAt={NOW} tools={[]} />)).not.toThrow();
  });

  it("escapes HTML in user content", () => {
    const html = render(<ChatMessage role="user" content={'<script>alert("x")</script>'} createdAt={NOW} tools={[]} />);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
});