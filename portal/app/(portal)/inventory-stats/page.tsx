"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AppWindow,
  Cpu,
  Flame,
  MemoryStick,
  Monitor,
  RefreshCcw,
  Shield,
  ShieldCheck,
  ShieldOff,
  Timer,
} from "lucide-react";
import { api } from "@/lib/api";
import type { InventoryStatsResponse, Organization, StatBucket } from "@/lib/types";
import { ORG_TYPE_META } from "@/lib/format";
import { useFlatOrgs } from "@/lib/use-flat-orgs";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  KpiCard,
  PageHeader,
  Select,
  Spinner,
} from "@/components/ui";

/**
 * Trang Thống kê cấu hình máy — đọc `GET /api/stats/inventory`.
 *
 * Phạm vi thống kê:
 *   - Hệ điều hành (by_os_family: Win10/Win11/Linux/Windows Server…)
 *   - Kiến trúc CPU (by_os_arch: x64 / ARM64)
 *   - Máy ảo / vật lý (by_is_vm)
 *   - Dung lượng RAM (by_ram_gb: <4 / 4–8 / 8–16 / 16–32 / 32+ GB)
 *   - Top phần mềm cài nhiều nhất (top_software)
 *   - Bảo mật: firewall, Windows Update (status + enabled), antivirus, bitlocker
 *
 * Có filter theo tổ chức (cây UBND/Sở ban ngành) — quyền admin đã được RBAC
 * xử lý từ backend.
 */
