"use client";

import { useCallback, useEffect, useState } from "react";
import { BellRing } from "lucide-react";
import { api } from "@/lib/api";
import type { AlertEvent } from "@/lib/types";
import { ALERT_SEVERITY_META, formatDateTime, timeAgo } from "@/lib/format";
import {
  Badge, Card, EmptyState, PageResponse, Pagination, Spinner,
  TABLE, TABLE_WRAP, TD, TH, THEAD, TR_HOVER,
} from "@/components/ui";

export default function HistoryTab() {
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [page, setPage] = useState<PageResponse<AlertEvent>>({ items: [], total: 0, limit: 50, offset: 0 });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (silent = false) => {
    try {
      const r = await api.get<PageResponse<AlertEvent>>("/alert-rules/events", { limit: 50, offset });
      setEvents(r.items);
      setPage(r);
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => { void load(); }, [load]);

  return (
    <Card title="Lịch sử cảnh báo" subtitle={`${page.total} sự kiện — content đã render lúc trigger`} padded={false}>
      {loading && events.length === 0 ? <Spinner /> : events.length === 0 ? (
        <EmptyState icon={<BellRing className="size-10" />} title="Chưa có cảnh báo nào" description="Cảnh báo sẽ xuất hiện khi rule kích hoạt." />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Thời gian</th>
                <th scope="col" className={TH}>Template</th>
                <th scope="col" className={TH}>Mức độ</th>
                <th scope="col" className={TH}>Nội dung</th>
                <th scope="col" className={TH}>Người nhận</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const sev = ALERT_SEVERITY_META[ev.severity] ?? ALERT_SEVERITY_META.info;
                return (
                  <tr key={ev.id} className={TR_HOVER}>
                    <td className={`${TD} text-xs`} title={formatDateTime(ev.created_at)}>{timeAgo(ev.created_at)}</td>
                    <td className={`${TD} text-xs text-slate-500`}>{ev.template_code}</td>
                    <td className={TD}><Badge className={sev.badge}>{sev.label}</Badge></td>
                    <td className={`${TD} text-sm text-slate-700`}>{ev.title}</td>
                    <td className={`${TD} text-xs text-slate-500`}>{ev.recipient_user_ids?.length ?? 0}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination page={page} onChange={(o) => { setOffset(o); void load(true); }} />
        </div>
      )}
    </Card>
  );
}
