"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BellOff, Check, Save, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { UserNotificationPref } from "@/lib/types";
import { ALERT_CATEGORY_META, ALERT_SEVERITY_META } from "@/lib/format";
import { useAuth } from "@/components/auth-context";
import { Badge, Button, Card, ErrorBanner, Select, Spinner, Toggle } from "@/components/ui";

const SEVERITY_OPTIONS = ["info", "success", "warning", "error", "critical"];

export default function NotificationPrefsPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [items, setItems] = useState<UserNotificationPref[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: UserNotificationPref[] }>("/me/notification-prefs");
      setItems(r.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được cấu hình");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const g: Record<string, UserNotificationPref[]> = {};
    for (const it of items) (g[it.category] ??= []).push(it);
    return g;
  }, [items]);

  const update = (code: string, patch: Partial<UserNotificationPref>) => {
    setItems((prev) => prev.map((it) => (it.template_code === code ? { ...it, ...patch } : it)));
    setSaved(false);
  };

  const saveAll = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.patch("/me/notification-prefs", {
        prefs: items.map((it) => ({
          template_code: it.template_code,
          muted: it.muted,
          min_severity: it.min_severity,
        })),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 5000);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner label="Đang tải cài đặt thông báo..." />;

  const enabledItems = items.filter((it) => it.opt_out_controls.length > 0);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="flex items-center gap-3">
        <BellOff className="size-7 text-brand-600" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Cài đặt nhận thông báo</h1>
          <p className="text-sm text-slate-500">
            Tùy chỉnh loại alert bạn muốn nhận. Thay đổi áp dụng cho cả cổng thông báo trên portal và Telegram.
          </p>
        </div>
      </header>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}
      {saved && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" /> Đã lưu cài đặt.
        </div>
      )}

      {isSuperAdmin && (
        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-slate-400" />
          <div>
            <p className="font-semibold">Bạn là Super Admin.</p>
            <p className="mt-1 text-xs">Super Admin luôn nhận mọi alert trong hệ thống và không thể tắt. Các control bên dưới không áp dụng cho bạn.</p>
          </div>
        </div>
      )}

      {enabledItems.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">Không có alert nào có tùy chọn nhận. Bạn nhận toàn bộ alert hệ thống.</p>
        </Card>
      ) : (
        Object.entries(grouped).map(([category, list]) => (
          <Card key={category} title={ALERT_CATEGORY_META[category]?.label ?? category}>
            <div className="divide-y divide-slate-100">
              {list.map((it) => (
                <div key={it.template_code} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-800">{it.template_name}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        Mức mặc định: <Badge className={ALERT_SEVERITY_META[it.default_severity]?.badge ?? ""}>{ALERT_SEVERITY_META[it.default_severity]?.label ?? it.default_severity}</Badge>
                      </p>
                    </div>
                    <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">{it.template_code}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-4">
                    {it.opt_out_controls.includes("template") && (
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <Toggle checked={!it.muted} onChange={(v: boolean) => update(it.template_code, { muted: !v })} label={`Nhận ${it.template_name}`} disabled={isSuperAdmin} />
                        <span className={it.muted ? "text-slate-400" : "text-slate-700"}>
                          {it.muted ? "Đang tắt" : "Đang nhận"}
                        </span>
                      </div>
                    )}
                    {it.opt_out_controls.includes("severity") && (
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <span className="text-xs text-slate-500">Chỉ nhận từ mức:</span>
                        <Select
                          value={it.min_severity ?? it.default_severity}
                          onChange={(e) => update(it.template_code, { min_severity: e.target.value })}
                          disabled={isSuperAdmin}
                          className="w-36"
                        >
                          {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{ALERT_SEVERITY_META[s]?.label ?? s}</option>)}
                        </Select>
                      </div>
                    )}
                    {it.opt_out_controls.length === 0 && (
                      <p className="text-xs text-slate-400">Luôn nhận (không có tùy chọn tắt).</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))
      )}

      {!isSuperAdmin && enabledItems.length > 0 && (
        <div className="sticky bottom-4 flex justify-end">
          <Button onClick={() => void saveAll()} loading={saving}>
            <Save className="size-3.5" /> Lưu cài đặt
          </Button>
        </div>
      )}
    </div>
  );
}
