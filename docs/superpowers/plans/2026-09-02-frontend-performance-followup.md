# Frontend Performance Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Sửa các bottleneck frontend còn lại đã được MiniMax M3 phát hiện và GPT 5.6 Luna xác nhận, tập trung vào input latency, modal/scroll jank, request fan-out và refresh chồng nhau.

**Architecture:** Giữ nguyên các endpoint và contract hiện tại, chỉ điều chỉnh lifecycle ở client. Tách state/render hot path khỏi draft input, dùng controller/throttle để quản lý request, và memoize dữ liệu dẫn xuất có chi phí đáng kể. Các findings false-positive đã được loại khỏi implementation scope.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Fetch API, Tailwind CSS 4, không thêm dependency.

**Spec:** `docs/superpowers/specs/2026-09-02-frontend-performance-followup-design.md`

**Audit evidence:** `docs/superpowers/handoffs/2026-09-01-frontend-performance-luna-review.md`

## Global Constraints

- Không sửa `server/`, `deepagent/` hoặc các thay đổi chưa commit ngoài phạm vi `portal/`.
- Không thay đổi endpoint, HTTP method, payload, quyền hạn, API response contract hoặc text nghiệp vụ.
- Không thêm dependency mới.
- Search text tiếp tục debounce 350ms; API không gọi theo từng ký tự.
- Request cũ phải bị abort hoặc stale-result guard; response cũ không được ghi đè UI mới.
- Giữ nguyên hành vi pagination, filter, retry, loading và nút thao tác hiện tại trừ các lỗi được nêu rõ trong task.
- Nếu cần commit, chỉ stage đúng các file trong task; tuyệt đối không stage `server/` hoặc `deepagent/`.
- Portal hiện không có test runner riêng; mỗi task dùng regression check Node/browser DevTools và kết thúc bằng typecheck/build.

---

### Task 1: Sửa Audit filter dead-end khi đang ở page > 1

**Files:**
- Modify: `portal/app/(portal)/audit/page.tsx:57-150`
- Test: regression check bằng Node inline và Chrome Network/interaction check

**Interfaces:**
- Consumes: `q`, `actor`, `action`, `offset`, `debouncedQ`, `debouncedActor`, `skipNextLoadRef`, `rawSearchRef` hiện có.
- Produces: sau khi filter debounced ổn định, `load()` được gọi đúng một lần với offset 0; khi offset reset, request trung gian với filter cũ bị bỏ qua.

- [ ] **Step 1: Tạo regression check đỏ cho state transition**

Chạy từ repository root trước khi sửa:

```bash
node <<'NODE'
const fs = require("fs");
const source = fs.readFileSync("portal/app/(portal)/audit/page.tsx", "utf8");
const required = "skipNextLoadRef.current = false;\n      void load();";
if (source.includes(required)) {
  throw new Error("RED check unexpectedly passes before the Audit fix");
}
console.log("RED: Audit debounced-reset branch does not load yet");
NODE
```

Expected: process exit 0 với dòng `RED...`; nếu source đã chứa branch đúng thì kiểm tra lại diff trước khi tiếp tục.

- [ ] **Step 2: Sửa nhánh clear skip flag**

Trong effect auto-load, giữ nguyên guard chờ raw search khớp debounced, nhưng gọi `load()` ngay sau khi clear cờ:

```tsx
useEffect(() => {
  if (skipNextLoadRef.current) {
    if (
      rawSearchRef.current.q !== debouncedQ ||
      rawSearchRef.current.actor !== debouncedActor
    ) {
      return;
    }
    skipNextLoadRef.current = false;
    void load();
    return;
  }
  void load();
}, [load]);
```

Không thêm `q` hoặc `actor` vào dependency array của effect này; nếu thêm, raw keystroke sẽ tự gọi API và phá debounce.

- [ ] **Step 3: Chạy regression check xanh**

```bash
node <<'NODE'
const fs = require("fs");
const source = fs.readFileSync("portal/app/(portal)/audit/page.tsx", "utf8");
const required = "skipNextLoadRef.current = false;\n    void load();";
if (!source.includes(required)) {
  throw new Error("Audit reset branch still does not call load()");
}
console.log("Audit reset regression check passed");
NODE
```

- [ ] **Step 4: Manual behavior check**

