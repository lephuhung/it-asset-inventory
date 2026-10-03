/**
 * Regression tests cho ChatRail — MOUNT THẬT, đây là lớp mà bộ test cũ không
 * chạm tới (chỉ renderToString shell đóng). Ở đây bắt được các bug reviewer
 * tìm ra: first-send mất câu hỏi, race lịch sử giữa các hội thoại, và nút "Gỡ"
 * ngữ cảnh không thật sự gỡ.
 *
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor, cleanup, fireEvent } from "@testing-library/react";

// jsdom không cài scrollTo — rail gọi nó để cuộn xuống đáy khi có token mới.
beforeEach(() => {
  Element.prototype.scrollTo = function scrollTo() {};
  // jsdom không có matchMedia; rail dùng để biết docked hay drawer.
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

const authState = { user: null as unknown };
vi.mock("@/components/auth-context", () => ({ useAuth: () => authState }));

let pathname = "/dashboard";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));

import { api } from "@/lib/api";
import { chatApi } from "@/lib/chat";
import { ChatRail } from "@/components/chat/chat-rail";
import type { ChatConversation, ChatConversationDetail, SessionUser } from "@/lib/types";

const enc = new TextEncoder();
const frame = (d: Record<string, unknown>) => `event: ${d.type}\ndata: ${JSON.stringify(d)}\n\n`;

function superAdmin(): SessionUser {
  return {
    id: "u1",
    email: "a@b.c",
    full_name: "A B",
    role: "super_admin",
    org_id: "o1",
    is_2fa_enabled: false,
    must_change_password: false,
  };
}

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

function detail(over: Partial<ChatConversationDetail> = {}): ChatConversationDetail {
  return { ...conv(), messages: [], active_turn_id: null, ...over };
}

/** Mở rail (localStorage đã set sẵn nên useSyncExternalStore đọc được ngay). */
async function openRail(): Promise<void> {
  window.localStorage.setItem("chat-rail-open", "true");
  render(<ChatRail />);
  await act(async () => {
    await Promise.resolve();
  });
}

function typeAndSend(text: string): void {
  const box = screen.getByLabelText("Nội dung câu hỏi") as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Gửi câu hỏi"));
}

