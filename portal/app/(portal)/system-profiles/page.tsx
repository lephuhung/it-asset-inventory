"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Clock, Layers, Plus, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { SystemProfile, SystemProfileStatus } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  KpiCard,
  PageHeader,
  Select,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
  EmptyState,
  PageResponse,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import { LevelBadge, StatusBadge } from "@/components/system-profile-badges";
import type { Organization } from "@/lib/types";
import { useFlatOrgs } from "@/lib/use-flat-orgs";

export default function SystemProfilesPage() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "super_admin" || user?.role === "org_admin" || user?.role === "admin_global" || user?.role === "admin_org";
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [items, setItems] = useState<SystemProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const flatOrgs = useFlatOrgs(orgs);

  const [orgId, setOrgId] = useState("");
  const [level, setLevel] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState<{ org_id: string; level: string; status: string; q: string }>({
    org_id: "",
    level: "",
    status: "",
    q: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.get<PageResponse<SystemProfile>>("/system-profiles", {
        org_id: applied.org_id,
        level: applied.level,
        status: applied.status,
        q: applied.q,
      });
      setItems(page.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách hồ sơ");
    } finally {
      setLoading(false);
    }
  }, [applied]);

  useEffect(() => {
    if (isSuperAdmin) {
      void api.get<Organization[]>("/orgs").then(setOrgs).catch(() => setOrgs([]));
    }
  }, [isSuperAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = {
    total: items.length,
    approved: items.filter((p) => p.status === "approved").length,
    pending: items.filter((p) => p.status === "pending_review").length,
    l1: items.filter((p) => p.level === 1).length,
    l2: items.filter((p) => p.level === 2).length,
    l3: items.filter((p) => p.level === 3).length,
  };

  return (
    <div>
      <PageHeader
        title="Hồ sơ cấp độ hệ thống thông tin"
        description="Hồ sơ xác định cấp độ (1–3), danh mục thiết bị và quyết định phê duyệt của hệ thống thông tin."
         actions={
          isAdmin ? (
            <Button onClick={() => router.push("/system-profiles/new")}>
              <Plus className="size-4" /> Tạo hồ sơ
            </Button>
          ) : undefined
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard
          label="Tổng hồ sơ"
          value={stats.total}
          icon={<ShieldCheck className="size-4 text-brand-600" />}
          accent="bg-brand-50"
        />
        <KpiCard
          label="Đã phê duyệt"
          value={stats.approved}
          icon={<ShieldCheck className="size-4 text-emerald-600" />}
          accent="bg-emerald-50"
        />
        <KpiCard
          label="Chờ duyệt"
          value={stats.pending}
          icon={<Clock className="size-4 text-amber-600" />}
          accent="bg-amber-50"
        />
        <KpiCard
          label="Theo cấp độ"
          value={`${stats.l1} · ${stats.l2} · ${stats.l3}`}
          icon={<Layers className="size-4 text-violet-600" />}
          accent="bg-violet-50"
          sub="C1 · C2 · C3"
        />
      </div>

      <Card className="mb-4" title="Bộ lọc" padded={false}>
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
          {isSuperAdmin && (
            <Field label="Đơn vị">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">Tất cả đơn vị</option>
                {flatOrgs.map(({ org, depth }) => (
                  <option key={org.id} value={org.id}>{`${"— ".repeat(depth)}${org.name}`}</option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Cấp độ">
            <Select value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">Tất cả</option>
              <option value="1">Cấp 1</option>
              <option value="2">Cấp 2</option>
              <option value="3">Cấp 3</option>
            </Select>
          </Field>
          <Field label="Trạng thái">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Tất cả</option>
              <option value="drafted">Nháp</option>
              <option value="pending_review">Chờ duyệt</option>
              <option value="approved">Đã phê duyệt</option>
              <option value="rejected">Bị từ chối</option>
            </Select>
          </Field>
          <Field label="Tìm theo tên">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tên hệ thống…" />
          </Field>
          <div className="flex items-end self-end">
            <Button variant="secondary" onClick={() => setApplied({ org_id: orgId, level, status, q })}>
              Lọc
            </Button>
          </div>
        </div>
      </Card>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && items.length === 0 ? (
        <Spinner label="Đang tải hồ sơ…" />
      ) : items.length === 0 && !error ? (
        <EmptyState
          icon={<ShieldCheck className="size-8 text-slate-400" />}
          title="Chưa có hồ sơ nào"
          description={isAdmin ? "Tạo hồ sơ cấp độ đầu tiên cho đơn vị của bạn." : "Đơn vị chưa có hồ sơ cấp độ hệ thống thông tin."}
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th className={TH}>Hồ sơ</th>
                <th className={TH}>Đơn vị</th>
                <th className={TH}>Cấp độ</th>
                <th className={TH}>Trạng thái</th>
                <th className={TH}>Quyết định</th>
                <th className={TH}>Thiết bị / Máy</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className={TR_HOVER}>
                  <td className={TD}>
                    <Link href={`/system-profiles/${p.id}`} className="font-medium text-brand-700 hover:underline">
                      {p.name}
                    </Link>
                    <div className="text-xs text-slate-500">{p.code}</div>
                  </td>
                  <td className={`${TD} text-sm`}>{p.org_name ?? p.org_id}</td>
                  <td className={TD}><LevelBadge level={p.level} /></td>
                  <td className={TD}>
                    <div className="flex flex-col gap-1">
                      <StatusBadge status={p.status} />
                      {p.status === "rejected" && p.review_note && (
                        <span className="text-xs text-rose-600">{p.review_note}</span>
                      )}
                    </div>
                  </td>
                  <td className={`${TD} text-sm`}>
                    {p.decision_number ? (
                      <>
                        <div className="font-medium">{p.decision_number}</div>
                        <div className="text-xs text-slate-500">{p.decision_agency}</div>
                      </>
                    ) : (
                      <span className="text-xs text-slate-400">— chưa đáp ứng —</span>
                    )}
                  </td>
                  <td className={`${TD} text-sm`}>{p.device_count} thiết bị / {p.machine_count} máy</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
