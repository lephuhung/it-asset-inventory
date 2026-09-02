"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { BellRing, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertRule, AlertTemplate, AlertRuleTestResult, Organization } from "@/lib/types";
import { ALERT_CATEGORY_META, ORG_TYPE_META } from "@/lib/format";
import { useFlatOrgs } from "@/lib/use-flat-orgs";
import {
  Badge, Button, Card, ConfirmDialog, EmptyState, ErrorBanner,
  Field, IconButton, Input, PageResponse, Select, Spinner, Pagination,
} from "@/components/ui";

const SCOPE_OPTIONS = [
  { value: "org_only", label: "Một tổ chức (không gồm đơn vị con)" },
  { value: "org_tree", label: "Tổ chức + đơn vị trực thuộc" },
  { value: "system", label: "Toàn hệ thống (chỉ Super Admin)" },
];

export default function SubscriptionsTab({
  isSuperAdmin, templates, orgs,
}: {
  isSuperAdmin: boolean;
  templates: AlertTemplate[];
  orgs: Organization[];
}) {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [page, setPage] = useState<PageResponse<AlertRule>>({ items: [], total: 0, limit: 50, offset: 0 });
  const [offset, setOffset] = useState(0);
  const flatOrgs = useFlatOrgs(orgs);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // form
  const [name, setName] = useState("");
  const [templateCode, setTemplateCode] = useState("machine_new");
  const [scopeMode, setScopeMode] = useState<"org_only" | "org_tree" | "system">("org_only");
  const [orgId, setOrgId] = useState("");
  const [thresholdDays, setThresholdDays] = useState(7);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AlertRule | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [testResult, setTestResult] = useState<AlertRuleTestResult | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const r = await api.get<PageResponse<AlertRule>>("/alert-rules", { limit: 50, offset });
      setRules(r.items);
      setPage(r);
      setError(null);
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : "Không tải được rule");
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => { void load(); }, [load]);

  const selectedTemplate = templates.find((t) => t.code === templateCode);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const config: Record<string, unknown> = {};
      if (selectedTemplate?.code === "machine_lost") config.threshold_days = thresholdDays;
      await api.post<AlertRule>("/alert-rules", {
        name,
        template_code: templateCode,
        org_id: scopeMode === "system" ? null : orgId || null,
        scope_mode: scopeMode,
        recipient_mode: "org_admins_and_super",
        config,
      });
      setName("");
      setTestResult(null);
      await load(true);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không tạo được rule");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleRule = async (rule: AlertRule) => {
    try {
      await api.patch(`/alert-rules/${rule.id}`, { enabled: !rule.enabled });
      await load(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Cập nhật thất bại"); }
  };

  const removeRule = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.delete(`/alert-rules/${removing.id}`);
      setRemoving(null);
      await load(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Xóa thất bại"); }
    finally { setRemoveBusy(false); }
  };

  const runTest = async (rule: AlertRule) => {
    setTestingId(rule.id);
    setTestResult(null);
    try {
      const r = await api.post<AlertRuleTestResult>(`/alert-rules/${rule.id}/test`, { context: {} });
      setTestResult(r);
    } catch (e) { setError(e instanceof Error ? e.message : "Test thất bại"); }
    finally { setTestingId(null); }
  };

  const canSystem = isSuperAdmin;
  const effectiveScopeOptions = SCOPE_OPTIONS.filter((o) => o.value !== "system" || canSystem);

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="Subscriptions" subtitle="Mỗi rule bind 1 template + phạm vi + người nhận mặc định (Org Admin + Super Admin)" padded={false}>
        {loading && rules.length === 0 ? <Spinner /> : rules.length === 0 ? (
          <EmptyState icon={<BellRing className="size-10" />} title="Chưa có rule nào" description="Tạo rule đầu tiên ở form bên phải." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {rules.map((r) => {
              const tpl = templates.find((t) => t.code === r.template_code);
              const cat = ALERT_CATEGORY_META[tpl?.category ?? "system"] ?? ALERT_CATEGORY_META.system;
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <span className={`flex size-9 items-center justify-center rounded-lg ${r.enabled ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-400"}`}>
                    <BellRing className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-800">{r.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge className={cat.badge}>{tpl?.name ?? r.template_code}</Badge>
                      <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">
                        {SCOPE_OPTIONS.find((o) => o.value === r.scope_mode)?.label ?? r.scope_mode}
                      </Badge>
                      {typeof r.config?.threshold_days === "number" && (
                        <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">&gt; {r.config.threshold_days} ngày</Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button variant="outline" size="sm" onClick={() => void runTest(r)} disabled={testingId === r.id}>
                      {testingId === r.id ? "Đang test…" : "Test"}
                    </Button>
                    <button role="switch" aria-checked={r.enabled} aria-label={r.enabled ? `Tắt rule ${r.name}` : `Bật rule ${r.name}`}
                      onClick={() => void toggleRule(r)}
                      className={`relative h-6 w-10 cursor-pointer rounded-full transition-colors ${r.enabled ? "bg-emerald-500" : "bg-slate-300"}`}>
                      <span className={`absolute top-1 size-4 rounded-full bg-white transition-all ${r.enabled ? "left-5" : "left-1"}`} />
                    </button>
                    <IconButton label={`Xóa rule ${r.name}`} onClick={() => setRemoving(r)} className="hover:bg-rose-50 hover:text-rose-600">
                      <Trash2 className="size-4" />
                    </IconButton>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <Pagination page={page} onChange={(o) => { setOffset(o); void load(true); }} />
      </Card>

      <Card title="Tạo rule mới">
        <form onSubmit={create} className="space-y-3">
          <Field label="Tên rule" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Máy mới ở Sở Công an" required />
          </Field>
          <Field label="Mẫu alert" required>
            <Select value={templateCode} onChange={(e) => { setTemplateCode(e.target.value); setTestResult(null); }}>
              {templates.map((t) => (
                <option key={t.code} value={t.code}>{t.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Phạm vi" required hint={scopeMode === "system" ? "Chỉ Super Admin" : undefined}>
            <Select value={scopeMode} onChange={(e) => setScopeMode(e.target.value as typeof scopeMode)}>
              {effectiveScopeOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          </Field>
          {scopeMode !== "system" && (
            <Field label="Tổ chức" required hint="Chọn tổ chức trong phạm vi bạn quản lý">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">— Chọn tổ chức —</option>
                {flatOrgs.map(({ org, depth }) => {
                  const meta = ORG_TYPE_META[org.type];
                  return (
                    <option key={org.id} value={org.id}>{"— ".repeat(depth)}{org.name} ({meta?.label ?? org.type})</option>
                  );
                })}
              </Select>
            </Field>
          )}
          {selectedTemplate?.code === "machine_lost" && (
            <Field label="Ngưỡng mất liên lạc (ngày)" required>
              <Input type="number" min={1} max={365} value={thresholdDays} onChange={(e) => setThresholdDays(Number(e.target.value))} />
            </Field>
          )}
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Người nhận: <b>Org Admin của phạm vi + Super Admin</b> (Org Admin tự tắt nhận qua Cài đặt thông báo)
          </div>
          {formError && <p className="text-sm text-rose-600">{formError}</p>}
          <Button type="submit" loading={submitting} className="w-full" disabled={!name || (scopeMode !== "system" && !orgId)}>
            <Plus className="size-4" /> Tạo rule
          </Button>
        </form>
      </Card>

      {testResult && (
        <Card className="xl:col-span-3" title="Kết quả test (dry-run — không gửi)">
          <div className="space-y-2 text-sm">
            <p className="font-medium">{testResult.title}</p>
            {testResult.body && <pre className="whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-600">{testResult.body}</pre>}
            <p className="text-xs text-slate-500">{testResult.total_recipients} người nhận</p>
            {testResult.recipients.length > 0 && (
              <ul className="max-h-40 overflow-y-auto rounded border border-slate-200 divide-y divide-slate-100 text-xs">
                {testResult.recipients.map((u) => (
                  <li key={u.user_id} className="flex items-center justify-between px-3 py-1.5">
                    <span>{u.full_name || u.email}</span>
                    <Badge className={u.telegram_linked ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-500 ring-slate-500/20"}>
                      {u.telegram_linked ? "Telegram ✓" : "Chưa link TG"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            {testResult.warnings.length > 0 && (
              <p className="text-xs text-amber-600">Warning: {testResult.warnings.join(", ")}</p>
            )}
          </div>
        </Card>
      )}

      <ConfirmDialog open={removing !== null} onClose={() => setRemoving(null)} title="Xóa alert rule" danger
        loading={removeBusy} confirmLabel="Xóa rule" onConfirm={() => void removeRule()}
        message={<>Rule <b>{removing?.name}</b> sẽ bị xóa vĩnh viễn.</>} />
    </div>
  );
}