beforeEach(() => {
  window.localStorage.clear();
  pathname = "/dashboard";
  authState.user = superAdmin();
  vi.spyOn(chatApi, "listConversations").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(chatApi, "getConversation").mockResolvedValue(detail());
  vi.spyOn(chatApi, "deleteConversation").mockResolvedValue(undefined);
  vi.spyOn(chatApi, "createConversation").mockResolvedValue(conv({ id: "c-new" }));
  vi.spyOn(chatApi, "patchConversation").mockResolvedValue(conv());
  vi.mocked(api.get).mockResolvedValue({} as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Stream token bình thường rồi đóng. */
function okStream(text = "Có 3 máy."): Response {
  return new Response(
    new ReadableStream({
      start(c) {
        c.enqueue(enc.encode(frame({ v: 1, seq: 1, type: "start", turn_id: "t1", message_id: "m1" })));
        c.enqueue(enc.encode(frame({ v: 1, seq: 2, type: "token", text })));
        c.enqueue(
          enc.encode(frame({ v: 1, seq: 3, type: "done", message_id: "m1", finish_reason: "stop" })),
        );
        c.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

describe("B1 — câu hỏi đầu tiên không được bị bỏ", () => {
  it("gửi được câu đầu tiên khi chưa có hội thoại nào", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await act(async () => {
      typeAndSend("máy nào quá hạn EOL?");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.content).toBe("máy nào quá hạn EOL?");
    expect(body.conversation_id).toBe("c-new");
  });

  it("ô nhập được xoá sau khi gửi thành công", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    await openRail();
    await act(async () => {
      typeAndSend("câu hỏi");
    });
    await waitFor(() => {
      expect((screen.getByLabelText("Nội dung câu hỏi") as HTMLTextAreaElement).value).toBe("");
    });
  });

  it("không tạo hội thoại mới nếu đã có hội thoại đang mở", async () => {
    const createSpy = vi.spyOn(chatApi, "createConversation");
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    // Chọn hội thoại đã có.
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("hỏi tiếp");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(createSpy).not.toHaveBeenCalled();
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string).conversation_id).toBe("c1");
  });

  it("tạo hội thoại mới thành công thì gửi tiếp, không nuốt câu hỏi", async () => {
    vi.spyOn(chatApi, "createConversation").mockResolvedValue(conv({ id: "c-new" }));
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await act(async () => {
      typeAndSend("xin chào");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });
});

describe("B3 — lịch sử không được lẫn giữa các hội thoại", () => {
  it("response chậm của hội thoại A không được ghi đè hội thoại B", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "A", title: "Hội thoại A" }), conv({ id: "B", title: "Hội thoại B" })],
      total: 2,
    });

    // A trả chậm, B trả nhanh.
    const getSpy = vi.spyOn(chatApi, "getConversation").mockImplementation(async (id) => {
      if (id === "A") {
        await new Promise((r) => setTimeout(r, 80));
        return detail({ id: "A", title: "Hội thoại A", messages: [
          { id: "a1", role: "user", content: "CÂU HỎI CỦA A", turn_id: "ta", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:00Z" },
        ] });
      }
      return detail({ id: "B", title: "Hội thoại B", messages: [
        { id: "b1", role: "user", content: "CÂU HỎI CỦA B", turn_id: "tb", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:00Z" },
      ] });
    });

    await openRail();

    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại A"));
    });
    // Chuyển sang B ngay, không đợi A xong.
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại B"));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(getSpy).toHaveBeenCalled();
    expect(screen.queryByText("CÂU HỎI CỦA A")).toBeNull();
    expect(screen.getByText("CÂU HỎI CỦA B")).toBeTruthy();
  });

  it("mở hội thoại khác phải xoá nội dung cũ ngay lập tức", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "A", title: "Hội thoại A" }), conv({ id: "B", title: "Hội thoại B" })],
      total: 2,
    });
    vi.mocked(chatApi.getConversation).mockImplementation(async (id) =>
      detail({
        id,
        title: id === "A" ? "Hội thoại A" : "Hội thoại B",
        messages: [
          {
            id: `${id}-1`,
            role: "user",
            content: id === "A" ? "CÂU HỎI CỦA A" : "CÂU HỎI CỦA B",
            turn_id: "t",
            machine_id: null,
            error_category: null,
            created_at: "2026-10-02T08:00:00Z",
          },
        ],
      }),
    );

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại A"));
    });
    await waitFor(() => expect(screen.getByText("CÂU HỎI CỦA A")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại B"));
    });
    await waitFor(() => expect(screen.queryByText("CÂU HỎI CỦA A")).toBeNull());
  });
});

describe("B5 — nút Gỡ phải gỡ thật", () => {
  it("bỏ chip khi người dùng bấm Gỡ, kể cả đang ở trang máy", async () => {
    pathname = "/machines/11111111-1111-4111-8111-111111111111";
    vi.mocked(api.get).mockResolvedValue({ hostname: "WS-01" } as never);

    await openRail();
    await waitFor(() => expect(screen.getByText(/Đang hỏi về:/)).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Gỡ ngữ cảnh/));

    await waitFor(() => {
      expect(screen.queryByText(/Đang hỏi về:/)).toBeNull();
    });
  });

  it("sau khi Gỡ, câu hỏi KHÔNG mang machine_context của trang", async () => {
    pathname = "/machines/11111111-1111-4111-8111-111111111111";
    vi.mocked(api.get).mockResolvedValue({ hostname: "WS-01" } as never);
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await waitFor(() => expect(screen.getByText(/Đang hỏi về:/)).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Gỡ ngữ cảnh/));
    await waitFor(() => expect(screen.queryByText(/Đang hỏi về:/)).toBeNull());

    await act(async () => {
      typeAndSend("hỏi chung");
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.machine_context).toBeUndefined();
  });

  it("không tự ghi machine_id vào hội thoại mới — chỉ Ghim mới lưu", async () => {
    pathname = "/machines/11111111-1111-4111-8111-111111111111";
    vi.mocked(api.get).mockResolvedValue({ hostname: "WS-01" } as never);
    const createSpy = vi.spyOn(chatApi, "createConversation");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));

    await openRail();
    await waitFor(() => expect(screen.getByText(/Đang hỏi về:/)).toBeTruthy());

    await act(async () => {
      typeAndSend("hỏi");
    });

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    // Ngữ cảnh là mềm → KHÔNG được ghim vào hội thoại khi tạo.
    expect(createSpy.mock.calls[0][0]).toEqual({});
  });

  it("bấm Ghim thì mới PATCH machine_id vào hội thoại", async () => {
    pathname = "/machines/11111111-1111-4111-8111-111111111111";
    vi.mocked(api.get).mockResolvedValue({ hostname: "WS-01" } as never);
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    const patchSpy = vi.spyOn(chatApi, "patchConversation");

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await waitFor(() => expect(screen.getByText(/Đang hỏi về:/)).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Ghim ngữ cảnh/));
    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith("c1", { machine_id: "11111111-1111-4111-8111-111111111111" });
    });
  });

  it("nút Ghim không bị kẹt vĩnh viễn sau khi PATCH lỗi", async () => {
    pathname = "/machines/11111111-1111-4111-8111-111111111111";
    vi.mocked(api.get).mockResolvedValue({ hostname: "WS-01" } as never);
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    vi.spyOn(chatApi, "patchConversation").mockRejectedValue(new Error("network"));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await waitFor(() => expect(screen.getByLabelText(/Ghim ngữ cảnh/)).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Ghim ngữ cảnh/));
    await waitFor(() => {
      expect((screen.getByLabelText(/Ghim ngữ cảnh/) as HTMLButtonElement).disabled).toBe(false);
    });
  });
});

