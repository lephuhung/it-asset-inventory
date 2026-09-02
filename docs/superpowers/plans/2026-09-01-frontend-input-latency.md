# Frontend Input Latency Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Loại bỏ độ trễ khi nhập prompt/chat điều tra AI và ngăn các ô tìm kiếm gọi API theo từng ký tự.

**Architecture:** Đưa state nhập liệu của prompt AI và chat vào component con để thay đổi text không làm render lại page lớn. Tách parser Markdown thành component memoized, sau đó debounce + hủy/bỏ qua request cũ ở các ô tìm kiếm từ xa. Tối ưu các phép tính chạy trong render của trang Tokens mà không thay đổi API contract.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, Fetch API, không thêm dependency.

**Spec:** `docs/superpowers/specs/2026-09-01-frontend-input-latency-design.md`

## Global Constraints

- Không thay đổi endpoint, payload, quyền hạn, text nghiệp vụ hoặc backend contract.
- Không thêm dependency mới.
- API tạo investigation chỉ gọi khi bấm “Bắt đầu điều tra”.
- API chat chỉ gọi khi bấm “Gửi” hoặc Ctrl/Cmd+Enter.
- Search API chỉ chạy sau khoảng 350ms người dùng ngừng gõ.
- Request tìm kiếm cũ phải bị hủy hoặc kết quả lỗi thời phải bị bỏ qua.
- Giữ nguyên prompt khi đóng/mở modal trong cùng lần mount.
- Không đụng vào các thay đổi chưa commit ở `server/` và `deepagent/`.

---

### Task 1: Tách modal nhập yêu cầu điều tra AI khỏi MachineDetailPage

**Files:**
- Create: `portal/components/investigation-prompt-modal.tsx`
- Modify: `portal/app/(portal)/machines/[id]/page.tsx:342-347,590-600,1247-1262`

**Interfaces:**
- Consumes: `Modal`, `Button`, `Field`, `Textarea`, `DfirInvestigation`, `machine.hostname`, `llmBusy`, `llmError`.
- Produces: `InvestigationPromptModalProps` và callback `onSubmit(instructions: string)`.

- [ ] **Step 1: Tạo component với state local**

Tạo interface và component theo contract:

```tsx
export interface InvestigationPromptModalProps {
  open: boolean;
  machineHostname: string | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (instructions: string) => void;
}
```

Trong component dùng `useState("")` cho `instructions`. Render `Modal` luôn khi component được mount, truyền `open={open}`. Đặt `Textarea` controlled bởi state local:

```tsx
const [instructions, setInstructions] = useState("");

<Textarea
  value={instructions}
  onChange={(event) => setInstructions(event.target.value)}
  placeholder="Ví dụ: nghi ngờ PowerShell thực thi bất thường trong 24 giờ gần đây"
  rows={5}
/>
```

Nút “Bắt đầu điều tra” gọi `onSubmit(instructions.trim())`; không gọi API trực tiếp trong component. Giữ nguyên nội dung sau khi đóng/mở bằng cách không reset state khi `open` đổi. Hiển thị `error` và khóa/loading nút khi `busy`.

- [ ] **Step 2: Chạy typecheck sau khi tạo component**

Run: `cd portal && npm run typecheck`

Expected: PASS; component mới chưa được import vẫn không tạo lỗi TypeScript.

- [ ] **Step 3: Đổi MachineDetailPage nhận prompt qua callback**

Xóa state `investigationInstructions` và state `llmInvestigationId` nếu không còn nơi đọc. Đổi hàm thành:

```tsx
const investigateWithAI = async (customInstructions: string) => {
  if (!machine) return;
  setLlmBusy(true);
  setLlmError(null);
  try {
    const inv = await api.post<DfirInvestigation>("/admin/llm-dfir/investigations", {
      machine_id: machine.id,
      artifacts: null,
      custom_instructions: customInstructions || null,
    });
    window.location.href = `/admin/llm-dfir/investigations/${inv.id}`;
  } catch (e) {
    setLlmError(e instanceof Error ? e.message : "Tạo investigation thất bại");
  } finally {
    setLlmBusy(false);
  }
};
```

Thay block modal cũ bằng component luôn được mount:

```tsx
<InvestigationPromptModal
  open={showInvestigationModal}
  machineHostname={machine.hostname}
  busy={llmBusy}
  error={llmError}
  onClose={() => setShowInvestigationModal(false)}
  onSubmit={(instructions) => void investigateWithAI(instructions)}
/>
```

Giữ callback `onInvestigateAI={() => setShowInvestigationModal(true)}` trong `VelociraptorLiveCard`.

- [ ] **Step 4: Kiểm tra hành vi modal và build**

Run:

```bash
cd portal && npm run typecheck && npm run build
```

Expected: cả hai lệnh thành công. Manual check: mở modal, nhập 20 ký tự, đóng/mở lại thấy nội dung còn nguyên; Network không có request khi gõ.

- [ ] **Step 5: Commit riêng phần modal**

```bash
git add portal/components/investigation-prompt-modal.tsx 'portal/app/(portal)/machines/[id]/page.tsx'
git commit -m "perf(portal): isolate AI investigation prompt input"
```

---

### Task 2: Tách chat investigation và memoize Markdown rendering

**Files:**
- Create: `portal/components/investigation-markdown.tsx`
- Create: `portal/components/investigation-chat-panel.tsx`
- Modify: `portal/app/(portal)/llm-dfir/investigations/[id]/page.tsx:30-115,135-220,400-480`

**Interfaces:**
- Consumes: `DfirInvestigationMessage[]`, `InvestigationStatus`, investigation ID và callback gửi message.
- Produces: `InvestigationMarkdown({ content })` và `InvestigationChatPanel` với state `chatInput`/`chatting` local.

- [ ] **Step 1: Di chuyển parser Markdown vào component memoized**

Tạo `InvestigationMarkdown` nhận:

```tsx
export const InvestigationMarkdown = memo(function InvestigationMarkdown({
  content,
}: {
  content: string;
}) {
  return <div>{parseMarkdown(content)}</div>;
});
```

Di chuyển nguyên logic `renderMarkdown` và `formatInline` hiện có từ detail page sang file này, giữ nguyên output HTML/class. Không dùng `ReactMarkdown` mới và không thay đổi nội dung report.

- [ ] **Step 2: Tạo `InvestigationChatPanel` với input state local**

Dùng interface:

```tsx
interface InvestigationChatPanelProps {
  investigationId: string;
  status: InvestigationStatus;
  messages: DfirInvestigationMessage[];
  onSend: (message: string) => Promise<void>;
}
```

Component phải:

- giữ `chatInput` và `chatting` bằng `useState` nội bộ;
- giữ auto-scroll `chatEndRef` nội bộ;
- render nguyên layout Card “Hỏi tiếp AI” hiện tại;
- gọi `onSend(chatInput.trim())` khi click hoặc Ctrl/Cmd+Enter;
- xóa input sau khi bắt đầu gửi;
- dùng `<InvestigationMarkdown content={m.content} />` cho assistant message;
- export bằng `memo` để parent rerender không dựng lại chat khi props không đổi.

Không gọi API trực tiếp trong component; callback parent tiếp tục chịu trách nhiệm optimistic message và endpoint `/admin/llm-dfir/investigations/{id}/chat`.

- [ ] **Step 3: Đổi callback gửi chat ở detail page**

Xóa `chatInput` và `chatting` khỏi detail page. Đổi hàm gửi thành:

```tsx
const sendChat = async (msg: string) => {
  if (!msg || !inv) return;
  setMessages((current) => [
    ...current,
    {
      id: `tmp-${Date.now()}`,
      role: "user",
      content: msg,
      tokens: null,
      created_at: new Date().toISOString(),
    },
  ]);
  try {
    const res = await api.post<{ response: string; model: string }>(
      `/admin/llm-dfir/investigations/${id}/chat`,
      { message: msg },
    );
    setMessages((current) => [
      ...current,
      {
        id: `tmp-${Date.now()}-r`,
        role: "assistant",
        content: res.response,
        tokens: null,
        created_at: new Date().toISOString(),
      },
    ]);
  } catch (e) {
    setError(e instanceof Error ? e.message : "Chat lỗi");
  }
};
```

Thay report bằng `InvestigationMarkdown` và thay toàn bộ Card chat cũ bằng:

```tsx
<InvestigationChatPanel
  investigationId={id}
  status={inv.status}
  messages={messages}
  onSend={sendChat}
/>
```

Giữ `load()` và polling 5 giây như cũ; chỉ thay đổi nơi lưu state nhập liệu và rendering.

- [ ] **Step 4: Typecheck/build và kiểm tra parse Markdown**

Run:

```bash
cd portal && npm run typecheck && npm run build
```

Expected: PASS. Manual check: trên investigation đã có report dài, gõ liên tục vào chat; report không bị nhấp nháy và không có request chat trước khi bấm gửi.

- [ ] **Step 5: Commit riêng phần chat**

```bash
git add portal/components/investigation-markdown.tsx portal/components/investigation-chat-panel.tsx 'portal/app/(portal)/llm-dfir/investigations/[id]/page.tsx'
git commit -m "perf(portal): isolate investigation chat rendering"
```

---

### Task 3: Debounce và hủy request ở remote search

**Files:**
- Create: `portal/lib/use-debounced-value.ts`
- Modify: `portal/lib/api.ts:44-79`
- Modify: `portal/app/(portal)/machines/page.tsx:123-180`
- Modify: `portal/app/(portal)/audit/page.tsx:53-99`
- Modify: `portal/app/(portal)/admin/telegram-bot/page.tsx:107-134`

**Interfaces:**
- Consumes: Fetch `AbortSignal`, raw search state.
- Produces: `useDebouncedValue<T>(value, delayMs): T` và `api.get(path, params, { signal })`.

- [ ] **Step 1: Tạo hook debounce**

Tạo file:

```tsx
import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
```

- [ ] **Step 2: Cho phép `api.get` nhận AbortSignal**

Mở rộng `request` để nhận `RequestInit` hiện có và truyền `signal` vào `fetch`. Mở rộng riêng signature GET mà không phá call site cũ:

```ts
get<T>(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
  options?: Pick<RequestInit, "signal">,
): Promise<T>
```

Trong `api.get`, gọi `request(pathWithQuery, options)`. Các method khác giữ nguyên.

- [ ] **Step 3: Debounce `/machines` và hủy request trước**

Trong `MachinesPage`:

```tsx
const debouncedQ = useDebouncedValue(q, 350);
const searchAbortRef = useRef<AbortController | null>(null);
```

Đổi `load` dùng `debouncedQ` thay cho raw `q`, thêm abort trước request:

```tsx
searchAbortRef.current?.abort();
const controller = new AbortController();
searchAbortRef.current = controller;
const data = await api.get<PageResponse<MachineListItem>>("/machines", params, {
  signal: controller.signal,
});
```

Catch `AbortError` im lặng; cleanup effect abort controller khi rời trang. Dependency của `load` dùng `debouncedQ`, không dùng `q`. Nút “Áp dụng” vẫn gọi `load(false, 0)` và hành vi filter không đổi.

- [ ] **Step 4: Debounce `/audit`**

Tạo `debouncedQ` và `debouncedActor` với 350ms. `load` dùng hai giá trị debounced; effect reset offset vẫn theo raw `q`/`actor`, nhưng không phát request cho từng ký tự. Dùng `AbortController` tương tự Machines và bỏ qua `AbortError`.

- [ ] **Step 5: Debounce Telegram linked-users**

Tạo `debouncedLinkedQ = useDebouncedValue(linkedQ, 350)`. Effect load linked users phụ thuộc `debouncedLinkedQ`, `linkedOffset`, `isSuperAdmin`; truyền `debouncedLinkedQ` vào `loadLinked`. Hủy request trước trong `loadLinked` và không log warning cho `AbortError`.

- [ ] **Step 6: Kiểm tra số request và race condition**

Run:

```bash
cd portal && npm run typecheck && npm run build
```

Manual check trong DevTools Network:

1. `/machines`: gõ `PC-042` liên tục → tối đa một request sau 350ms.
2. `/audit`: gõ vào `q` và `actor` → không có request từng ký tự.
3. Telegram: gõ linked-user search → request trước bị canceled hoặc không cập nhật UI sau khi đã lỗi thời.

- [ ] **Step 7: Commit phần remote search**

