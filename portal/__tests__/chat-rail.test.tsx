import { describe, it, expect, vi } from "vitest";
import { renderToString } from "react-dom/server";

const authState = { user: null as unknown, loading: false };

vi.mock("@/components/auth-context", () => ({
  useAuth: () => authState,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

import { ChatRail } from "@/components/chat/chat-rail";
import type { SessionUser } from "@/lib/types";

function user(over: Partial<SessionUser> = {}): SessionUser {
  return {
    id: "u1",
    email: "a@b.c",
    full_name: "A B",
    role: "super_admin",
    org_id: "o1",
    is_2fa_enabled: false,
    must_change_password: false,
    ...over,
  };
}

function render(): string {
  return renderToString(<ChatRail />);
}

describe("ChatRail role gate", () => {
  it("renders nothing for a non-super-admin", () => {
    authState.user = user({ role: "org_admin" });
    expect(render()).toBe("");
  });

  it("renders nothing for a viewer", () => {
    authState.user = user({ role: "viewer" });
    expect(render()).toBe("");
  });

  it("renders nothing while there is no session", () => {
    authState.user = null;
    expect(render()).toBe("");
  });

  it("renders a toggle for super_admin", () => {
    authState.user = user({ role: "super_admin" });
    expect(render()).toContain("aria-label");
  });

  it("accepts the legacy admin_global role as super admin", () => {
    authState.user = user({ role: "admin_global" });
    const html = render();
    expect(html).not.toBe("");
  });

  it("renders no chat copy at all for a non-super-admin", () => {
    authState.user = user({ role: "org_admin" });
    const html = render();
    expect(html).not.toContain("Trợ lý");
    expect(html).not.toContain("Hội thoại");
  });
});

describe("ChatRail shell", () => {
  it("starts closed on the server and renders only the open affordance", () => {
    // SSR snapshot của localStorage là `false` → không được render panel.
    authState.user = user();
    const html = render();
    expect(html).toContain("Mở trợ lý tra cứu");
    expect(html).not.toContain("Cuộc trò chuyện mới");
    expect(html).not.toContain("Gửi câu hỏi");
  });

  it("docks the closed affordance as a floating button, not a modal", () => {
    authState.user = user();
    const html = render();
    expect(html).toContain("fixed");
    expect(html).toContain("rounded-full");
  });

  it("tells assistive tech the panel is collapsed", () => {
    authState.user = user();
    expect(render()).toContain('aria-expanded="false"');
  });

  it("mounts no dialog/overlay when closed", () => {
    authState.user = user();
    const html = render();
    expect(html).not.toContain('role="dialog"');
    expect(html).not.toContain("aria-modal");
  });
});