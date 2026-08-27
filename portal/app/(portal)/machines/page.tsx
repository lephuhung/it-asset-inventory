"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Monitor, RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineListItem, MachineStatus, Organization } from "@/lib/types";
import { useRealtime } from "@/components/realtime-context";
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
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { LIFECYCLE_META, MACHINE_STATUS_META, ORG_TYPE_META, flattenOrgTree, formatDateTime, timeAgo } from "@/lib/format";
import { useAuth } from "@/components/auth-context";

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
  const { lastEvent } = useRealtime();

  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [orgId, setOrgId] = useState("");

  const load = useCallback(
    async (silent = false) => {
      try {
        const list = await api.get<MachineListItem[]>("/machines", {
          q: q || undefined,
          status: status || undefined,
          org_id: orgId || undefined,
        });
        setMachines(list);
        setError(null);
      } catch (e) {
        if (!silent) setError(e instanceof Error ? e.message : "Không tải được danh sách máy");
      } finally {
        setLoading(false);
      }
    },
    [q, status, orgId],
  );

  // Org list (admin toàn cục) — endpoint /api/orgs chưa có ở backend → ẩn bộ lọc khi thiếu.
  useEffect(() => {
    api
      .get<Organization[]>("/orgs")
      .then((list) => {
        setOrgs(Array.isArray(list) ? list : []);
      })
      .catch(() => setOrgs([]));
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(true), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  // Realtime: máy online/offline → refresh nhẹ
  useEffect(() => {
    if (!lastEvent) return;
    const t = setTimeout(() => void load(true), 1200);
    return () => clearTimeout(t);
  }, [lastEvent, load]);

  const countByStatus = machines.reduce<Record<string, number>>((acc, m) => {
    acc[m.status] = (acc[m.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <PageHeader
        title="Danh sách máy"
        description={`${machines.length} máy trong phạm vi quản lý`}
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
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          {orgs.length > 0 && (
            <Field label="Tổ chức (UBND cấp xã / Sở ban ngành)">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">Tất cả</option>
                {flattenOrgTree(orgs).map(({ org, depth }) => {
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
          <div className="flex items-end self-end">
            <Button variant="secondary" onClick={() => void load()} disabled={loading}>
              Áp dụng
            </Button>
          </div>
        </div>
        {user?.role === "super_admin" && orgs.length === 0 && (
          <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            Chưa có tổ chức nào — thêm UBND cấp xã / Sở ban ngành tại mục "Cây tổ chức".
          </p>
        )}
      </Card>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && machines.length === 0 ? (
        <Spinner label="Đang tải danh sách máy…" />
      ) : machines.length === 0 ? (
        <EmptyState
          icon={<Monitor className="size-10" />}
          title="Không có máy nào khớp bộ lọc"
          description="Tạo token triển khai tại mục Token để đưa máy vào hệ thống."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Hostname</th>
                <th scope="col" className={TH}>UUID máy</th>
                <th scope="col" className={TH}>Trạng thái</th>
                <th scope="col" className={TH}>Vòng đời</th>
                <th scope="col" className={TH}>Loại</th>
                <th scope="col" className={TH}>Người dùng đăng nhập</th>
                <th scope="col" className={TH}>Lần cuối online</th>
                <th scope="col" className={TH}>Enroll</th>
                <th scope="col" className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {machines.map((m) => {
                const meta = MACHINE_STATUS_META[m.status];
                const life = LIFECYCLE_META[m.lifecycle] ?? { label: m.lifecycle, badge: "bg-slate-100 text-slate-500 ring-slate-500/20" };
                return (
                  <tr key={m.id} className={TR_HOVER}>
                    <td className={`${TD} font-medium text-slate-800`}>{m.hostname ?? "(chưa đặt tên)"}</td>
                    <td className={`${TD} font-mono text-xs text-slate-500`}>{m.machine_uuid.slice(0, 12)}…</td>
                    <td className={TD}>
                      <Badge className={meta.badge}>
                        <StatusDot className={meta.dot} />
                        {meta.label}
                      </Badge>
                      {m.status !== "online" && m.last_seen_at && (
                        <p className="mt-1 text-[11px] text-slate-400">Cuối: {timeAgo(m.last_seen_at)}</p>
                      )}
                    </td>
                    <td className={TD}>
                      <Badge className={life.badge}>{life.label}</Badge>
                    </td>
                    <td className={TD}>{m.is_vm ? "Ảo" : "Vật lý"}</td>
                    <td className={`${TD} text-xs`}>
                      {m.logged_user ? (
                        <span className="font-mono" title={m.logged_user}>{m.logged_user}</span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className={`${TD} text-xs`}>{formatDateTime(m.last_seen_at)}</td>
                    <td className={`${TD} text-xs`}>{formatDateTime(m.enrolled_at)}</td>
                    <td className={TD}>
                      <Link
                        href={`/machines/${m.id}`}
                        className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-600 hover:underline"
                      >
                        Chi tiết <ChevronRight className="size-3.5" />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {Object.keys(countByStatus).length > 0 && (
            <div className="flex flex-wrap gap-2 border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
              {Object.entries(countByStatus).map(([s, n]) => (
                <span key={s} className="inline-flex items-center gap-1">
                  <StatusDot className={MACHINE_STATUS_META[s as MachineStatus]?.dot ?? "bg-slate-400"} />
                  {MACHINE_STATUS_META[s as MachineStatus]?.label ?? s}: <b>{n}</b>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}