"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ClipboardCheck, Monitor, RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem, Organization, Tag } from "@/lib/types";
import { useRealtimeEvents } from "@/components/realtime-context";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  PageResponse,
  Select,
  Spinner,
} from "@/components/ui";
import { ORG_TYPE_META } from "@/lib/format";
import { useFlatOrgs } from "@/lib/use-flat-orgs";
import { useAuth } from "@/components/auth-context";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { MachineResultsTable } from "@/components/machine-results-table";

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Tất cả trạng thái" },
  { value: "online", label: "Online" },
  { value: "offline", label: "Offline" },
  { value: "lost", label: "Máy mất kết nối" },
  { value: "pending", label: "Chờ duyệt" },
  { value: "decommissioned", label: "Đã thanh lý" },
];

export default function MachinesPage() {
  const { user } = useAuth();
  const { lastEvent } = useRealtimeEvents();

  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [page, setPage] = useState<PageResponse<MachineListItem>>({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const flatOrgs = useFlatOrgs(orgs);
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [orgId, setOrgId] = useState("");
  const [tag, setTag] = useState("");
  const [offset, setOffset] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);

  // Debounce 350ms cho q — không phát request theo từng ký tự.
  const debouncedQ = useDebouncedValue(q, 350);
  // AbortController cho request search đang chạy — request trước bị hủy khi
  // user gõ tiếp.
  const searchAbortRef = useRef<AbortController | null>(null);
  // Guard chống burst refresh từ realtime + poll 30s: chỉ một silent refresh
  // trong cửa sổ 5 giây và không xếp chồng khi refresh đang in-flight.
  const refreshInFlightRef = useRef(false);
  const lastRefreshAtRef = useRef(0);

  const load = useCallback(
    async (silent = false, overrideOffset?: number, overrideQ?: string) => {
      // Hủy request cũ (nếu đang pending) — bỏ qua kết quả lỗi thời.
      // Tạo controller mới và gán vào ref TRƯỚC khi await — đảm bảo các lần
      // gọi load() tiếp theo thấy được controller hiện tại để abort/stale-check.
      searchAbortRef.current?.abort();
      const controller = new AbortController();
      searchAbortRef.current = controller;
      // Mọi load (initial, manual "Làm mới" / "Áp dụng", silent pagination /
      // delete, realtime qua WebSocket, poll 30s) đều tham gia in-flight
      // guard và ghi timestamp ngay khi bắt đầu — đảm bảo:
      //  - Khi bất kỳ load nào đang chạy, `refreshFromRealtime` thấy
      //    `refreshInFlightRef.current = true` và skip — không có silent
      //    refresh chồng với request đang in-flight.
      //  - Cửa sổ throttle 5 giây được thiết lập từ lúc load bắt đầu (không
      //    phải từ lúc kết thúc), nên burst WebSocket event ngay sau khi load
      //    hoàn tất cũng không thể lọt qua guard.
      // Manual click vẫn luôn được phép vì `onClick` gọi `load()` trực tiếp
      // chứ không qua `refreshFromRealtime` — chỉ guard throttling mới bị
      // tham gia vào cửa sổ 5s (chấp nhận được, không phá khả năng thao
      // tác manual). Stale finally của controller cũ được chặn bởi guard
      // `searchAbortRef.current === controller` ở dưới.
      refreshInFlightRef.current = true;
      lastRefreshAtRef.current = Date.now();
      const useOffset = overrideOffset ?? offset;
      try {
        const data = await api.get<PageResponse<MachineListItem>>(
          "/machines",
          {
            q: (overrideQ ?? debouncedQ) || undefined,
            status: status || undefined,
            org_id: orgId || undefined,
            tag: tag || undefined,
            limit: 50,
            offset: useOffset,
          },
          { signal: controller.signal },
        );
        if (controller.signal.aborted || searchAbortRef.current !== controller) return;
        setMachines(data.items);
        setPage(data);
        // Ẩn máy "pending" khỏi Assets — máy chờ duyệt chỉ hiện ở trang /approvals.
        const pending = data.items.filter((m) => m.status === "pending").length;
        setPendingCount(pending);
        if (status === "") {
          // Default: chỉ hiện máy đã duyệt. Khi user chọn filter cụ thể, tôn trọng lựa chọn.
          setMachines(data.items.filter((m) => m.status !== "pending"));
        }
        setError(null);
      } catch (e: any) {
        // AbortError hoặc request đã lỗi thời — im lặng, không log error UI.
        if (e?.name === "AbortError" || controller.signal.aborted || searchAbortRef.current !== controller) return;
        if (!silent) setError(e instanceof Error ? e.message : "Không tải được danh sách máy");
      } finally {
        // Stale result guard: chỉ reset trạng thái cho controller hiện tại.
        // Nếu controller cũ còn finally chờ (vì promise của nó bị abort
        // khi manual / pagination / realtime load mới bắt đầu), nó không
        // được phép đè in-flight của controller mới — nếu không, cửa sổ
        // throttle bị phá vỡ và `refreshFromRealtime` có thể bắn thêm một
        // silent refresh chồng với controller đang chạy.
        // In-flight giờ là cờ chung cho mọi load (silent hay manual), nên
        // reset unconditional cho bất kỳ controller nào còn là hiện tại —
        // không phân biệt silent/manual nữa.
        if (searchAbortRef.current === controller) {
          setLoading(false);
          refreshInFlightRef.current = false;
        }
      }
    },
    [debouncedQ, status, orgId, tag, offset],
  );

  // Cleanup AbortController khi rời trang.
  useEffect(() => {
    return () => {
      searchAbortRef.current?.abort();
      searchAbortRef.current = null;
    };
  }, []);

  // Org list (admin toàn cục) — endpoint /api/orgs chưa có ở backend → ẩn bộ lọc khi thiếu.
  useEffect(() => {
    api
      .get<Organization[]>("/orgs")
      .then((list) => {
        setOrgs(Array.isArray(list) ? list : []);
      })
      .catch(() => setOrgs([]));
    // Tags (phân loại + mục đích) — cho bộ lọc
    api
      .get<Tag[]>("/tags")
      .then((list) => setTags(Array.isArray(list) ? list : []))
      .catch(() => setTags([]));
  }, []);

  // Callback dùng chung cho cả effect lastEvent và poll 30s — cả hai
  // nguồn kích hoạt đều đi qua cùng guard burst throttle. Timestamp được
  // ghi ở `load()` ngay khi controller mới được tạo, nên callback này
  // chỉ cần kiểm tra guard và gọi `load(true)` — không ghi timestamp
  // thủ công (tránh duplicate và đảm bảo single source of truth).
  const refreshFromRealtime = useCallback(() => {
    const now = Date.now();
    if (refreshInFlightRef.current || now - lastRefreshAtRef.current < 5000) return;
    void load(true);
  }, [load]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => refreshFromRealtime(), 30_000);
    return () => clearInterval(timer);
  }, [load, refreshFromRealtime]);

  // Realtime: máy online/offline → refresh nhẹ (qua guard).
  useEffect(() => {
    if (!lastEvent) return;
    refreshFromRealtime();
  }, [lastEvent, refreshFromRealtime]);

  const countByStatus = useMemo(
    () =>
      (machines ?? []).reduce<Record<string, number>>((acc, m) => {
        acc[m.status] = (acc[m.status] ?? 0) + 1;
        return acc;
      }, {}),
    [machines],
  );

  // Callback cho bảng kết quả — giữ tham chiếu ổn định để `MachineResultsTable`
  // (memo) không re-render khi chỉ `q`/filter thay đổi.
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

  return (
    <div>
      <PageHeader
        title="Danh sách máy"
        description={`${machines?.length ?? 0} máy trong phạm vi quản lý`}
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Làm mới
          </Button>
        }
      />

      <Card className="mb-4" title="Bộ lọc" padded={false}>
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Tìm kiếm (hostname / UUID)">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="VD: PC-042, KT-*…"
                className="pl-9"
              />
            </div>
          </Field>
          <Field label="Trạng thái">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {(STATUS_OPTIONS ?? []).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          {(orgs?.length ?? 0) > 0 && (
            <Field label="Tổ chức (UBND cấp xã / Sở ban ngành)">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">Tất cả</option>
                {flatOrgs.map(({ org, depth }) => {
                  const meta = ORG_TYPE_META[org.type];
                  return (
                    <option key={org.id} value={org.id}>
                      {"— ".repeat(depth)}
                      {org.name} ({meta?.label ?? org.type})
                    </option>
                  );
                })}
              </Select>
            </Field>
          )}
          <Field label="Phân loại / tag">
            <Select value={tag} onChange={(e) => setTag(e.target.value)}>
              <option value="">Tất cả loại máy</option>
              {tags.map((t) => (
                <option key={t.id} value={t.key}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex items-end self-end">
            <Button
              variant="secondary"
              onClick={() => {
                setOffset(0);
                // Apply là thao tác chủ động: dùng giá trị đang hiển thị thay vì
                // giá trị debounced cũ nếu user bấm ngay sau khi nhập.
                void load(false, 0, q);
              }}
              disabled={loading}
            >
              Áp dụng
            </Button>
          </div>
        </div>
        {user?.role === "super_admin" && (orgs?.length ?? 0) === 0 && (
          <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            Chưa có tổ chức nào — thêm UBND cấp xã / Sở ban ngành tại mục "Cây tổ chức".
          </p>
        )}
      </Card>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {pendingCount > 0 && status === "" && (
        <Link
          href="/approvals"
          className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm transition hover:bg-amber-100"
        >
          <span className="flex items-center gap-2 text-amber-800">
            <ClipboardCheck className="size-4" />
            <span>
              Có <b>{pendingCount}</b> máy đang chờ duyệt (đã ẩn khỏi Assets để tránh đếm trùng).
            </span>
          </span>
          <span className="text-xs font-semibold text-amber-700 underline">
            Đi tới Chờ duyệt →
          </span>
        </Link>
      )}

      {loading && (machines?.length ?? 0) === 0 ? (
        <Spinner label="Đang tải danh sách máy…" />
      ) : (machines?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<Monitor className="size-10" />}
          title="Không có máy nào khớp bộ lọc"
          description="Tạo token triển khai tại mục Token để đưa máy vào hệ thống."
        />
      ) : (
        <MachineResultsTable
          machines={machines}
          page={page}
          countByStatus={countByStatus}
          onReload={handleMachineReload}
          onPageChange={handleMachinePageChange}
        />
      )}
    </div>
  );
}