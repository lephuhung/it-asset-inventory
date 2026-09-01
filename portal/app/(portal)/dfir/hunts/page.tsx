"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ExternalLink, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from "@/components/ui";
import type { DfirHunt } from "@/lib/types";
import { formatDateTime, timeAgo } from "@/lib/format";
import { DeleteButton } from "@/components/delete-button";

/** Lịch sử hunt / collect đã chạy (audit log local). */
export default function DfirHuntsPage() {
  const [hunts, setHunts] = useState<DfirHunt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const hs = await api.get<DfirHunt[]>("/admin/velociraptor/hunts", { limit: 200 });
      setHunts(hs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được lịch sử hunt");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner label="Đang tải lịch sử hunt…" />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lịch sử Hunt / Collect"
        description="Mỗi lần admin chạy hunt hoặc collect artifact qua Velociraptor đều được ghi log ở đây."
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              <RefreshCw className="size-3.5" /> Nạp lại
            </Button>
            <Link
              href="/dfir"
              className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              <ChevronLeft className="size-3.5" /> DFIR dashboard
            </Link>
          </div>
        }
      />

      {error && <ErrorBanner message={error} />}

      <Card className="overflow-hidden p-0">
        {hunts.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="Chưa có hunt nào"
              description="Vào /dfir để chạy hunt đầu tiên. Kết quả lưu trên Velociraptor Server, không cache trên portal."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">Thời điểm</th>
                  <th className="px-4 py-3 text-left">Artifact</th>
                  <th className="px-4 py-3 text-left">Phạm vi</th>
                  <th className="px-4 py-3 text-left">Trạng thái</th>
                  <th className="px-4 py-3 text-left">Velociraptor</th>
                  <th className="px-4 py-3 text-left">Ghi chú</th>
                  <th className="px-4 py-3 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {hunts.map((h) => (
                  <tr key={h.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 text-slate-600">
                      <div>{formatDateTime(h.created_at)}</div>
                      <div className="text-[11px] text-slate-400">{timeAgo(h.created_at)}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-slate-900">{h.artifact}</td>
                    <td className="px-4 py-3">
                      {h.scope === "all" ? (
                        <Badge className="bg-slate-100 text-slate-700 ring-slate-600/20">Tất cả</Badge>
                      ) : (
                        <Badge className="bg-violet-100 text-violet-700 ring-violet-600/20">1 máy</Badge>
                      )}
                      {h.client_count != null && (
                        <span className="ml-1 text-[11px] text-slate-400">({h.client_count})</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {h.status === "completed" ? (
                        <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">OK</Badge>
                      ) : h.status === "error" ? (
                        <Badge className="bg-rose-100 text-rose-700 ring-rose-600/20">Lỗi</Badge>
                      ) : (
                        <Badge className="bg-amber-100 text-amber-700 ring-amber-600/20">Pending</Badge>
                      )}
                      {h.error && (
                        <p className="mt-1 max-w-xs truncate text-[11px] text-rose-600" title={h.error}>
                          {h.error}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {h.velociraptor_url ? (
                        <a
                          href={h.velociraptor_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 font-mono text-[11px] text-brand-600 hover:underline"
                        >
                          {h.hunt_id?.slice(0, 12) ?? "—"}…
                          <ExternalLink className="size-3" />
                        </a>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate text-xs text-slate-600" title={h.notes ?? ""}>
                      {h.notes || "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {h.hunt_id && (
                        <DeleteButton
                          resource="hunt"
                          itemName={`${h.artifact} (${h.hunt_id.slice(0, 8)})`}
                          deletePath={`/admin/velociraptor/hunts/${h.hunt_id}`}
                          onDeleted={() => void load()}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