describe("B6 — active_turn_id từ server", () => {
  it("mở hội thoại có turn đang chạy → hiện nút Dừng, khoá Gửi", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(
      detail({ id: "c1", active_turn_id: "turn-server" }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });

    await waitFor(() => {
      expect(screen.getByLabelText("Dừng trả lời")).toBeTruthy();
    });
    expect(screen.queryByLabelText("Gửi câu hỏi")).toBeNull();
  });

  it("bấm Dừng với turn từ server sẽ gọi đúng turn đó", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(
      detail({ id: "c1", active_turn_id: "turn-server" }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    const cancelSpy = vi.spyOn(chatApi, "cancelTurn").mockResolvedValue({ status: "canceled" });

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await waitFor(() => expect(screen.getByLabelText("Dừng trả lời")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Dừng trả lời"));
    });

    await waitFor(() => {
      expect(cancelSpy).toHaveBeenCalledWith("c1", "turn-server");
    });
  });
});

describe("render trùng lặp & retry", () => {
  it("câu trả lời đã persist không bị hiện 2 lần", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(
      detail({
        id: "c1",
        messages: [
          { id: "m0", role: "user", content: "hỏi gì", turn_id: "t0", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:00Z" },
          { id: "m1", role: "assistant", content: "Có 3 máy.", turn_id: "t1", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:01Z" },
        ],
      }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream("Có 3 máy.")));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("hỏi gì");
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });

    expect(screen.getAllByText("Có 3 máy.")).toHaveLength(1);
  });

  it("lỗi trước khi gửi được → nút Thử lại điền lại đúng câu vừa hỏi", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ category: "chat_budget_exceeded", hint: "Hết hạn mức.", retryable: true }), {
          status: 429,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    // Lịch sử KHÔNG có câu hỏi vừa gửi (lỗi xảy ra trước khi persist).
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1", messages: [] }));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("CÂU HỎI QUAN TRỌNG");
    });

    const retry = await screen.findByText("Thử lại câu hỏi vừa rồi");
    fireEvent.click(retry);

    await waitFor(() => {
      expect((screen.getByLabelText("Nội dung câu hỏi") as HTMLTextAreaElement).value).toBe("CÂU HỎI QUAN TRỌNG");
    });
  });

  it("hiển thị hint do server gửi kèm, không phải câu chữ chung chung", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ category: "chat_rate_limited", hint: "Bạn gửi hơi nhanh.", retryable: true }), {
          status: 429,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("hỏi");
    });

    await waitFor(() => {
      expect(screen.getAllByText(/Bạn gửi hơi nhanh\./).length).toBeGreaterThan(0);
    });
    // retryable từ server ⇒ vẫn hiện nút Thử lại dù status < 500.
    expect(screen.getByText("Thử lại câu hỏi vừa rồi")).toBeTruthy();
  });
});
describe("Regression vòng 2 — dấu vết tool, Enter, reset, ngữ cảnh theo hội thoại", () => {
  function toolStream(): Response {
    return new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(enc.encode(frame({ v: 1, seq: 1, type: "start", turn_id: "t1", message_id: "m1" })));
          c.enqueue(
            enc.encode(
              frame({ v: 1, seq: 2, type: "tool_start", tool_call_id: "tc1", tool: "inventory_search", params_digest: "d", summary: "s" }),
            ),
          );
          c.enqueue(
            enc.encode(
              frame({ v: 1, seq: 3, type: "tool_result", tool_call_id: "tc1", ok: true, row_count: 3, byte_count: null, duration_ms: 12 }),
            ),
          );
          c.enqueue(enc.encode(frame({ v: 1, seq: 4, type: "token", text: "Có 3 máy." })));
          c.enqueue(
            enc.encode(frame({ v: 1, seq: 5, type: "done", message_id: "m1", finish_reason: "stop" })),
          );
          c.close();
        },
      }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  }

  it("dấu vết tool KHÔNG biến mất sau khi lịch sử được nạp lại", async () => {
    // MessageOut không mang tools → nếu chỉ ẩn bản stream, chip tool sẽ mất.
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(
      detail({
        id: "c1",
        messages: [
          { id: "m0", role: "user", content: "kiểm tra", turn_id: "t0", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:00Z" },
          { id: "m1", role: "assistant", content: "Có 3 máy.", turn_id: "t1", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:01Z" },
        ],
      }),
    );
    const fetchMock = vi.fn().mockResolvedValue(toolStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("kiểm tra");
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(fetchMock).toHaveBeenCalled();
    // Chip tool vẫn còn, và câu trả lời chỉ hiện MỘT lần.
    expect(screen.getByText("inventory_search")).toBeTruthy();
    expect(screen.getAllByText("Có 3 máy.")).toHaveLength(1);
  });

  it("phím Enter không bypass được khoá khi server còn turn đang chạy", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1", active_turn_id: "turn-server" }));
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await waitFor(() => expect(screen.getByLabelText("Dừng trả lời")).toBeTruthy());

    const box = screen.getByLabelText("Nội dung câu hỏi");
    fireEvent.change(box, { target: { value: "câu cố gửi" } });
    await act(async () => {
      fireEvent.keyDown(box, { key: "Enter", shiftKey: false });
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Nội dung câu hỏi") as HTMLTextAreaElement).value).toBe("câu cố gửi");
  });

  it("tạo hội thoại mới sau khi mở turn đang chạy → không mượn nút Dừng của hội thoại cũ", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "c1", title: "Cũ" })],
      total: 1,
    });
    vi.mocked(chatApi.createConversation).mockResolvedValue(conv({ id: "c-new" }));
    vi.mocked(chatApi.getConversation).mockImplementation(async (id) =>
      id === "c1" ? detail({ id, active_turn_id: "turn-A" }) : detail({ id }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    const cancelSpy = vi.spyOn(chatApi, "cancelTurn").mockResolvedValue({ status: "canceled" });

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Cũ"));
    });
    await waitFor(() => expect(screen.getByLabelText("Dừng trả lời")).toBeTruthy());

    // Bấm "Cuộc trò chuyện mới".
    await act(async () => {
      fireEvent.click(screen.getByText("Cuộc trò chuyện mới"));
    });

    // Nút Dừng của turn-A không được mang sang hội thoại mới.
    await waitFor(() => {
      expect(screen.queryByLabelText("Dừng trả lời")).toBeNull();
    });
    expect(screen.getByLabelText("Gửi câu hỏi")).toBeTruthy();
    cancelSpy.mockClear();
  });

  it("xoá hội thoại đang mở không được xoá hội thoại người dùng vừa chuyển sang", async () => {
    let resolveDelete!: () => void;
    vi.spyOn(chatApi, "deleteConversation").mockReturnValue(
      new Promise<void>((res) => {
        resolveDelete = () => res();
      }) as never,
    );
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "A", title: "Hội A" }), conv({ id: "B", title: "Hội B" })],
      total: 2,
    });
    vi.mocked(chatApi.getConversation).mockImplementation(async (id) =>
      detail({ id, messages: [
        { id: `${id}-1`, role: "user", content: id === "A" ? "CÂU A" : "CÂU B", turn_id: "t", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:00Z" },
      ] }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội A"));
    });
    await waitFor(() => expect(screen.getByText("CÂU A")).toBeTruthy());

    // Xoá A nhưng CHƯA xong; trong lúc đó người dùng chuyển sang B.
    await act(async () => {
      fireEvent.click(screen.getByLabelText("Xoá hội thoại: Hội A"));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("Hội B"));
    });
    await act(async () => {
      resolveDelete();
      await new Promise((r) => setTimeout(r, 60));
    });

    // B vẫn phải còn nguyên.
    expect(screen.getByText("CÂU B")).toBeTruthy();
  });

  it("không ở trang máy + hội thoại đã ghim máy → gửi máy ĐÃ LƯU", async () => {
    // Spec L276: "Gỡ chip/reload/chuyển hội thoại → reset về machine_id đã lưu".
    pathname = "/dashboard";
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })] , total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(
      detail({ id: "c1", machine_id: "22222222-2222-4222-8222-222222222222" }),
    );
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });

    await act(async () => {
      typeAndSend("hỏi");
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    // Không có ngữ cảnh trang → dùng máy đã ghim của hội thoại.
    expect(body.machine_context.machine_id).toBe("22222222-2222-4222-8222-222222222222");
  });

  it("đang ở trang máy → máy đó là override per-turn kể cả khi hội thoại đã ghim máy khác", async () => {
    // Spec L273: "Đã có hội thoại → chip là override per-turn".
    pathname = "/machines/11111111-1111-4111-8111-111111111111";
    vi.mocked(api.get).mockResolvedValue({ hostname: "WS-TRANG" } as never);
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(
      detail({ id: "c1", machine_id: "22222222-2222-4222-8222-222222222222" }),
    );
    const fetchMock = vi.fn().mockResolvedValue(okStream());
    vi.stubGlobal("fetch", fetchMock);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await waitFor(() => expect(screen.getByText(/Đang hỏi về:/)).toBeTruthy());

    await act(async () => {
      typeAndSend("hỏi");
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.machine_context.machine_id).toBe("11111111-1111-4111-8111-111111111111");
  });

  it("cancel thất bại thì báo lỗi, không giả vờ đã dừng", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1", active_turn_id: "turn-server" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));
    vi.spyOn(chatApi, "cancelTurn").mockRejectedValue(new Error("500 Internal"));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await waitFor(() => expect(screen.getByLabelText("Dừng trả lời")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Dừng trả lời"));
    });

    await waitFor(() => {
      expect(screen.getByText("Không dừng được câu trả lời. Thử lại hoặc tải lại trang.")).toBeTruthy();
    });
    // Vẫn còn turn đang chạy → không được mở nút Gửi.
    expect(screen.getByLabelText("Dừng trả lời")).toBeTruthy();
  });
});