1. Mở `/audit`, chuyển tới page 2 hoặc 3.
2. Nhập vào `q` hoặc `actor` liên tục.
3. Trong Network xác nhận không có request cho từng ký tự, sau khoảng 350ms có request `/api/proxy/audit` với filter mới và `offset=0`.
4. Xóa filter và lặp lại; danh sách phải cập nhật, không cần đổi page.

- [ ] **Step 5: Verify task**

```bash
cd portal && npm run typecheck
```

- [ ] **Step 6: Commit scoped change (optional)**

```bash
git add 'portal/app/(portal)/audit/page.tsx'
git commit -m "fix(portal): reload audit results after debounced filter reset"
```

---

### Task 2: Giảm fan-out và chống load chồng ở EOL

**Files:**
- Modify: `portal/app/(portal)/eol/page.tsx:1-120`
- Modify: `portal/lib/api.ts` chỉ dùng signature `api.get(..., { signal })` đã có; không đổi contract
- Test: concurrency/generation check và Chrome Network

**Interfaces:**
- Consumes: `MachineListItem[]`, `MachineDetail`, `api.get` với `AbortSignal`, `getWindowsEol`.
- Produces: helper client nội bộ tải tối đa 4 machine details đồng thời; `load()` hủy request trước, bỏ qua kết quả stale và không cho nút Tính lại tạo pool chồng.

- [ ] **Step 1: Tạo regression check đỏ cho concurrency hiện tại**

```bash
node <<'NODE'
const fs = require("fs");
const source = fs.readFileSync("portal/app/(portal)/eol/page.tsx", "utf8");
if (!source.includes("length: 8")) {
  throw new Error("RED check cannot find the current EOL worker pool");
}
console.log("RED: EOL still uses an 8-worker fan-out");
NODE
```

- [ ] **Step 2: Đổi helper thành bounded worker pool**

Đổi `fetchDetailsSequential` thành helper nhận `signal` và concurrency mặc định 4. Giữ nguyên endpoint `/machines/:id` và giới hạn tối đa 400 item hiện tại. Dùng mảng theo index để kết quả ổn định và không push race:

```tsx
async function fetchMachineDetails(
  list: MachineListItem[],
  signal: AbortSignal,
  concurrency = 4,
): Promise<MachineDetail[]> {
  const targets = list.slice(0, 400);
  const results: Array<MachineDetail | null> = Array(targets.length).fill(null);
  let cursor = 0;

  const worker = async () => {
    while (true) {
      if (signal.aborted) return;
      const index = cursor++;
      if (index >= targets.length) return;
      try {
        results[index] = await api.get<MachineDetail>(
          `/machines/${targets[index].id}`,
          undefined,
          { signal },
        );
      } catch (error) {
        if (signal.aborted || (error as { name?: string })?.name === "AbortError") return;
      }
    }
  };

  await Promise.all(
    Array.from({ length: Math.min(concurrency, targets.length) }, () => worker()),
  );
  return results.filter((item): item is MachineDetail => item !== null);
}
```

- [ ] **Step 3: Add controller and in-flight guard to `EolPage.load`**

Thêm `useRef` import và refs:

```tsx
const loadAbortRef = useRef<AbortController | null>(null);
const loadInFlightRef = useRef(false);
```

Trong `load`, nếu đang có load thì không khởi động thêm một load từ nút hoặc retry; trước request mới abort controller cũ, tạo controller mới và truyền signal cho cả `/machines` lẫn detail helper. Chỉ set `rows`, `generatedAt`, `error` và `loading` nếu controller hiện tại vẫn là controller đó:

```tsx
const load = useCallback(async () => {
  if (loadInFlightRef.current) return;
  loadInFlightRef.current = true;
  loadAbortRef.current?.abort();
  const controller = new AbortController();
  loadAbortRef.current = controller;
  setLoading(true);
  try {
    const data = await api.get<PageResponse<MachineListItem>>(
      "/machines",
      { status: undefined, limit: 50 },
      { signal: controller.signal },
    );
    const details = await fetchMachineDetails(data.items, controller.signal, 4);
    if (controller.signal.aborted || loadAbortRef.current !== controller) return;
    const mapped = details.map((d) => ({
      machine: d as MachineListItem,
      eol: getWindowsEol(d.latest_spec?.os_name, d.latest_spec?.os_build),
    }));
    mapped.sort((a, b) => (a.eol.daysLeft ?? 1e9) - (b.eol.daysLeft ?? 1e9));
    setRows(mapped);
    setGeneratedAt(new Date().toLocaleTimeString("vi-VN"));
    setError(null);
  } catch (error) {
    if (controller.signal.aborted || (error as { name?: string })?.name === "AbortError") return;
    if (loadAbortRef.current === controller) {
      setError(error instanceof Error ? error.message : "Không tải được dữ liệu EOL");
    }
  } finally {
    if (loadAbortRef.current === controller) {
      loadInFlightRef.current = false;
      setLoading(false);
    }
  }
}, []);
```

