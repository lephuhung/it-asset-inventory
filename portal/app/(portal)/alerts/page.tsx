"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Bell, BellRing, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertEvent, AlertRule, AlertRuleType, Organization } from "@/lib/types";
import {
  ALERT_CHANNEL_META,
  ALERT_RULE_TYPE_META,
  ALERT_SEVERITY_META,
  ORG_TYPE_META,
  flattenOrgTree,
  formatDateTime,
  timeAgo,
} from "@/lib/format";
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
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";

const RULE_TYPES: Array<{ value: AlertRuleType; label: string }> = [
  { value: "machine_new", label: "Máy mới xuất hiện" },
  { value: "machine_lost", label: "Mất liên lạc > N ngày" },
  { value: "software_new", label: "Phần mềm lạ" },
  { value: "hardware_changed", label: "Phần cứng thay đổi" },
];

const CHANNELS = ["email", "telegram", "zalo"];

export default function AlertsPage() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form tạo rule
  const [name, setName] = useState("");
  const [ruleType, setRuleType] = useState<AlertRuleType>("machine_lost");
  const [orgId, setOrgId] = useState("");
  const [thresholdDays, setThresholdDays] = useState(7);
  const [channels, setChannels] = useState<string[]>(["email"]);
  const [targets, setTargets] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const [r, e] = await Promise.all([
        api.get<AlertRule[]>("/alert-rules"),
        api.get<AlertEvent[]>("/alert-rules/events", { limit: 50 }),
      ]);
      setRules(r);
      setEvents(e);
      setError(null);
    } catch (err) {
      if (!silent) setError(err instanceof Error ? err.message : "Không tải được alert");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    api
      .get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
  }, [load]);

  const toggleChannel = (c: string) => {
    setChannels((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      await api.post<AlertRule>("/alert-rules", {
        name,
        rule_type: ruleType,
        org_id: orgId || null,
        enabled: true,
        threshold_days: ruleType === "machine_lost" ? thresholdDays : null,
        channels,
        notify_targets: targets
          .split(/[\n,;]+/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setName("");
      setTargets("");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cập nhật thất bại");
    }
  };

  const removeRule = async (rule: AlertRule) => {
    if (!window.confirm(`Xóa rule "${rule.name}"?`)) return;
    try {
      await api.delete(`/alert-rules/${rule.id}`);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Xóa thất bại");
    }
  };

  return (
    <div>
      <PageHeader
        title="Cảnh báo (Alert rules)"
        description="Phát hiện máy mới, mất liên lạc, phần mềm lạ, phần cứng đổi → gửi Email / Telegram / Zalo (tính năng #14-15)"
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Alert rules"
          subtitle="Job quét chạy mỗi phút; mỗi rule + máy + ngày chỉ cảnh báo 1 lần"
          padded={false}
        >
          {loading && rules.length === 0 ? (
            <Spinner />
          ) : rules.length === 0 ? (
            <EmptyState
              icon={<Bell className="size-10" />}
              title="Chưa có rule nào"
              description="Tạo rule đầu tiên ở form bên phải."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {rules.map((r) => {
                const meta = ALERT_RULE_TYPE_META[r.rule_type] ?? {
                  label: r.rule_type,
                  badge: "bg-slate-100 text-slate-600 ring-slate-500/20",
                };
                return (
                  <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                    <span className={`flex size-9 items-center justify-center rounded-lg ${r.enabled ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-400"}`}>
                      <BellRing className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-800">{r.name}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Badge className={meta.badge}>{meta.label}</Badge>
                        {r.rule_type === "machine_lost" && r.threshold_days && (
                          <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">
                            &gt; {r.threshold_days} ngày
                          </Badge>
                        )}
                        {(r.channels ?? []).map((c) => (
                          <Badge key={c} className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                            {ALERT_CHANNEL_META[c] ?? c}
                          </Badge>
                        ))}
                        {r.org_id === null && (
                          <Badge className="bg-violet-50 text-violet-700 ring-violet-600/20">Toàn hệ thống</Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => void toggleRule(r)}
                        className={`relative h-5 w-9 rounded-full transition-colors ${r.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
                        title={r.enabled ? "Tắt rule" : "Bật rule"}
                      >
                        <span className={`absolute top-0.5 size-4 rounded-full bg-white transition-all ${r.enabled ? "left-4.5 left-[18px]" : "left-0.5"}`} />
                      </button>
                      <button
                        onClick={() => void removeRule(r)}
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                        title="Xóa rule"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Tạo rule mới">
          <form onSubmit={create} className="space-y-3">
            <Field label="Tên rule" required>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Máy mất liên lạc 7 ngày" required />
            </Field>
            <Field label="Loại cảnh báo" required>
              <Select value={ruleType} onChange={(e) => setRuleType(e.target.value as AlertRuleType)}>
                {RULE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Field>
            {orgs.length > 0 && (
              <Field label="Phạm vi tổ chức" hint="Bỏ trống = toàn hệ thống (Super Admin)">
                <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  <option value="">— Toàn hệ thống —</option>
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
            {ruleType === "machine_lost" && (
              <Field label="Ngưỡng mất liên lạc (ngày)" required>
                <Input type="number" min={1} max={365} value={thresholdDays} onChange={(e) => setThresholdDays(Number(e.target.value))} />
              </Field>
            )}
            <Field label="Kênh nhận">
              <div className="flex flex-wrap gap-2">
                {CHANNELS.map((c) => (
                  <label key={c} className="flex items-center gap-1.5 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={channels.includes(c)}
                      onChange={() => toggleChannel(c)}
                      className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    {ALERT_CHANNEL_META[c]}
                  </label>
                ))}
              </div>
            </Field>
            <Field label="Người nhận" hint="Email (phân cách bởi dấu phẩy / dòng mới). Telegram/Zalo dùng cấu hình bot ở server (.env)">
              <Input value={targets} onChange={(e) => setTargets(e.target.value)} placeholder="it@example.gov.vn, admin@example.gov.vn" />
            </Field>
            {formError && <p className="text-sm text-rose-600">{formError}</p>}
            <Button type="submit" loading={submitting} className="w-full" disabled={!name}>
              <Plus className="size-4" /> Tạo rule
            </Button>
          </form>
        </Card>
      </div>

      <Card
        className="mt-6"
        title="Lịch sử cảnh báo"
        subtitle={`${events.length} sự kiện gần nhất — gửi thành công qua kênh cấu hình hay chỉ ghi log`}
        padded={false}
      >
        {events.length === 0 ? (
          <EmptyState icon={<BellRing className="size-10" />} title="Chưa có cảnh báo nào" description="Cảnh báo sẽ xuất hiện khi rule kích hoạt." />
        ) : (
          <div className={TABLE_WRAP}>
            <table className={TABLE}>
              <thead className={THEAD}>
                <tr>
                  <th className={TH}>Thời gian</th>
                  <th className={TH}>Mức độ</th>
                  <th className={TH}>Nội dung</th>
                  <th className={TH}>Kênh</th>
                  <th className={TH}>Gửi</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => {
                  const sev = ALERT_SEVERITY_META[ev.severity] ?? ALERT_SEVERITY_META.info;
                  return (
                    <tr key={ev.id} className={TR_HOVER}>
                      <td className={`${TD} text-xs`} title={formatDateTime(ev.created_at)}>
                        {timeAgo(ev.created_at)}
                      </td>
                      <td className={TD}>
                        <Badge className={sev.badge}>{sev.label}</Badge>
                      </td>
                      <td className={`${TD} text-sm text-slate-700`}>{ev.message}</td>
                      <td className={`${TD} text-xs text-slate-500`}>
                        {(ev.channels ?? []).map((c) => ALERT_CHANNEL_META[c] ?? c).join(", ") || "—"}
                      </td>
                      <td className={TD}>
                        <Badge className={ev.delivered ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-500 ring-slate-500/20"}>
                          {ev.delivered ? "Đã gửi" : "Chưa gửi"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}