/** Stream chỉ phát `start` rồi treo — mô phỏng lúc model đang suy nghĩ (~5s thật). */
function thinkingStreamForTest(): Response {
  return new Response(
    new ReadableStream({
      start(c) {
        c.enqueue(enc.encode(frame({ v: "chat.sse/1", seq: 0, type: "start", turn_id: "t1", message_id: null })));
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

describe("Tab lịch sử / Tab chat", () => {
  it("mở rail thì đang ở tab Chat", async () => {
    await openRail();
    expect(screen.getByRole("tab", { name: /Chat/i }).getAttribute("aria-selected")).toBe("true");
  });

  it("bấm tab Lịch sử thì hiện danh sách và ẩn khung chat", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "c1", title: "Hội thoại cũ" })],
      total: 1,
    });
    await openRail();

    const historyTab = screen.getByRole("tab", { name: /Lịch sử/i });
    expect(historyTab.getAttribute("aria-selected")).toBe("false");

    await act(async () => {
      fireEvent.click(historyTab);
    });

    expect(screen.getByRole("tab", { name: /Lịch sử/i }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Hội thoại cũ")).toBeTruthy();
    // Khung chat bị ẨN (hidden) chứ không bị gỡ khỏi DOM: giữ nguyên câu đang gõ
    // dở và stream đang chạy khi người dùng xem lại lịch sử.
    expect(screen.getByLabelText("Nội dung câu hỏi")).toBeTruthy();
    expect(document.getElementById("chat-panel-chat")?.hasAttribute("hidden")).toBe(true);
    expect(document.getElementById("chat-panel-history")?.hasAttribute("hidden")).toBe(false);
  });

  it("chọn một hội thoại thì tự chuyển sang tab Chat", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "c1", title: "Hội thoại cũ" })],
      total: 1,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Lịch sử/i }));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại cũ"));
    });

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Chat/i }).getAttribute("aria-selected")).toBe("true");
    });
    expect(screen.getByLabelText("Nội dung câu hỏi")).toBeTruthy();
  });

  it("header hiện tên trợ lý và trạng thái kết nối", async () => {
    await openRail();
    expect(screen.getByRole("heading", { name: "Trợ lý tra cứu" })).toBeTruthy();
    expect(screen.getByText("Đã kết nối")).toBeTruthy();
    expect(screen.getByText("Chỉ SuperAdmin")).toBeTruthy();
  });

  it("lịch sử gom theo ngày (Hôm nay)", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [
        conv({ id: "a", title: "Hội A", last_message_at: new Date().toISOString() }),
        conv({ id: "b", title: "Hội B", last_message_at: new Date().toISOString() }),
      ],
      total: 2,
    });
    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Lịch sử/i }));
    });
    expect(screen.getByRole("heading", { name: "Hôm nay" })).toBeTruthy();
    expect(screen.getByText("Hội A")).toBeTruthy();
    expect(screen.getByText("Hội B")).toBeTruthy();
  });

  it("tab Lịch sử có badge số hội thoại", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      items: [conv({ id: "a" }), conv({ id: "b" })],
      total: 2,
    });
    await openRail();
    const historyTab = screen.getByRole("tab", { name: /Lịch sử/i });
    expect(historyTab.textContent).toContain("2");
  });
});