Thêm unmount cleanup abort; nếu cần cho phép retry sau một lỗi không phải abort, reset `loadInFlightRef` trong cùng `finally` như trên. Nút `Tính lại` dùng `disabled={loading}` và giữ callback `void load()`.

- [ ] **Step 4: Chạy concurrency invariant xanh**

```bash
node <<'NODE'
const fs = require("fs");
const source = fs.readFileSync("portal/app/(portal)/eol/page.tsx", "utf8");
if (!source.includes("concurrency = 4")) throw new Error("EOL concurrency is not bounded at 4");
if (!source.includes("loadInFlightRef")) throw new Error("EOL in-flight guard is missing");
if (!source.includes("signal")) throw new Error("EOL AbortSignal plumbing is missing");
console.log("EOL concurrency regression check passed");
NODE
```

- [ ] **Step 5: Manual Network check**

Mở `/eol`, bấm `Tính lại` liên tiếp trong khi đang tải. Xác nhận:

- Không có fan-out thứ hai.
- Tối đa 4 request `/machines/:id` đang pending cùng lúc.
- Request cũ bị canceled hoặc không cập nhật bảng.
- Một lần load thành công vẫn hiển thị đủ các máy trả về và thứ tự EOL không đổi.

- [ ] **Step 6: Verify task**

```bash
cd portal && npm run typecheck
```

---

### Task 3: Tách realtime context và throttle refresh Dashboard/Machines

**Files:**
- Modify: `portal/components/realtime-context.tsx:15-25,165-185`
- Modify: `portal/app/(portal)/layout.tsx:1-50`
- Modify: `portal/app/(portal)/dashboard/page.tsx:1-75`
- Modify: `portal/app/(portal)/machines/page.tsx:1-210`
- Test: WebSocket burst + Network check

**Interfaces:**
- Consumes: `connected`, `events`, `lastEvent` hiện có.
- Produces: `useRealtimeStatus(): { connected: boolean }` và `useRealtimeEvents(): { events: MachineEvent[]; lastEvent: MachineEvent | null }`; giữ `useRealtime()` để tương thích nếu còn call site ngoài các file đã grep.

- [ ] **Step 1: Kiểm tra call sites trước khi đổi context**

```bash
grep -RIn "useRealtime" portal/app portal/components | grep -v node_modules
```

Expected call sites cần chuyển:

- `layout.tsx` chỉ cần `useRealtimeStatus()`.
- `machines/page.tsx` chỉ cần `useRealtimeEvents()`.
- `dashboard/page.tsx` dùng `useRealtimeStatus()` và `useRealtimeEvents()`.

- [ ] **Step 2: Viết regression check đỏ cho context fan-out**

```bash
node <<'NODE'
const fs = require("fs");
const source = fs.readFileSync("portal/components/realtime-context.tsx", "utf8");
if (!source.includes("const RealtimeStatusContext")) {
  console.log("RED: realtime context is not split into status/events contexts");
  process.exit(0);
}
throw new Error("RED check unexpectedly passes before context split");
NODE
```

- [ ] **Step 3: Tạo hai context value ổn định**

Trong `realtime-context.tsx`, giữ state `events`/`connected` và provider WebSocket hiện tại nhưng tách context:

```tsx
const RealtimeStatusContext = createContext<{ connected: boolean } | null>(null);
const RealtimeEventsContext = createContext<{
  events: MachineEvent[];
  lastEvent: MachineEvent | null;
} | null>(null);
```

Memoize value theo đúng state:

```tsx
const statusValue = useMemo(() => ({ connected }), [connected]);
const eventsValue = useMemo(
  () => ({ events, lastEvent: events[0] ?? null }),
  [events],
);
```

Provider lồng hai context. Export `useRealtimeStatus`, `useRealtimeEvents`, và giữ `useRealtime` ghép hai hook để không phá call site chưa tìm thấy.

- [ ] **Step 4: Chuyển consumers và thêm scheduler throttle**

