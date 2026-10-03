import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue(undefined),
  },
}));

import { api } from "@/lib/api";
import { chatApi } from "@/lib/chat";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("chatApi", () => {
  it("lists conversations through the BFF proxy", async () => {
    await chatApi.listConversations();
    expect(api.get).toHaveBeenCalledWith("/chat/conversations", {});
  });

  it("passes list params through", async () => {
    await chatApi.listConversations({ limit: 20, offset: 40, archived: false });
    expect(api.get).toHaveBeenCalledWith("/chat/conversations", { limit: 20, offset: 40, archived: false });
  });

  it("gets one conversation", async () => {
    await chatApi.getConversation("c1");
    expect(api.get).toHaveBeenCalledWith("/chat/conversations/c1");
  });

  it("encodes the conversation id in the path", async () => {
    await chatApi.getConversation("a/b?c");
    expect(api.get).toHaveBeenCalledWith("/chat/conversations/a%2Fb%3Fc");
  });

  it("creates with machine context", async () => {
    await chatApi.createConversation({ machine_id: "m1" });
    expect(api.post).toHaveBeenCalledWith("/chat/conversations", { machine_id: "m1" });
  });

  it("creates without machine context", async () => {
    await chatApi.createConversation();
    expect(api.post).toHaveBeenCalledWith("/chat/conversations", {});
  });

  it("patches title", async () => {
    await chatApi.patchConversation("c1", { title: "Kiểm kê" });
    expect(api.patch).toHaveBeenCalledWith("/chat/conversations/c1", { title: "Kiểm kê" });
  });

  it("patches machine context to null to detach", async () => {
    await chatApi.patchConversation("c1", { machine_id: null });
    expect(api.patch).toHaveBeenCalledWith("/chat/conversations/c1", { machine_id: null });
  });

  it("deletes a conversation", async () => {
    await chatApi.deleteConversation("c1");
    expect(api.delete).toHaveBeenCalledWith("/chat/conversations/c1");
  });

  it("cancels a turn", async () => {
    await chatApi.cancelTurn("c1", "t1");
    expect(api.post).toHaveBeenCalledWith("/chat/conversations/c1/cancel", { turn_id: "t1" });
  });
});