describe("Câu hỏi phải hiện ngay + báo đang suy nghĩ", () => {
  /** Stream treo: chỉ `start`, chưa có token — mô phỏng lúc model đang nghĩ. */
  function thinkingStream(): Response {
    return new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(enc.encode(frame({ v: "chat.sse/1", seq: 0, type: "start", turn_id: "t1", message_id: null })));
          // không enqueue token, không đóng → treo
        },
      }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  }

  it("hiện câu hỏi ngay khi vừa gửi, chưa cần câu trả lời", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    let release!: (v: Response) => void;
    const pending = new Promise<Response>((res) => {
      release = res;
    });
    vi.stubGlobal("fetch", vi.fn(() => pending) as unknown as typeof fetch);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("máy nào quá hạn EOL?");
    });

    // Stream còn treo, lịch sử chưa kịp nạp — câu hỏi vẫn phải thấy.
    await waitFor(() => {
      expect(screen.getAllByText("máy nào quá hạn EOL?").length).toBeGreaterThan(0);
    });

    await act(async () => {
      release(okStream());
      await pending;
    });
  });

  it("báo 'Đang suy nghĩ…' khi stream chưa có token nào", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(thinkingStream()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });

    await waitFor(() => {
      expect(screen.getByText(/Đang suy nghĩ/)).toBeTruthy();
    });
  });

  it("ẩn 'Đang suy nghĩ…' khi token đầu tiên về", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(screen.queryByText(/Đang suy nghĩ/)).toBeNull();
  });

  it("không hiện câu hỏi hai lần sau khi lịch sử nạp lại", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    // Lúc mở hội thoại thì lịch sử trống; sau khi gửi, backend đã persist cả
    // câu hỏi lẫn câu trả lời (user persist ngay khi claim turn).
    // Lần gọi đầu (mở hội thoại) thì lịch sử còn trống; các lần sau đã có dữ liệu.
    let calls = 0;
    vi.mocked(chatApi.getConversation).mockImplementation(async (id) =>
      calls++ > 0
        ? detail({
            id,
            messages: [
              { id: "m0", role: "user", content: "câu hỏi", turn_id: "t0", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:00Z" },
              { id: "m1", role: "assistant", content: "Có 3 máy.", turn_id: "t1", machine_id: null, error_category: null, created_at: "2026-10-02T08:00:01Z" },
            ],
          })
        : detail({ id }),
    );
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okStream()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(screen.getAllByText("câu hỏi")).toHaveLength(1);
    expect(screen.getAllByText("Có 3 máy.")).toHaveLength(1);
  });

  it("câu hỏi vẫn còn khi stream báo lỗi", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ category: "chat_upstream_llm", hint: "Mô hình đang bận.", retryable: true }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi bị lỗi");
    });

    await waitFor(() => {
      expect(screen.getAllByText("câu hỏi bị lỗi").length).toBeGreaterThan(0);
    });
    // Banner lỗi hiện ở khung chat...
    const banner = document.querySelector("p.bg-red-50");
    expect(banner?.textContent).toContain("chat_upstream_llm");
    expect(banner?.textContent).toContain("Mô hình đang bận");
    // ...và vùng aria-live thông báo lại cho trình đọc màn hình (cố ý trùng nội dung).
    const live = document.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain("Mô hình đang bận");
  });
});