Ở Dashboard/Machines, thêm refs:

```tsx
const refreshInFlightRef = useRef(false);
const lastRefreshAtRef = useRef(0);
```

Đặt `lastRefreshAtRef.current` khi `load` bắt đầu và reset `refreshInFlightRef` trong `finally`. Tạo callback dùng chung trong từng page:

```tsx
const refreshFromRealtime = useCallback(() => {
  const now = Date.now();
  if (refreshInFlightRef.current || now - lastRefreshAtRef.current < 5000) return;
  lastRefreshAtRef.current = now;
  void load(true);
}, [load]);
```

Dùng `refreshFromRealtime` trong effect `lastEvent`, thay vì tạo `setTimeout` mới cho từng event. Poll 30 giây cũng phải đi qua guard hoặc ít nhất không được tạo request khi một refresh khác đang in-flight. Giữ initial load và dữ liệu UI hiện tại.

- [ ] **Step 5: Chạy invariant check xanh**

```bash
node <<'NODE'
const fs = require("fs");
const context = fs.readFileSync("portal/components/realtime-context.tsx", "utf8");
const machines = fs.readFileSync("portal/app/(portal)/machines/page.tsx", "utf8");
const dashboard = fs.readFileSync("portal/app/(portal)/dashboard/page.tsx", "utf8");
for (const [name, source] of [["context", context], ["machines", machines], ["dashboard", dashboard]]) {
  if (name === "context" && !source.includes("RealtimeStatusContext")) throw new Error("Missing split realtime status context");
  if (name !== "context" && !source.includes("refreshInFlightRef")) throw new Error(`${name} missing refresh in-flight guard`);
}
console.log("Realtime scheduler regression checks passed");
NODE
```

- [ ] **Step 6: Manual burst check**

Mở `/dashboard` và `/machines` cùng lúc, tạo/quan sát burst WebSocket event trong DevTools. Xác nhận:

- Layout chỉ đổi badge connected, không rerender theo từng event array.
- Mỗi page không có quá một silent refresh trong bất kỳ cửa sổ 5 giây nào.
- Poll và realtime không tạo hai request cùng lúc.

- [ ] **Step 7: Verify task**

```bash
cd portal && npm run typecheck
```

---

### Task 4: Memoize organization tree và lookup map

**Files:**
- Create: `portal/lib/use-flat-orgs.ts`
- Modify: `portal/app/(portal)/machines/page.tsx`
- Modify: `portal/app/(portal)/inventory-stats/page.tsx`
- Modify: `portal/app/(portal)/users/page.tsx`
- Modify: `portal/app/(portal)/api-keys/page.tsx`
- Modify: `portal/app/(portal)/reports/page.tsx`
- Modify: `portal/app/(portal)/notifications-alerts/SubscriptionsTab.tsx`
- Test: source invariant + typecheck

**Interfaces:**
- Produces:

```tsx
export function useFlatOrgs(orgs: Organization[]): Array<{
  org: Organization;
  depth: number;
}>;
```

- [ ] **Step 1: Tạo failing import/use invariant**

```bash
node <<'NODE'
const fs = require("fs");
const files = [
  "machines/page.tsx",
  "inventory-stats/page.tsx",
  "users/page.tsx",
  "api-keys/page.tsx",
  "reports/page.tsx",
  "notifications-alerts/SubscriptionsTab.tsx",
];
const bad = files.filter((file) => fs.readFileSync(`portal/app/(portal)/${file}`, "utf8").includes("flattenOrgTree(orgs).map"));
if (bad.length === 0) throw new Error("RED check unexpectedly passes before org memoization");
console.log("RED: direct flattenOrgTree JSX calls remain in", bad.join(", "));
NODE
```

- [ ] **Step 2: Implement `useFlatOrgs`**

```tsx
import { useMemo } from "react";
import type { Organization } from "@/lib/types";
import { flattenOrgTree } from "@/lib/format";

export function useFlatOrgs(orgs: Organization[]) {
  return useMemo(() => flattenOrgTree(orgs), [orgs]);
}
```

- [ ] **Step 3: Replace direct calls in all six pages**

Trong mỗi component page, gọi hook sau khi có `orgs` state:

```tsx
const flatOrgs = useFlatOrgs(orgs);
```

Thay toàn bộ `flattenOrgTree(orgs).map(...)` bằng `flatOrgs.map(...)`. Ở `api-keys/page.tsx`, thay cả `orgName()`:

