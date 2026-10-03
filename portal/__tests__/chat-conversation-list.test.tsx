import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";

import { ChatConversationList } from "@/components/chat/chat-conversation-list";
import type { ChatConversation } from "@/lib/types";

function conv(over: Partial<ChatConversation> = {}): ChatConversation {
  return {
    id: "c1",
    title: null,
    machine_id: null,
    message_count: 0,
    last_message_at: null,
    archived: false,
    created_at: "2026-10-02T08:00:00Z",
    updated_at: "2026-10-02T08:00:00Z",
    ...over,
  };
}

const noop = () => undefined;

describe("ChatConversationList", () => {
  it("falls back to Vietnamese copy for an untitled conversation", () => {
    const html = renderToString(<ChatConversationList items={[conv()]} onSelect={noop} onCreate={noop} onDelete={noop} />);
    expect(html).toContain("Hội thoại mới");
  });

  it("renders the real title when set", () => {
    const html = renderToString(
      <ChatConversationList items={[conv({ title: "Kiểm kê phòng 3" })]} onSelect={noop} onCreate={noop} onDelete={noop} />,
    );
    expect(html).toContain("Kiểm kê phòng 3");
    expect(html).not.toContain("Hội thoại mới");
  });

  it("renders an empty state when there are no conversations", () => {
    const html = renderToString(<ChatConversationList items={[]} onSelect={noop} onCreate={noop} onDelete={noop} />);
    expect(html).toMatch(/Chưa có hội thoại/i);
  });

  it("always offers a way to start a new conversation, even when empty", () => {
    const html = renderToString(<ChatConversationList items={[]} onSelect={noop} onCreate={noop} onDelete={noop} />);
    expect(html).toContain("Cuộc trò chuyện mới");
  });

  it("shows the message count", () => {
    const html = renderToString(
      <ChatConversationList items={[conv({ message_count: 7 })]} onSelect={noop} onCreate={noop} onDelete={noop} />,
    );
    expect(html).toContain("7");
  });

  it("marks the active conversation for assistive tech", () => {
    const html = renderToString(
      <ChatConversationList items={[conv()]} activeId="c1" onSelect={noop} onCreate={noop} onDelete={noop} />,
    );
    expect(html).toContain('aria-current="true"');
  });

  it("does not mark any conversation active when activeId is null", () => {
    const html = renderToString(
      <ChatConversationList items={[conv()]} activeId={null} onSelect={noop} onCreate={noop} onDelete={noop} />,
    );
    expect(html).not.toContain('aria-current="true"');
  });

  it("exposes a delete control per conversation", () => {
    const html = renderToString(
      <ChatConversationList items={[conv()]} onSelect={noop} onCreate={noop} onDelete={noop} />,
    );
    expect(html.toLowerCase()).toContain("aria-label");
    expect(html).toContain("Xoá hội thoại");
  });

  it("renders relative time for the last message", () => {
    const html = renderToString(
      <ChatConversationList
        items={[conv({ last_message_at: "2026-10-02T09:00:00Z" })]}
        onSelect={noop}
        onCreate={noop}
        onDelete={noop}
      />,
    );
    expect(html).not.toContain("2026-10-02T09:00:00Z");
    expect(html).toMatch(/trước|vừa|phút|giờ|ngày/);
  });

  it("escapes a hostile conversation title", () => {
    const html = renderToString(
      <ChatConversationList
        items={[conv({ title: '<img src=x onerror="alert(1)">' })]}
        onSelect={noop}
        onCreate={noop}
        onDelete={noop}
      />,
    );
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("renders an archived conversation without leaking its raw flag", () => {
    const html = renderToString(
      <ChatConversationList items={[conv({ archived: true })]} onSelect={noop} onCreate={noop} onDelete={noop} />,
    );
    expect(html).toContain("Lưu trữ");
    expect(html).not.toContain("archived");
  });

  it("renders many conversations without dropping any", () => {
    const items = Array.from({ length: 12 }, (_, i) => conv({ id: `c${i}`, title: `Hội thoại ${i}` }));
    const html = renderToString(<ChatConversationList items={items} onSelect={noop} onCreate={noop} onDelete={noop} />);
    for (let i = 0; i < 12; i++) expect(html).toContain(`Hội thoại ${i}`);
  });
});