export default function InventoryStatsPage() {
  const [data, setData] = useState<InventoryStatsResponse | null>(null);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const flatOrgs = useFlatOrgs(orgs);
  const [orgId, setOrgId] = useState<string>("");
  const [topLimit, setTopLimit] = useState<number>(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<Date | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const [s, o] = await Promise.all([
          api.get<InventoryStatsResponse>("/stats/inventory", {
            org_id: orgId || undefined,
            top_software_limit: topLimit,
          }),
          orgs.length === 0
            ? api.get<Organization[]>("/orgs").catch(() => [] as Organization[])
            : Promise.resolve(orgs),
        ]);
        setData(s);
        setOrgs(Array.isArray(o) ? o : []);
        setGeneratedAt(new Date());
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Không tải được thống kê");
      } finally {
        setLoading(false);
      }
    },
    [orgId, topLimit, orgs],
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, topLimit]);

  // Tổng hợp nhanh để hiển thị KPI trên đầu trang
  const kpis = useMemo(() => {
    if (!data) return null;
    return {
      total: data.total_machines,
      firewallOn: bucketValue(arr(data.by_firewall), "true"),
      firewallUnknown: bucketValue(arr(data.by_firewall), "unknown"),
      updateEnabled: bucketValue(arr(data.by_windows_update_enabled), "true"),
      updatePending: bucketValue(arr(data.by_windows_update_status), "pending"),
      updateUpToDate: bucketValue(arr(data.by_windows_update_status), "up-to-date"),
      antivirusOn: bucketValue(arr(data.by_antivirus), "true"),
    };
  }, [data]);

  // Bản đồ tên hiển thị cho từng nhóm OS (đồng bộ với backend)
  const OS_LABELS: Record<string, string> = {
    windows_11: "Windows 11",
    windows_10: "Windows 10",
    windows_server_2022: "Windows Server 2022",
    windows_server_2019: "Windows Server 2019",
    windows_server_2016: "Windows Server 2016",
    windows_server_other: "Windows Server (khác)",
    linux: "Linux",
    macos: "macOS",
    other: "Khác",
  };

  const UPDATE_STATUS_LABELS: Record<string, string> = {
    "up-to-date": "Đã cập nhật",
    pending: "Có bản chờ cài",
    paused: "Tạm dừng",
    unknown: "Không xác định",
  };

  const BITLOCKER_LABELS: Record<string, string> = {
    on: "Đang bật",
    off: "Đã tắt",
    unknown: "Không xác định",
  };

  return (
    <div>
      <PageHeader
        title="Thống kê cấu hình máy"
        description="Phân tích theo hệ điều hành, RAM, phần mềm phổ biến, số máy bật firewall và Windows Update — phạm vi theo quyền xem của bạn."
        actions={
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full bg-white px-3.5 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 transition-all hover:bg-slate-50 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCcw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
            Tính lại
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {/* Filter */}
      <Card title="Bộ lọc" className="mb-5">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {orgs.length > 0 && (
            <Field label="Tổ chức">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">Toàn bộ (cây tổ chức)</option>
                {flatOrgs.map(({ org, depth }) => (
                  <option key={org.id} value={org.id}>
                    {"— ".repeat(depth)}
                    {org.name} ({ORG_TYPE_META[org.type]?.label ?? org.type})
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Số app hiển thị trong Top phần mềm">
            <Select value={String(topLimit)} onChange={(e) => setTopLimit(Number(e.target.value))}>
              {[10, 20, 30, 50].map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex items-end text-xs text-slate-400">
            {generatedAt ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-500">
                <Timer className="size-3" /> Cập nhật {generatedAt.toLocaleTimeString("vi-VN")}
              </span>
            ) : (
              <span>—</span>
            )}
          </div>
        </div>
      </Card>

      {loading && !data ? (
        <Spinner label="Đang nạp thống kê cấu hình…" />
      ) : !data || data.total_machines === 0 ? (
        <EmptyState
          icon={<Cpu className="size-10" />}
          title="Chưa có dữ liệu cấu hình"
          description="Cần ít nhất 1 máy đã gửi inventory (os_family + ram_gb) để thống kê. Agent cũ chưa cung cấp trường security sẽ hiển thị 'Không xác định'."
        />
      ) : (
        <>
          {/* KPI cards */}
          <div className="mb-5 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <KpiCard
              label="Tổng máy"
              value={kpis?.total ?? 0}
              icon={<Monitor className="size-4 text-brand-600" />}
              accent="bg-brand-50"
            />
            <KpiCard
              label="Bật Firewall"
              value={kpis?.firewallOn ?? 0}
              icon={<ShieldCheck className="size-4 text-emerald-600" />}
              accent="bg-emerald-50"
              sub={kpis?.firewallUnknown ? `${kpis.firewallUnknown} máy chưa rõ` : undefined}
            />
            <KpiCard
              label="Bật Windows Update"
              value={kpis?.updateEnabled ?? 0}
              icon={<Shield className="size-4 text-sky-600" />}
              accent="bg-sky-50"
              sub={kpis?.updateUpToDate ? `${kpis.updateUpToDate} máy đã cập nhật` : undefined}
            />
            <KpiCard
              label="Có bản chờ cài"
              value={kpis?.updatePending ?? 0}
              icon={<ShieldOff className="size-4 text-amber-600" />}
              accent="bg-amber-50"
            />
            <KpiCard
              label="Bật Antivirus"
              value={kpis?.antivirusOn ?? 0}
              icon={<ShieldCheck className="size-4 text-violet-600" />}
              accent="bg-violet-50"
            />
            <KpiCard
              label="Số ứng dụng"
              value={arr(data.top_software).length}
              icon={<AppWindow className="size-4 text-amber-600" />}
              accent="bg-amber-50"
              sub="đang theo dõi"
            />
          </div>

          {/* Hàng 1: Hệ điều hành + RAM */}
          <div className="grid gap-5 lg:grid-cols-3">
            <BucketCard
              title="Hệ điều hành"
              subtitle="Phân bố theo OS family — đếm từ snapshot mới nhất của mỗi máy"
              icon={<Monitor className="size-4" />}
              buckets={sortOsFamily(arr(data.by_os_family))}
              total={data.total_machines}
              formatLabel={(k) => OS_LABELS[k] ?? prettifyUnknown(k)}
              accentMap={OS_ACCENT}
            />
            <BucketCard
              title="Dung lượng RAM"
              subtitle="Nhóm theo dung lượng RAM vật lý (GB) — cơ sở đánh giá nâng cấp"
              icon={<MemoryStick className="size-4" />}
              buckets={sortRamBuckets(arr(data.by_ram_gb))}
              total={data.total_machines}
              formatLabel={(k) => k}
              accentMap={RAM_ACCENT}
            />
            <BucketCard
              title="Kiến trúc CPU"
              subtitle="x64 / ARM64 — phục vụ quy hoạch triển khai phần mềm"
              icon={<Cpu className="size-4" />}
              buckets={sortByKey(arr(data.by_os_arch), ["X64", "ARM64", "X86", "UNKNOWN"])}
              total={data.total_machines}
              formatLabel={(k) => (k === "UNKNOWN" ? "Không rõ" : k)}
              accentMap={ARCH_ACCENT}
            />
          </div>

          {/* Hàng 2: Bảo mật */}
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <Card title="Bảo mật máy trạm" subtitle="Firewall · Windows Update · Antivirus · BitLocker" padded={false}>
              <div className="divide-y divide-slate-100">
                <SecurityRow
                  label="Firewall Windows"
                  icon={<Shield className="size-4 text-sky-600" />}
                  buckets={arr(data.by_firewall)}
                  total={data.total_machines}
                  valueLabels={{ true: "Bật", false: "Tắt", unknown: "Chưa rõ" }}
                  tone={{ true: "good", false: "bad", unknown: "muted" }}
                />
                <SecurityRow
                  label="Auto Windows Update"
                  icon={<ShieldCheck className="size-4 text-emerald-600" />}
                  buckets={arr(data.by_windows_update_enabled)}
                  total={data.total_machines}
                  valueLabels={{ true: "Đang bật", false: "Đã tắt", unknown: "Chưa rõ" }}
                  tone={{ true: "good", false: "bad", unknown: "muted" }}
                />
                <SecurityRow
                  label="Trạng thái Windows Update"
                  icon={<Shield className="size-4 text-amber-600" />}
                  buckets={arr(data.by_windows_update_status)}
                  total={data.total_machines}
                  valueLabels={UPDATE_STATUS_LABELS}
                  tone={{ "up-to-date": "good", pending: "warn", paused: "warn", unknown: "muted" }}
                />
                <SecurityRow
                  label="Antivirus"
                  icon={<ShieldCheck className="size-4 text-violet-600" />}
                  buckets={arr(data.by_antivirus)}
                  total={data.total_machines}
                  valueLabels={{ true: "Đang bật", false: "Đã tắt", unknown: "Chưa rõ" }}
                  tone={{ true: "good", false: "bad", unknown: "muted" }}
                />
                <SecurityRow
                  label="BitLocker"
                  icon={<Flame className="size-4 text-rose-600" />}
                  buckets={arr(data.by_bitlocker)}
                  total={data.total_machines}
                  valueLabels={BITLOCKER_LABELS}
                  tone={{ on: "good", off: "bad", unknown: "muted" }}
                />
              </div>
            </Card>

            <BucketCard
              title="Máy ảo / Vật lý"
              subtitle="Phục vụ phân bổ license và quy hoạch nguồn lực"
              icon={<Cpu className="size-4" />}
              buckets={sortIsVm(arr(data.by_is_vm))}
              total={data.total_machines}
              formatLabel={(k) => ({ true: "Máy ảo (VM)", false: "Máy vật lý", unknown: "Không rõ" })[k] ?? k}
              accentMap={{ true: "bg-violet-500", false: "bg-brand-600", unknown: "bg-slate-300" }}
              stacked
            />
          </div>

          {/* Hàng 3: Top phần mềm */}
          <Card
            title="Top phần mềm cài đặt"
            subtitle={`${arr(data.top_software).length} ứng dụng được cài nhiều nhất — đếm số máy cài (distinct)`}
            className="mt-5"
            padded={false}
          >
            {arr(data.top_software).length === 0 ? (
              <EmptyState
                icon={<AppWindow className="size-10" />}
                title="Chưa có dữ liệu phần mềm"
                description="Agent cần gửi trường `installed_software` để thống kê được cập nhật."
              />
            ) : (
              <TopSoftwareTable rows={arr(data.top_software)} total={data.total_machines} />
            )}
          </Card>

          <p className="mt-5 text-xs leading-relaxed text-slate-400">
            Nguồn dữ liệu: <code className="font-mono text-[11px]">machine_current</code> (snapshot
            mới nhất/máy) + <code className="font-mono text-[11px]">machine_software</code>. Phạm vi
            theo <Link href="/audit" className="text-brand-600 hover:underline">RBAC cây tổ chức</Link>;
            máy ở tổ chức ngoài quyền sẽ không hiển thị. Trường `unknown` = máy chưa gửi được dữ liệu
            (agent cũ, hoặc payload thiếu khóa).
          </p>
        </>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────── */
/* Helpers                                                       */
/* ────────────────────────────────────────────────────────────── */

function bucketValue(buckets: StatBucket[] | undefined, key: string): number {
  return (buckets ?? []).find((b) => b.key === key)?.count ?? 0;
}

/** Luôn trả về mảng — fallback `[]` khi backend cũ / response thiếu field
 * (vd proxy cache response trước khi schema cập nhật). Tránh "X is not iterable". */
function arr<T>(v: T[] | undefined | null): T[] {
  return Array.isArray(v) ? v : [];
}

function prettifyUnknown(k: string): string {
  if (k === "unknown") return "Không xác định";
  if (k === "true") return "Bật";
  if (k === "false") return "Tắt";
  return k;
}

/** Thứ tự ưu tiên cho OS family — đặt Win11/Win10 lên đầu dù count nhỏ. */
const OS_ORDER = [
  "windows_11",
  "windows_10",
  "windows_server_2022",
  "windows_server_2019",
  "windows_server_2016",
  "windows_server_other",
  "linux",
  "macos",
  "other",
  "unknown",
];

function sortOsFamily(b: StatBucket[] | undefined | null): StatBucket[] {
  const arr = Array.isArray(b) ? [...b] : [];
  arr.sort((a, b) => {
    const ia = OS_ORDER.indexOf(a.key);
    const ib = OS_ORDER.indexOf(b.key);
    if (ia !== -1 || ib !== -1) {
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    }
    return b.count - a.count;
  });
  return arr;
}

const RAM_ORDER = ["<4 GB", "4–8 GB", "8–16 GB", "16–32 GB", "32+ GB", "unknown"];

function sortRamBuckets(b: StatBucket[] | undefined | null): StatBucket[] {
  return sortByKey(b, RAM_ORDER);
}

function sortByKey(b: StatBucket[] | undefined | null, order: string[]): StatBucket[] {
  const arr = Array.isArray(b) ? [...b] : [];
  arr.sort((a, b) => {
    const ia = order.indexOf(a.key);
    const ib = order.indexOf(b.key);
    if (ia !== -1 || ib !== -1) {
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    }
    return b.count - a.count;
  });
  return arr;
}

function sortIsVm(b: StatBucket[] | undefined | null): StatBucket[] {
  return sortByKey(b, ["false", "true", "unknown"]);
}

/* Accent bars — dùng tone nhất quán theo nhóm ngữ nghĩa. */
const OS_ACCENT: Record<string, string> = {
  windows_11: "bg-brand-600",
  windows_10: "bg-sky-600",
  windows_server_2022: "bg-indigo-500",
  windows_server_2019: "bg-indigo-400",
  windows_server_2016: "bg-indigo-300",
  windows_server_other: "bg-indigo-300",
  linux: "bg-emerald-500",
  macos: "bg-slate-500",
  other: "bg-slate-400",
  unknown: "bg-slate-300",
};

const RAM_ACCENT: Record<string, string> = {
  "<4 GB": "bg-rose-500",
  "4–8 GB": "bg-amber-500",
  "8–16 GB": "bg-emerald-500",
  "16–32 GB": "bg-brand-600",
  "32+ GB": "bg-violet-500",
  unknown: "bg-slate-300",
};

const ARCH_ACCENT: Record<string, string> = {
  X64: "bg-brand-600",
  ARM64: "bg-emerald-500",
  X86: "bg-amber-500",
  UNKNOWN: "bg-slate-300",
};

/* ────────────────────────────────────────────────────────────── */
/* Sub-components                                                */
/* ────────────────────────────────────────────────────────────── */

function BucketCard({
  title,
  subtitle,
  icon,
  buckets,
  total,
  formatLabel,
  accentMap,
  stacked = false,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  buckets: StatBucket[];
  total: number;
  formatLabel: (k: string) => string;
  accentMap: Record<string, string>;
  /** true = mỗi bucket hiển thị stacked (count/total) thay vì bar tuyệt đối. */
  stacked?: boolean;
}) {
  const safeTotal = Math.max(1, total);
  const safeBuckets = Array.isArray(buckets) ? buckets : [];
  return (
    <Card title={title} subtitle={subtitle}>
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span className="flex size-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          {icon}
        </span>
        <span>
          Tổng <b className="tabular-nums text-slate-700">{total}</b> máy · {safeBuckets.length} nhóm
        </span>
      </div>

      {safeBuckets.length === 0 ? (
        <p className="mt-4 text-sm text-slate-400">Chưa có dữ liệu cho nhóm này.</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {safeBuckets.map((b) => {
            const pct = (b.count / safeTotal) * 100;
            const accent = accentMap[b.key] ?? "bg-slate-400";
            const tone =
              b.key === "unknown"
                ? "text-slate-500"
                : b.count > 0
                  ? "text-slate-700"
                  : "text-slate-400";
            return (
              <li key={b.key}>
                <div className="mb-1 flex items-baseline justify-between gap-2">
                  <span className={`truncate text-sm font-medium ${tone}`}>{formatLabel(b.key)}</span>
                  <span className="shrink-0 text-xs tabular-nums text-slate-500">
                    <b className="text-slate-700">{b.count}</b>
                    <span className="ml-1 text-slate-400">
                      ({pct.toFixed(pct < 10 ? 1 : 0)}%)
                    </span>
                  </span>
                </div>
                <div
                  className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100"
                  role="progressbar"
                  aria-valuenow={Math.round(pct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${formatLabel(b.key)}: ${b.count} / ${total}`}
                >
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${accent} ${stacked ? "opacity-90" : ""}`}
                    style={{ width: `${Math.max(2, pct)}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

type SecurityTone = "good" | "warn" | "bad" | "muted";

function SecurityRow({
  label,
  icon,
  buckets,
  total,
  valueLabels,
  tone,
}: {
  label: string;
  icon: React.ReactNode;
  buckets: StatBucket[];
  total: number;
  valueLabels: Record<string, string>;
  tone: Record<string, SecurityTone>;
}) {
  const safeTotal = Math.max(1, total);
  const safeBuckets = Array.isArray(buckets) ? buckets : [];
  const sortedKeys = Object.keys(valueLabels).filter((k) =>
    safeBuckets.some((b) => b.key === k),
  );
  // bổ sung key có trong buckets nhưng chưa khai báo trong valueLabels (defensive)
  for (const b of safeBuckets) {
    if (!sortedKeys.includes(b.key)) sortedKeys.push(b.key);
  }

  return (
    <div className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 px-5 py-4 sm:grid-cols-[180px_1fr_auto] sm:items-center">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
        <span className="flex size-7 items-center justify-center rounded-lg bg-slate-100">{icon}</span>
        {label}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {sortedKeys.length === 0 ? (
          <span className="text-xs text-slate-400">Chưa có dữ liệu</span>
        ) : (
          sortedKeys.map((k) => {
            const cnt = safeBuckets.find((b) => b.key === k)?.count ?? 0;
            const pct = (cnt / safeTotal) * 100;
            const t = tone[k] ?? "muted";
            const meta = SECURITY_TONE_META[t];
            return (
              <div key={k} className="flex items-center gap-1.5 text-xs">
                <Badge className={meta.badge}>{valueLabels[k] ?? prettifyUnknown(k)}</Badge>
                <span className="tabular-nums font-semibold text-slate-700">{cnt}</span>
                <span className="text-slate-400 tabular-nums">({pct.toFixed(0)}%)</span>
              </div>
            );
          })
        )}
      </div>

      <div className="col-span-2 mt-1 sm:col-span-1 sm:mt-0">
        <div className="flex h-2 w-32 overflow-hidden rounded-full bg-slate-100 sm:w-40">
          {sortedKeys.map((k) => {
            const cnt = safeBuckets.find((b) => b.key === k)?.count ?? 0;
            if (cnt === 0) return null;
            const pct = (cnt / safeTotal) * 100;
            const t = tone[k] ?? "muted";
            return (
              <div
                key={k}
                className={SECURITY_TONE_META[t].bar}
                style={{ width: `${pct}%` }}
                title={`${valueLabels[k] ?? k}: ${cnt} (${pct.toFixed(0)}%)`}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

const SECURITY_TONE_META: Record<SecurityTone, { badge: string; bar: string }> = {
  good: {
    badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    bar: "bg-emerald-500",
  },
  warn: {
    badge: "bg-amber-50 text-amber-700 ring-amber-600/20",
    bar: "bg-amber-500",
  },
  bad: {
    badge: "bg-rose-50 text-rose-700 ring-rose-600/20",
    bar: "bg-rose-500",
  },
  muted: {
    badge: "bg-slate-100 text-slate-500 ring-slate-500/20",
    bar: "bg-slate-300",
  },
};

function TopSoftwareTable({
  rows,
  total,
}: {
  rows: { name: string; machines: number }[];
  total: number;
}) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const safeTotal = Math.max(1, total);
  const max = Math.max(1, ...safeRows.map((r) => r.machines));
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          <tr>
            <th scope="col" className="px-4 py-3 font-semibold whitespace-nowrap">#</th>
            <th scope="col" className="px-4 py-3 font-semibold">Tên phần mềm</th>
            <th scope="col" className="px-4 py-3 font-semibold text-right">Số máy cài</th>
            <th scope="col" className="px-4 py-3 font-semibold">Tỉ lệ</th>
          </tr>
        </thead>
        <tbody>
          {safeRows.map((r, idx) => {
            const pct = (r.machines / safeTotal) * 100;
            const bar = (r.machines / max) * 100;
            return (
              <tr key={r.name} className="border-b border-slate-100 transition-colors last:border-b-0 hover:bg-slate-50/70">
                <td className="px-4 py-2.5 align-middle text-xs tabular-nums text-slate-400">{idx + 1}</td>
                <td className="px-4 py-2.5 align-middle">
                  <div className="flex items-center gap-2">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500">
                      <AppWindow className="size-3.5" />
                    </span>
                    <span className="font-medium text-slate-800">{r.name}</span>
                  </div>
                </td>
                <td className="px-4 py-2.5 align-middle text-right text-sm font-semibold tabular-nums text-slate-700">
                  {r.machines}
                  <span className="ml-1 text-xs font-normal text-slate-400">({pct.toFixed(0)}%)</span>
                </td>
                <td className="px-4 py-2.5 align-middle">
                  <div className="h-2 w-full max-w-xs overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-brand-600 transition-all duration-500"
                      style={{ width: `${Math.max(2, bar)}%` }}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
