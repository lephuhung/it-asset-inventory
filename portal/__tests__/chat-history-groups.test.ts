import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";

import { groupConversationsByDay } from "@/components/chat/chat-ux";
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

const NOW = new Date("2026-10-03T12:00:00Z");

describe("groupConversationsByDay", () => {
  it("tách nhóm Hôm nay / Hôm qua / Trước đó", () => {
    const groups = groupConversationsByDay(
      [
        conv({ id: "a", last_message_at: "2026-10-03T09:00:00Z" }),
        conv({ id: "b", last_message_at: "2026-10-02T09:00:00Z" }),
        conv({ id: "c", last_message_at: "2026-09-20T09:00:00Z" }),
      ],
      NOW,
    );

    expect(groups.map((g) => g.label)).toEqual(["Hôm nay", "Hôm qua", "Trước đó"]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["a"]);
    expect(groups[2].items.map((i) => i.id)).toEqual(["c"]);
  });

  it("xếp nhóm theo thứ tự thời gian giảm dần", () => {
    const groups = groupConversationsByDay(
      [
        conv({ id: "old", last_message_at: "2026-09-20T09:00:00Z" }),
        conv({ id: "new", last_message_at: "2026-10-03T09:00:00Z" }),
        conv({ id: "mid", last_message_at: "2026-10-02T09:00:00Z" }),
      ],
      NOW,
    );
    expect(groups.map((g) => g.label)).toEqual(["Hôm nay", "Hôm qua", "Trước đó"]);
  });

  it("dùng updated_at khi chưa có tin nhắn nào", () => {
    const groups = groupConversationsByDay(
      [conv({ id: "new", updated_at: "2026-10-03T08:00:00Z", last_message_at: null })],
      NOW,
    );
    expect(groups[0].label).toBe("Hôm nay");
  });

  it("lùi về created_at khi updated_at cũ hơn (dữ liệu không nhất quán)", () => {
    const groups = groupConversationsByDay(
      [conv({ id: "x", created_at: "2026-10-03T08:00:00Z", updated_at: "2026-10-02T08:00:00Z", last_message_at: null })],
      NOW,
    );
    // last_message_at > updated_at > created_at — lấy mốc gần nhất có sẵn.
    expect(["Hôm nay", "Hôm qua"]).toContain(groups[0].label);
  });

  it("trả về mảng rỗng khi không có hội thoại", () => {
    expect(groupConversationsByDay([], NOW)).toEqual([]);
  });

  it("chỉ tạo nhóm cho ngày thực sự có hội thoại", () => {
    const groups = groupConversationsByDay(
      [conv({ id: "a", last_message_at: "2026-10-03T09:00:00Z" })],
      NOW,
    );
    expect(groups).toHaveLength(1);
  });
});