describe("Chỉ báo trong lúc chờ — phải nói đúng đang làm gì", () => {
  /** Stream: start → tool_start → tool_result rồi TREO (chờ token, mất ~20s thật). */
  function afterToolsStream(): Response {
    return new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(enc.encode(frame({ v: "chat.sse/1", seq: 0, type: "start", turn_id: "t1", message_id: null })));
          c.enqueue(enc.encode(frame({ v: "chat.sse/1", seq: 1, type: "tool_start", tool_call_id: "tc1", tool: "inventory_software", params_digest: "d", summary: "s" })));
          c.enqueue(enc.encode(frame({ v: "chat.sse/1", seq: 2, type: "tool_result", tool_call_id: "tc1", ok: true, row_count: 5, byte_count: null, duration_ms: 20 })));
          // chưa có token → treo
        },
      }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  }

  it("chờ token đầu tiên → 'Đang suy nghĩ…'", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(thinkingStreamForTest()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });

    await waitFor(() => expect(screen.getByText(/Đang suy nghĩ/)).toBeTruthy());
  });

  it("tool đã xong nhưng token chưa về → 'Đang soạn câu trả lời…'", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(afterToolsStream()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("thống kê phần mềm");
    });

    await waitFor(() => expect(screen.getByText(/Đang soạn câu trả lời/)).toBeTruthy());
    // Chip tool vẫn hiện — người dùng thấy tiến độ.
    expect(screen.getByText("inventory_software")).toBeTruthy();
  });
});

