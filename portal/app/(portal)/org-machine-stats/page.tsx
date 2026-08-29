"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Briefcase, HardDriveDownload, Monitor, Tags, User } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Card, ErrorBanner, PageHeader, PageResponse, Select, Spinner } from "@/components/ui";
import { ORG_TYPE_META, tagBadgeClass } from "@/lib/format";
import type { Tag, TagStatsResponse } from "@/lib/types";

/** Thống kê số máy theo tổ chức — phân loại theo tag (cá nhân / công vụ / BMNN). */

interface OrgMachineStat {
  org_id: string;
  org_name: string;
  org_type: string;
  total: number;
  personal: number;
  official: number;
  bmnn: number;
  with_agent: number;
  pending: number;
}

const COLORS = {
  personal: "var(--color-sky-600, #0ea5e9)",
  official: "var(--color-brand-600, #0075de)",
  bmnn: "#dd5b00",
  pending: "#cbd5e1",
};

/** Màu mặc định khi tag không có color (theo kind). */
const KIND_COLORS: Record<string, string> = {
  classification: "#7c3aed",
  purpose: "#0891b2",
};

export default function OrgMachineStatsPage() {
  const [stats, setStats] = useState<OrgMachineStat[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Thống kê theo tag / kind ──
  const [tagStats, setTagStats] = useState<TagStatsResponse | null>(null);
  const [tagStatsLoading, setTagStatsLoading] = useState(false);
  const [tagStatsError, setTagStatsError] = useState<string | null>(null);
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [kindFilter, setKindFilter] = useState<"all" | "classification" | "purpose">("all");
  const [selectedTagKey, setSelectedTagKey] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const data = await api.get<PageResponse<OrgMachineStat>>("/orgs/machine-stats", { limit: 50 });
      setStats(data.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được thống kê theo tổ chức");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Load thống kê theo tag + danh sách tag (cho bộ lọc kind)
  const loadTagStats = useCallback(async () => {
    setTagStatsLoading(true);
    setTagStatsError(null);
    try {
      const [ts, tags] = await Promise.all([
        api.get<TagStatsResponse>("/stats/tags"),
        api.get<Tag[]>("/tags"),
      ]);
      setTagStats(ts);
      setAllTags(Array.isArray(tags) ? tags : []);
    } catch (e) {
      setTagStatsError(e instanceof Error ? e.message : "Không tải được thống kê theo loại máy & mục đích");
    } finally {
      setTagStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTagStats();
  }, [loadTagStats]);

  /** Tổng toàn hệ thống — nguồn cho donut phân loại. Công vụ = official + bmnn. */
  const overall = useMemo(() => {
    const acc = { personal: 0, official: 0, bmnn: 0, pending: 0, with_agent: 0, total: 0 };
    for (const s of stats ?? []) {
      acc.personal += s.personal;
      acc.official += s.official;
      acc.bmnn += s.bmnn;
      acc.pending += s.pending;
      acc.with_agent += s.with_agent;
      acc.total += s.total;
    }
    return acc;
  }, [stats]);

  const donutSlices = useMemo(() => {
    if (!overall.total) return [];
    const slices = [
      { label: "Máy cá nhân", count: overall.personal, color: COLORS.personal },
      { label: "Máy công vụ (thuần)", count: overall.official, color: COLORS.official },
      { label: "Máy BMNN (là công vụ)", count: overall.bmnn, color: COLORS.bmnn },
      { label: "Chờ duyệt", count: overall.pending, color: COLORS.pending },
    ].filter((s) => s.count > 0);
    let acc = 0;
    return slices.map((s) => {
      const from = (acc / overall.total) * 100;
      acc += s.count;
      const to = (acc / overall.total) * 100;
      return { ...s, from, to };
    });
  }, [overall]);

  const donutGradient =
    (donutSlices?.length ?? 0) > 0
      ? `conic-gradient(${donutSlices.map((s) => `${s.color} ${s.from}% ${s.to}%`).join(", ")})`
      : "conic-gradient(var(--color-slate-100) 0% 100%)";

  // ── Chọn tag cho thống kê chi tiết ──
  const tagOptions = useMemo(() => {
    const list = allTags.filter((t) => kindFilter === "all" || t.kind === kindFilter);
    return [...list].sort((a, b) => {
      const kindCmp = a.kind === b.kind ? 0 : a.kind === "classification" ? -1 : 1;
      return kindCmp !== 0 ? kindCmp : a.label.localeCompare(b.label);
    });
  }, [allTags, kindFilter]);

  // Tag được chọn: ưu tiên theo key; fallback sang option đầu tiên phù hợp kind
  const selectedTag = useMemo(() => {
    const byKey = tagOptions.find((t) => t.key === selectedTagKey);
    if (byKey) return byKey;
    return tagOptions[0] ?? null;
  }, [tagOptions, selectedTagKey]);

  const selectedStat = useMemo(() => {
    if (!selectedTag || !tagStats) return null;
    return tagStats.tags.find((t) => t.key === selectedTag.key) ?? null;
  }, [selectedTag, tagStats]);

  // Khi đổi kind mà tag đang chọn không thuộc kind → tự chọn lại
  useEffect(() => {
    if (selectedTag && kindFilter !== "all" && selectedTag.kind !== kindFilter) {
      const first = tagOptions[0];
      setSelectedTagKey(first ? first.key : "");
    }
  }, [kindFilter, tagOptions, selectedTag]);

  /** Donut phân bố tag theo tổ chức. */
  const tagDonut = useMemo(() => {
    if (!selectedStat || selectedStat.count === 0) return { slices: [] as Array<{ label: string; count: number; color: string; from: number; to: number }>, gradient: "" };
    const total = selectedStat.count;
    const palette = ["#0ea5e9", "#0075de", "#7c3aed", "#0891b2", "#dd5b00", "#16a34a", "#dc2626", "#64748b"];
    let acc = 0;
    const slices = selectedStat.org_stats
      .filter((o) => o.count > 0)
      .sort((a, b) => b.count - a.count)
      .map((o, i) => {
        const from = (acc / total) * 100;
        acc += o.count;
        const to = (acc / total) * 100;
        return { label: o.org_name, count: o.count, color: palette[i % palette.length], from, to };
      });
    return {
      slices,
      gradient: `conic-gradient(${slices.map((s) => `${s.color} ${s.from}% ${s.to}%`).join(", ")})`,
    };
  }, [selectedStat]);

  if (loading && !stats) return <Spinner label="Đang tải thống kê tổ chức…" />;

  const congVu = overall.official + overall.bmnn;

  return (
    <div>
      <PageHeader
        title="Thống kê máy theo tổ chức"
        description="Phân loại máy: cá nhân (không tính vào công vụ) · công vụ (gồm cả BMNN) · BMNN — theo loại máy và mục đích sử dụng đã gán"
        actions={
          <button
            onClick={() => {
              void load();
              void loadTagStats();
            }}
            className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
          >
            Nạp lại
          </button>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {/* ── KPI tổng quan ── */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Tổng số máy", value: overall.total, icon: Monitor, chip: "bg-slate-100 text-slate-600" },
          { label: "Máy cá nhân", value: overall.personal, icon: User, chip: "bg-sky-50 text-sky-600" },
          { label: "Máy công vụ (gồm BMNN)", value: congVu, icon: Briefcase, chip: "bg-emerald-50 text-emerald-600" },
          { label: "Trong đó: Máy BMNN", value: overall.bmnn, icon: HardDriveDownload, chip: "bg-amber-50 text-amber-600" },
        ].map((kpi) => (
          <div key={kpi.label} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{kpi.label}</p>
              <span className={`flex size-7 items-center justify-center rounded-md ${kpi.chip}`}>
                <kpi.icon className="size-3.5" />
              </span>
            </div>
            <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-slate-900">{kpi.value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* ── Biểu đồ tròn tỉ lệ phân loại toàn bộ ── */}
        <Card title="Tỉ lệ phân loại máy" subtitle={`Toàn bộ ${overall.total} máy của hệ thống`}>
          <div className="flex items-center gap-5">
            <div
              role="img"
              aria-label="Biểu đồ tròn tỉ lệ máy cá nhân, công vụ và BMNN"
              className="relative size-36 shrink-0 rounded-full transition-colors"
              style={{ background: donutGradient }}
            >
              <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-white shadow-sm">
                <span className="text-2xl font-bold tabular-nums tracking-tight text-slate-900">{overall.total}</span>
                <span className="text-[10px] uppercase tracking-wide text-slate-400">máy</span>
              </div>
            </div>
            <ul className="min-w-0 flex-1 space-y-2">
              {[...donutSlices].sort((a, b) => b.count - a.count).map((s) => (
                <li key={s.label} className="flex items-center gap-2 text-sm">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
                  <span className="min-w-0 flex-1 truncate text-slate-600">{s.label}</span>
                  <b className="tabular-nums text-slate-900">{s.count}</b>
                  <span className="w-9 shrink-0 text-right text-xs tabular-nums text-slate-400">
                    {overall.total > 0 ? Math.round((s.count / overall.total) * 100) : 0}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-snug text-slate-500">
            Máy công vụ = công vụ thuần + BMNN. Máy cá nhân <b>không</b> tính vào công vụ.
            Tag mục đích (dịch vụ công, soạn thảo văn bản…) không ảnh hưởng số liệu này.
          </p>
        </Card>

        {/* ── Bảng chi tiết theo tổ chức ── */}
        <Card title="Chi tiết theo tổ chức" className="lg:col-span-2">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3 font-semibold whitespace-nowrap">Tổ chức</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Tổng</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Cá nhân</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Công vụ</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">BMNN</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Có agent</th>
                  <th className="px-4 py-3 text-right font-semibold whitespace-nowrap">Chờ duyệt</th>
                </tr>
              </thead>
              <tbody>
                {(stats ?? []).map((s) => (
                  <tr key={s.org_id} className="transition-colors hover:bg-slate-50/70">
                    <td className="border-b border-slate-100 px-4 py-3 align-middle">
                      <Link href="/machines" className="font-medium text-slate-800 hover:text-brand-700">
                        {s.org_name}
                      </Link>
                      <Badge className="ml-2 bg-zinc-100 text-zinc-600 ring-zinc-500/20">
                        {ORG_TYPE_META[s.org_type as keyof typeof ORG_TYPE_META]?.label ?? s.org_type}
                      </Badge>
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right font-semibold tabular-nums text-slate-900">{s.total}</td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-slate-700">{s.personal}</td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-emerald-700">{s.official}</td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-amber-700">{s.bmnn}</td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-slate-500">{s.with_agent}</td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right tabular-nums text-slate-400">{s.pending}</td>
                  </tr>
                ))}
                {(stats ?? []).length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-400">
                      Chưa có dữ liệu máy
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* ── Thống kê theo loại máy & mục đích sử dụng ── */}
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            <Tags className="size-4 text-violet-600" /> Thống kê theo loại máy & mục đích sử dụng
          </span> as unknown as string
        }
        subtitle="Chọn loại máy (cá nhân / công vụ / BMNN) hoặc mục đích sử dụng (dịch vụ công, soạn thảo văn bản…) — hệ thống đếm số máy thuộc loại / mang mục đích đó, phân bố theo tổ chức (1 máy có thể có nhiều mục đích sử dụng)"
        className="mt-6"
      >
        {/* Bộ lọc */}
        <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Loại thống kê</label>
            <Select value={kindFilter} onChange={(e) => setKindFilter(e.target.value as "all" | "classification" | "purpose")}>
              <option value="all">Tất cả</option>
              <option value="classification">Loại máy (phân loại)</option>
              <option value="purpose">Mục đích sử dụng</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Loại máy / mục đích</label>
            <Select value={selectedTag?.key ?? ""} onChange={(e) => setSelectedTagKey(e.target.value)}>
              {tagOptions.length === 0 && <option value="">Chưa có dữ liệu</option>}
              {tagOptions.map((t) => (
                <option key={t.id} value={t.key}>
                  {t.label} ({t.kind === "classification" ? "loại máy" : "mục đích"})
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-end">
            <button
              onClick={() => void loadTagStats()}
              disabled={tagStatsLoading}
              className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {tagStatsLoading ? "Đang tải…" : "Nạp lại dữ liệu"}
            </button>
          </div>
        </div>

        {tagStatsError && (
          <div className="mb-4">
            <ErrorBanner message={tagStatsError} />
          </div>
        )}

        {tagStatsLoading && !tagStats ? (
          <Spinner label="Đang tải thống kê…" />
        ) : !selectedStat ? (
          <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
            Chọn 1 loại máy hoặc mục đích sử dụng để xem số máy thuộc loại / mang mục đích đó (theo tổ chức). Chưa có dữ liệu.
          </p>
        ) : (
          <div className="grid gap-6 lg:grid-cols-3">
            {/* Số liệu chính */}
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">Đang xem</p>
                  <Badge className={tagBadgeClass({ key: selectedStat.key, label: selectedStat.label, kind: selectedStat.kind, color: selectedStat.color })}>
                    {selectedStat.label}
                  </Badge>
                </div>
                <p className="mt-2 text-3xl font-bold tabular-nums tracking-tight text-slate-900">{selectedStat.count}</p>
                <p className="text-xs text-slate-400">
                  máy / tổng {tagStats?.total_machines ?? 0} máy
                  ({tagStats && tagStats.total_machines > 0 ? Math.round((selectedStat.count / tagStats.total_machines) * 100) : 0}%)
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">Phân bố theo tổ chức</p>
                <ul className="space-y-1.5">
                  {selectedStat.org_stats
                    .slice()
                    .sort((a, b) => b.count - a.count)
                    .map((o) => {
                      const pct = selectedStat.count > 0 ? Math.round((o.count / selectedStat.count) * 100) : 0;
                      return (
                        <li key={o.org_id} className="flex items-center gap-2 text-sm">
                          <span className="min-w-0 flex-1 truncate text-slate-600" title={o.org_name}>{o.org_name}</span>
                          <b className="tabular-nums text-slate-900">{o.count}</b>
                          <span className="w-9 shrink-0 text-right text-xs tabular-nums text-slate-400">{pct}%</span>
                        </li>
                      );
                    })}
                </ul>
              </div>
            </div>

            {/* Donut phân bố theo org */}
            <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white p-4">
              <div
                role="img"
                aria-label={`Biểu đồ tròn phân bố ${selectedStat.label} theo tổ chức`}
                className="relative size-40 shrink-0 rounded-full"
                style={{ background: tagDonut.gradient }}
              >
                <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-white shadow-sm">
                  <span className="text-2xl font-bold tabular-nums tracking-tight text-slate-900">{selectedStat.count}</span>
                  <span className="max-w-[80%] truncate text-[9px] uppercase tracking-wide text-slate-400">máy</span>
                </div>
              </div>
              <ul className="mt-4 w-full space-y-1.5">
                {tagDonut.slices.map((s) => (
                  <li key={s.label} className="flex items-center gap-2 text-xs">
                    <span className="size-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
                    <span className="min-w-0 flex-1 truncate text-slate-600" title={s.label}>{s.label}</span>
                    <b className="tabular-nums text-slate-900">{s.count}</b>
                    <span className="w-8 shrink-0 text-right tabular-nums text-slate-400">
                      {selectedStat.count > 0 ? Math.round((s.count / selectedStat.count) * 100) : 0}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Bar chart theo org */}
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <p className="mb-3 text-[11px] font-medium uppercase tracking-wider text-slate-400">Biểu đồ cột — máy theo tổ chức</p>
              <div className="space-y-2.5">
                {selectedStat.org_stats
                  .slice()
                  .sort((a, b) => b.count - a.count)
                  .map((o) => {
                    const max = selectedStat.org_stats.reduce((m, x) => Math.max(m, x.count), 1);
                    const pct = Math.round((o.count / max) * 100);
                    return (
                      <div key={o.org_id}>
                        <div className="mb-0.5 flex items-center justify-between gap-2 text-xs">
                          <span className="min-w-0 truncate text-slate-600" title={o.org_name}>{o.org_name}</span>
                          <b className="shrink-0 tabular-nums text-slate-900">{o.count}</b>
                        </div>
                        <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${Math.max(pct, 2)}%`, background: "var(--color-brand-600, #0075de)" }}
                          />
                        </div>
                      </div>
                    );
                  })}
              </div>
              <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-snug text-slate-500">
                Một máy có thể có nhiều mục đích sử dụng → máy được đếm ở mọi mục đích nó mang.
                Dữ liệu trong phạm vi tổ chức bạn được phép xem.
              </p>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
