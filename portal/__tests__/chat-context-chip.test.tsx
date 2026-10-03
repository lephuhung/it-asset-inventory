import { describe, it, expect, vi } from "vitest";
import { renderToString } from "react-dom/server";

import { ChatContextChip } from "@/components/chat/chat-context-chip";

const noop = () => undefined;

describe("ChatContextChip", () => {
  it("renders nothing without a machine context", () => {
    expect(renderToString(<ChatContextChip machineId={null} onClear={noop} onPin={noop} />)).toBe("");
  });

  it("shows the Vietnamese soft-context copy with the hostname", () => {
    const html = renderToString(
      <ChatContextChip machineId="m1" hostname="WS-01" onClear={noop} onPin={noop} />,
    );
    expect(html).toContain("Đang hỏi về:");
    expect(html).toContain("WS-01");
  });

  it("falls back to a shortened id when the hostname is unknown", () => {
    const html = renderToString(
      <ChatContextChip
        machineId="11111111-1111-4111-8111-111111111111"
        onClear={noop}
        onPin={noop}
      />,
    );
    expect(html).toContain("Đang hỏi về:");
    expect(html).not.toContain("11111111-1111-4111-8111-111111111111");
  });

  it("offers a clear control", () => {
    const html = renderToString(
      <ChatContextChip machineId="m1" hostname="WS-01" onClear={noop} onPin={noop} />,
    );
    expect(html).toContain("aria-label");
    expect(html).toMatch(/Gỡ|bỏ/i);
  });

  it("offers a pin control when the context is not yet stored", () => {
    const html = renderToString(
      <ChatContextChip machineId="m1" hostname="WS-01" pinned={false} onClear={noop} onPin={noop} />,
    );
    expect(html).toContain("Ghim");
  });

  it("shows the pinned state instead of the pin action once stored", () => {
    const html = renderToString(
      <ChatContextChip machineId="m1" hostname="WS-01" pinned onClear={noop} onPin={noop} />,
    );
    expect(html).toContain("Đã ghim");
    expect(html).not.toContain("Ghim vào hội thoại");
  });

  it("explains that the context is per-turn, not persisted", () => {
    const html = renderToString(
      <ChatContextChip machineId="m1" hostname="WS-01" onClear={noop} onPin={noop} />,
    );
    expect(html).toMatch(/lượt|chỉ áp dụng|không lưu/i);
  });

  it("escapes a hostile hostname", () => {
    const html = renderToString(
      <ChatContextChip machineId="m1" hostname={'<b onmouseover="x">'} onClear={noop} onPin={noop} />,
    );
    expect(html).not.toContain("<b onmouseover");
    expect(html).toContain("&lt;b");
  });
});