```bash
git add portal/lib/use-debounced-value.ts portal/lib/api.ts 'portal/app/(portal)/machines/page.tsx' 'portal/app/(portal)/audit/page.tsx' 'portal/app/(portal)/admin/telegram-bot/page.tsx'
git commit -m "perf(portal): debounce remote search inputs"
```

---

### Task 4: Giảm chi phí render lặp lại ở Tokens page

**Files:**
- Modify: `portal/app/(portal)/tokens/page.tsx:1-20,172-210,255-274,368,554,627,712`

**Interfaces:**
- Consumes: `csvText`, `orgs`, sessionStorage command map.
- Produces: `parsedCsv`, `flatOrgs`, `commands` ổn định giữa các lần render.

- [ ] **Step 1: Memoize danh sách organization và tag options**

Thêm `useMemo` vào import và tạo:

```tsx
const flatOrgs = useMemo(() => flattenOrgTree(orgs), [orgs]);
const classificationTags = useMemo(
  () => tags.filter((t) => t.kind === "classification"),
  [tags],
);
const purposeTagOptions = useMemo(
  () => tags.filter((t) => t.kind === "purpose"),
  [tags],
);
```

Thay ba lần `flattenOrgTree(orgs)` bằng `flatOrgs`.

- [ ] **Step 2: Memoize parse CSV**

Giữ hàm parse hiện tại nhưng tạo kết quả một lần theo `csvText`:

```tsx
const parsedCsv = useMemo(() => parseCsv(csvText), [csvText]);
```

Dùng `parsedCsv` trong `importCsv` và hiển thị số dòng thay cho gọi `parseCsv(csvText)` trực tiếp trong JSX. Không parse CSV khi các state khác thay đổi.

- [ ] **Step 3: Không đọc sessionStorage trong mỗi render**

Đổi:

```tsx
const commands = loadCommands();
```

thành:

```tsx
const [commands, setCommands] = useState<Record<string, string>>({});
useEffect(() => {
  setCommands(loadCommands());
}, []);
```

Sau khi `saveCommand` chạy ở `create` hoặc `reissue`, cập nhật `commands` bằng map mới đọc từ `loadCommands()` để nút Copy vẫn hoạt động mà không đọc storage trong render.

- [ ] **Step 4: Kiểm tra regression**

Run:

```bash
cd portal && npm run typecheck && npm run build
```

Manual check: nhập vào các field tạo token và textarea CSV; nội dung không mất, số dòng CSV vẫn cập nhật đúng, các select organization và nút Copy vẫn hoạt động.

- [ ] **Step 5: Commit tối ưu Tokens**

```bash
git add 'portal/app/(portal)/tokens/page.tsx'
git commit -m "perf(portal): memoize token form derived data"
```

---

### Task 5: Verification cuối và kiểm tra không làm ảnh hưởng thay đổi có sẵn

**Files:**
- No source changes expected.

- [ ] **Step 1: Chạy toàn bộ kiểm tra Portal**

Run:

```bash
cd portal && npm run typecheck && npm run build
```

Expected: typecheck và production build đều PASS.

- [ ] **Step 2: Kiểm tra diff chỉ thuộc Portal/performance**

Run:

```bash
git status --short
git diff --stat HEAD~4..HEAD
```

Xác nhận không có file `server/` hoặc `deepagent/` bị đưa vào commit của kế hoạch này; các thay đổi backend/deepagent vốn đã tồn tại phải được giữ nguyên.

- [ ] **Step 3: Chạy acceptance test thủ công**

Trong browser DevTools:

- Prompt AI: nhập liên tục 20 ký tự → không có request mạng; chỉ modal cập nhật.
- Chat investigation: nhập liên tục vào chat → không gọi endpoint chat; report không parse lại theo từng ký tự.
- Machines/Audit/Telegram search: dừng gõ 350ms → một request cho giá trị cuối; response cũ không ghi đè kết quả mới.
- Đóng/mở prompt modal → nội dung vẫn còn trong cùng lần mount.

- [ ] **Step 4: Ghi nhận kết quả trước khi hoàn tất**

Báo cáo các lệnh đã chạy, số request quan sát được và bất kỳ residual risk nào nếu dữ liệu inventory/report cực lớn vẫn vượt ngân sách frame 16ms.