describe("Không được hiện bong bóng rỗng khi chưa có chữ", () => {
  it("đang suy nghĩ thì KHÔNG có bong bóng trợ lý rỗng", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(thinkingStreamForTest()));

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });

    await waitFor(() => expect(screen.getByText(/Đang suy nghĩ/)).toBeTruthy());
    // Chỉ có chỉ báo, KHÔNG có bong bóng trợ lý nào cả (kể cả bong bóng rỗng).
    expect(document.querySelectorAll('[data-role="assistant"]').length).toBe(0);
    // Câu hỏi của người dùng thì đã hiện.
    expect(document.querySelectorAll('[data-role="user"]').length).toBe(1);
  });

  it("token đầu tiên về thì bong bóng mới xuất hiện, kèm chữ", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    let release!: (v: Response) => void;
    const pending = new Promise<Response>((res) => {
      release = res;
    });
    vi.stubGlobal("fetch", vi.fn(() => pending) as unknown as typeof fetch);

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });
    await waitFor(() => expect(screen.getByText(/Đang suy nghĩ/)).toBeTruthy());
    expect(document.querySelectorAll('[data-role="assistant"]').length).toBe(0);

    // Token đầu tiên đến.
    await act(async () => {
      release(okStream("Câu trả lời"));
      await pending;
    });

    await waitFor(() => {
      expect(document.querySelectorAll('[data-role="assistant"]').length).toBe(1);
    });
    expect(screen.getByText(/Câu trả lời/)).toBeTruthy();
    expect(screen.queryByText(/Đang suy nghĩ/)).toBeNull();
  });

  it("bong bóng rỗng cũng không xuất hiện khi stream lỗi trước khi có chữ", async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({ items: [conv({ id: "c1" })], total: 1 });
    vi.mocked(chatApi.getConversation).mockResolvedValue(detail({ id: "c1" }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ category: "chat_upstream_llm", hint: "Mô hình đang bận.", retryable: true }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await openRail();
    await act(async () => {
      fireEvent.click(screen.getByText("Hội thoại mới"));
    });
    await act(async () => {
      typeAndSend("câu hỏi");
    });

    await waitFor(() => {
      expect(document.querySelector("p.bg-red-50")).toBeTruthy();
    });
    // Lỗi thì hiện banner, KHÔNG hiện bong bóng trợ lý rỗng.
    expect(document.querySelectorAll('[data-role="assistant"]').length).toBe(0);
  });
});
