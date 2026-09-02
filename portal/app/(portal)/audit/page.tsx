"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, ScrollText, ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  StatusDot,
} from "@/components/ui";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { AuditResultsTable, type AuditPageResponse } from "@/components/audit-results-table";

interface VerifyResponse {
  ok: boolean;
  broken_index: number | null;
  checked: number;
  anchor_hash: string;
}

const PAGE_SIZE = 100;

/** Trang audit log read-only (Sprint 4, mục 7.2) — append-only + hash chain. */
export default function AuditPage() {
  const [data, setData] = useState<AuditPageResponse | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Bộ lọc
  const [action, setAction] = useState("");
  const [q, setQ] = useState("");
  const [actor, setActor] = useState("");
  const [offset, setOffset] = useState(0);

  // Debounce 350ms — gõ vào q/actor không phát request từng ký tự.
  const debouncedQ = useDebouncedValue(q, 350);
  const debouncedActor = useDebouncedValue(actor, 350);
  // Hủy request trước nếu user gõ tiếp.
  const searchAbortRef = useRef<AbortController | null>(null);
  const skipNextLoadRef = useRef(false);
  const filterRef = useRef({ action: "", q: "", actor: "" });
  const rawSearchRef = useRef({ q: "", actor: "" });
  rawSearchRef.current = { q, actor };

  // Verify hash chain
  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [verifyBusy, setVerifyBusy] = useState(false);

  const load = useCallback(
    async (silent = false, overrideOffset?: number) => {
      const useOffset = overrideOffset ?? offset;
      searchAbortRef.current?.abort();
      const controller = new AbortController();
      searchAbortRef.current = controller;
      try {
        const res = await api.get<AuditPageResponse>(
          "/audit",
          {
            limit: PAGE_SIZE,
            offset: useOffset,
            action: action || undefined,
            actor: debouncedActor || undefined,
            q: debouncedQ || undefined,
          },
          { signal: controller.signal },
        );
        if (controller.signal.aborted || searchAbortRef.current !== controller) return;
        setData(res);
        setError(null);
      } catch (e: any) {
        // AbortError hoặc request đã lỗi thời — bỏ qua.
        if (e?.name === "AbortError" || controller.signal.aborted || searchAbortRef.current !== controller) return;
        if (!silent) setError(e instanceof Error ? e.message : "Không tải được audit log");
      } finally {
        if (searchAbortRef.current === controller) setLoading(false);
      }
    },
    [action, debouncedQ, debouncedActor, offset],
  );

  // Cleanup khi rời trang.
  useEffect(() => {
    return () => {
      searchAbortRef.current?.abort();
      searchAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    const filterChanged =
      filterRef.current.action !== action ||
      filterRef.current.q !== q ||
      filterRef.current.actor !== actor;
    if (!filterChanged) return;
    filterRef.current = { action, q, actor };
    if (offset !== 0) {
      // Chờ debounced filter thay đổi; không tải lại ngay với giá trị tìm kiếm cũ.
      skipNextLoadRef.current = true;
      setOffset(0);
    }
  }, [action, q, actor, offset]);

  useEffect(() => {
    if (skipNextLoadRef.current) {
      // Nếu search text còn chưa debounce, tiếp tục chờ giá trị mới thay vì
      // tải với filter cũ sau lần reset offset.
      if (rawSearchRef.current.q !== debouncedQ || rawSearchRef.current.actor !== debouncedActor) return;
      // Chờ `setOffset(0)` từ filter effect commit xong trước khi gọi load().
      // Nếu gọi ngay, closure của `load` vẫn capture `offset` cũ (page > 1)
      // và phát một request trung gian với filter mới nhưng offset cũ — vi
      // phạm acceptance "một request sau khi filter ổn định với offset 0".
      if (offset !== 0) return;
      skipNextLoadRef.current = false;
      void load();
      return;
    }
    void load();
  }, [load]);

  useEffect(() => {
    api
      .get<string[]>("/audit/actions")
      .then((list) => setActions(Array.isArray(list) ? list : []))
      .catch(() => setActions([]));
  }, []);

  const runVerify = async () => {
    setVerifyBusy(true);
    try {
      setVerify(await api.get<VerifyResponse>("/audit/verify"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kiểm tra hash chain thất bại");
    } finally {
      setVerifyBusy(false);
    }
  };

  // Callback cho bảng kết quả — giữ tham chiếu ổn định để `AuditResultsTable`
  // (memo) không re-render khi chỉ `q`/`actor`/`action` thay đổi.
  const handleAuditPageChange = useCallback(
    (newOffset: number) => {
      setOffset(newOffset);
      void load(true, newOffset);
    },
    [load],
  );

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="Nhật ký chỉ ghi (append-only) có hash chain — mọi thao tác nhạy cảm: login, token, enroll, export, drift, xác nhận tuân thủ"
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* Kiểm tra hash chain */}
      <Card className="mb-4" padded={false}>
        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
          <ShieldCheck className="size-5 text-blue-600" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-800">Kiểm tra toàn vẹn hash chain</p>
            <p className="text-xs text-slate-400">
              {verify
                ? `Đã kiểm tra ${verify.checked} dòng — anchor: ${verify.anchor_hash.slice(0, 16)}…`
                : "Xác minh không dòng nào bị sửa/xóa giữa chuỗi (phát hiện ngay mọi can thiệp)."}
            </p>
          </div>
          {verify && (
            verify.ok ? (
              <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                <StatusDot className="bg-emerald-500" /> Chuỗi hợp lệ
              </Badge>
            ) : (
              <Badge className="bg-rose-50 text-rose-700 ring-rose-600/20">
                <StatusDot className="bg-rose-500" /> ĐỨT CHUỖI tại dòng #{verify.broken_index}
              </Badge>
            )
          )}
          <Button variant="secondary" size="sm" onClick={() => void runVerify()} loading={verifyBusy}>
            <ShieldAlert className="size-3.5" /> Kiểm tra
          </Button>
        </div>
      </Card>

      {/* Bộ lọc */}
      <Card className="mb-4" padded={false}>
        <div className="grid gap-3 p-4 sm:grid-cols-3">
          <Field label="Hành động (action)">
            <Select value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="">Tất cả</option>
              {(actions ?? []).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Người thực hiện (actor)">
            <Input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="VD: agent:…, user id…" />
          </Field>
          <Field label="Tìm kiếm (action/target)">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="VD: token.create, enroll…" />
          </Field>
        </div>
      </Card>

      {loading && !data ? (
        <Spinner label="Đang tải audit log…" />
      ) : !data || (data.items?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<ScrollText className="size-10" />}
          title="Không có bản ghi audit khớp bộ lọc"
          description="Khi có hoạt động (đăng nhập, sinh token, enroll máy…), các bản ghi sẽ liệt kê tại đây."
        />
      ) : (
        <AuditResultsTable
          data={data}
          pageOffset={offset}
          onPageChange={handleAuditPageChange}
        />
      )}
    </div>
  );
}