```tsx
const flatOrgMap = useMemo(
  () => new Map(flatOrgs.map(({ org }) => [org.id, org.name])),
  [flatOrgs],
);
const orgName = (id: string | null) =>
  id ? flatOrgMap.get(id) ?? id.slice(0, 8) : "Toàn hệ thống";
```

Xóa import `flattenOrgTree` ở file nào không còn dùng.

- [ ] **Step 4: Chạy invariant xanh và typecheck**

```bash
node <<'NODE'
const fs = require("fs");
const files = [
  "machines/page.tsx",
  "inventory-stats/page.tsx",
  "users/page.tsx",
  "api-keys/page.tsx",
  "reports/page.tsx",
  "notifications-alerts/SubscriptionsTab.tsx",
];
for (const file of files) {
  const source = fs.readFileSync(`portal/app/(portal)/${file}`, "utf8");
  if (source.includes("flattenOrgTree(orgs).map")) throw new Error(`Direct flatten remains in ${file}`);
  if (!source.includes("useFlatOrgs")) throw new Error(`useFlatOrgs missing in ${file}`);
}
console.log("Organization tree memoization checks passed");
NODE
cd portal && npm run typecheck
```

---

### Task 5: Cô lập render bảng khỏi draft search input

**Files:**
- Create: `portal/components/machine-results-table.tsx`
- Create: `portal/components/audit-results-table.tsx`
- Modify: `portal/app/(portal)/machines/page.tsx`
- Modify: `portal/app/(portal)/audit/page.tsx`
- Test: React render profiling và Network check

**Interfaces:**

`MachineResultsTableProps`:

```tsx
interface MachineResultsTableProps {
  machines: MachineListItem[];
  page: PageResponse<MachineListItem>;
  countByStatus: Record<string, number>;
  onReload: () => void;
  onPageChange: (offset: number) => void;
}
```

`AuditResultsTableProps`:

```tsx
interface AuditResultsTableProps {
  data: AuditPageResponse;
  pageOffset: number;
  onPageChange: (offset: number) => void;
}
```

Cả hai component export bằng `memo`. Không đưa raw `q`/`actor` vào props bảng.

- [ ] **Step 1: Capture baseline render behavior**

Trong React DevTools Profiler, record `/machines` và `/audit`, gõ 20 ký tự khi response data không đổi. Ghi nhận table component hiện tại render mỗi lần. Network phải không phát request từng ký tự do debounce đã có.

- [ ] **Step 2: Tách bảng giữ nguyên markup**

Di chuyển nguyên `<table>`, pagination và status summary tương ứng sang component mới. Các callback phải được tạo bằng `useCallback` ở page:

```tsx
const handleMachineReload = useCallback(() => {
  void load(true);
}, [load]);

const handleMachinePageChange = useCallback(
  (newOffset: number) => {
    setOffset(newOffset);
    void load(true, newOffset);
  },
  [load],
);
```

Trong child dùng:

Component mới phải export bằng `memo` và nhận đúng props đã khai báo. Di chuyển nguyên block `<div className={TABLE_WRAP}>...</div>` hiện có của Machines (table, pagination, status summary và `DeleteButton`) vào component mới; thay closure `load` bằng callback `onReload`/`onPageChange`. Làm tương tự với toàn bộ block table của Audit. Không thay đổi class, text, row key hoặc thứ tự cột trong quá trình di chuyển.

- [ ] **Step 3: Giữ data reference ổn định khi chỉ draft input đổi**

Page vẫn giữ `q`/`actor` local để debounce; không tạo `.slice()`, `.filter()` hoặc object mới cho data bảng trong JSX. `countByStatus` phải dùng `useMemo` theo `machines` để không đổi reference theo raw keystroke.

- [ ] **Step 4: Profile lại**

Record cùng thao tác. Expected: raw input component/page có thể update, nhưng `MachineResultsTable`/`AuditResultsTable` không render lại khi `machines`/`data` và callback props không đổi. Khi response mới về, table phải render và hiển thị dữ liệu mới.

- [ ] **Step 5: Verify task**

```bash
cd portal && npm run typecheck && npm run build
```

---

### Task 6: Loại request notification trùng và blur modal dùng chung

**Files:**
- Modify: `portal/app/(portal)/notifications-alerts/page.tsx:90-108`
- Modify: `portal/components/ui.tsx:506-516`
- Test: Network check và source invariant

**Interfaces:**
- Giữ nguyên `useNotifications().refresh()` cho các thao tác user-triggered.
- Provider là owner của initial notification refresh; NotificationsAlertsPage không refresh trùng khi mount.

- [ ] **Step 1: Tạo regression check đỏ**

```bash
node <<'NODE'
const fs = require("fs");
const page = fs.readFileSync("portal/app/(portal)/notifications-alerts/page.tsx", "utf8");
const modal = fs.readFileSync("portal/components/ui.tsx", "utf8");
if (!page.includes("void refresh()")) throw new Error("RED check cannot find duplicate page refresh");
if (!modal.includes("backdrop-blur-sm")) throw new Error("RED check cannot find shared modal blur");
console.log("RED: duplicate notification refresh and shared modal blur remain");
NODE
```

- [ ] **Step 2: Xóa initial refresh trùng ở page**

Trong effect mount của `NotificationsAlertsPage`, giữ `loadTemplates()` và `/orgs`, bỏ riêng dòng `void refresh();`. Không xóa `refresh` khỏi context hoặc các handler gửi/đánh dấu notification.

- [ ] **Step 3: Bỏ blur khỏi `Modal` dùng chung**

Đổi overlay:

```tsx
<div className="absolute inset-0 bg-slate-900/55" onClick={onClose} />
```

Đổi sticky header từ nền alpha + blur sang nền đặc:

```tsx
<header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-slate-100 bg-white px-6 py-4">
```

Giữ nguyên focus trap, body scroll lock, z-index, close behavior và children.

- [ ] **Step 4: Verify behavior**

Mở `/notifications-alerts` và quan sát Network: initial list/count chỉ có một cặp request từ provider. Mở modal tạo form trên GPU yếu và cuộn; không còn overlay `backdrop-filter` trong computed styles.

- [ ] **Step 5: Verify task**

```bash
node <<'NODE'
const fs = require("fs");
const page = fs.readFileSync("portal/app/(portal)/notifications-alerts/page.tsx", "utf8");
const modal = fs.readFileSync("portal/components/ui.tsx", "utf8");
if (page.includes("void refresh()")) throw new Error("Duplicate page refresh remains");
if (modal.includes("backdrop-blur-sm")) throw new Error("Shared modal blur remains");
console.log("Notification/modal regression checks passed");
NODE
cd portal && npm run typecheck
```

---

### Task 7: Final integration verification and scope audit

**Files:**
- No new source files expected beyond Tasks 2, 4 and 5.
- Inspect: all files changed by Tasks 1–6.

- [ ] **Step 1: Run full portal verification**

```bash
cd portal && npm run typecheck && npm run build
```

Expected: both commands exit 0; build may retain the existing warning about root and `portal/pnpm-lock.yaml` being multiple lockfiles.

- [ ] **Step 2: Check formatting and changed-file scope**

```bash
git diff --check
git status --short
git diff --name-only -- portal
```

Expected: no whitespace errors; implementation files are within the listed `portal/` paths. Existing `server/` and `deepagent/` changes remain unstaged and untouched.

- [ ] **Step 3: Run acceptance matrix**

| Flow | Expected evidence |
|---|---|
| Audit page > 1 + filter | One request after debounce, new filter, offset 0, list updates |
| EOL initial load/reload | Max 4 detail requests in flight; no duplicate pool; stale load ignored |
| Dashboard/Machines + WS burst | Max one silent refresh per 5s per page; status-only consumers skip event-array updates |
| Machines/Audit search typing | Table does not render on every draft keystroke; network remains debounced |
| Organization selects | No direct `flattenOrgTree(orgs).map` remains in target pages |
| NotificationsAlerts mount | No duplicate initial notification list/count pair |
| Shared modal scroll | No backdrop/sticky-header blur; focus and body scroll lock preserved |

- [ ] **Step 4: Review non-goals**

Do not implement the rejected MiniMax findings unless a new DevTools profile proves them: chat two-phase update, `InvestigationMarkdown` inner parse cache, Top10 collected branch, Sidebar OrgNode claim, `InvestigationHistoryRow` memo, or realtime retry “connected=false” loop.

- [ ] **Step 5: Final report**

Report changed files, commands and outputs, manual DevTools evidence, remaining lockfile warning, and any finding deferred because it requires backend endpoint work or real fleet-size profiling.
