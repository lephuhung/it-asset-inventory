"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  BellRing,
  Check,
  ExternalLink,
  History,
  Loader2,
  Plus,
  RefreshCw,
  SendHorizontal,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertEvent, AlertRule, AlertRuleType, NotificationOut, Organization } from "@/lib/types";
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
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Pagination,
  PageResponse,
  Select,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import { useNotifications, SEVERITY_BADGES } from "@/components/notification-bell";

const RULE_TYPES: Array<{ value: AlertRuleType; label: string }> = [
  { value: "machine_new", label: "Máy mới xuất hiện" },
  { value: "machine_lost", label: "Mất liên lạc > N ngày" },
  { value: "software_new", label: "Phần mềm lạ" },
  { value: "hardware_changed", label: "Phần cứng thay đổi" },
];

const CHANNELS = ["email", "telegram", "zalo"];

const NOTIF_SEVERITY_OPTIONS = [
  { value: "info", label: "Info" },
  { value: "success", label: "Success" },
  { value: "warning", label: "Warning" },
  { value: "error", label: "Error" },
  { value: "critical", label: "Critical" },
];

const NOTIF_CATEGORY_OPTIONS = [
  { value: "message", label: "Tin nhắn" },
  { value: "investigation", label: "Điều tra" },
  { value: "alert", label: "Cảnh báo" },
  { value: "system", label: "Hệ thống" },
  { value: "machine", label: "Máy" },
  { value: "security", label: "Bảo mật" },
];

const NOTIF_RECIPIENT_OPTIONS = [
  { value: "admins", label: "Tất cả Admin (Super + Org)" },
  { value: "super", label: "Chỉ Super Admin" },
  { value: "org_admins", label: "Admin tổ chức (Org Admin)" },
  { value: "broadcast", label: "Toàn hệ thống (mọi người dùng)" },
];

type HistoryTab = "all" | "read";

export default function NotificationsAlertsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  // ── Alert rules + events state ─────────────────────────────
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [rulesPage, setRulesPage] = useState<PageResponse<AlertRule>>({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  const [eventsPage, setEventsPage] = useState<PageResponse<AlertEvent>>({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rulesOffset, setRulesOffset] = useState(0);
  const [eventsOffset, setEventsOffset] = useState(0);

  // Form tạo rule
  const [name, setName] = useState("");
  const [ruleType, setRuleType] = useState<AlertRuleType>("machine_lost");
  const [orgId, setOrgId] = useState("");
  const [thresholdDays, setThresholdDays] = useState(7);
  const [channels, setChannels] = useState<string[]>(["email"]);
  const [targets, setTargets] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AlertRule | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);

  // ── Notification compose modal state ───────────────────────
  const { notifications, unreadCount, refresh, markAllRead, markRead, deleteOne } = useNotifications();
  const [composeOpen, setComposeOpen] = useState(false);
  const [notifTitle, setNotifTitle] = useState("");
  const [notifSeverity, setNotifSeverity] = useState("info");
  const [notifCategory, setNotifCategory] = useState("message");
  const [notifBody, setNotifBody] = useState("");
  const [notifLink, setNotifLink] = useState("");
  const [notifRecipient, setNotifRecipient] = useState("admins");
  const [sending, setSending] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composeDone, setComposeDone] = useState<string | null>(null);

  // ── History slide-over state ──────────────────────────────
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyTab, setHistoryTab] = useState<HistoryTab>("all");

  const load = useCallback(async (silent = false) => {
    try {
      const [r, e] = await Promise.all([
        api.get<PageResponse<AlertRule>>("/alert-rules", { limit: 50, offset: rulesOffset }),
        api.get<PageResponse<AlertEvent>>("/alert-rules/events", { limit: 50, offset: eventsOffset }),
      ]);
      setRules(r.items);
      setEvents(e.items);
      setRulesPage(r);
      setEventsPage(e);
      setError(null);
    } catch (err) {
      if (!silent) setError(err instanceof Error ? err.message : "Không tải được alert");
    } finally {
      setLoading(false);
    }
  }, [rulesOffset, eventsOffset]);

  useEffect(() => {
    void load();
    api
      .get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
    void refresh();
  }, [load, refresh]);

  const toggleChannel = (c: string) => {
    setChannels((prev) => (prev.includes(c) ? (prev ?? []).filter((x) => x !== c) : [...prev, c]));
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

  const removeRule = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.delete(`/alert-rules/${removing.id}`);
      setRemoving(null);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Xóa thất bại");
    } finally {
      setRemoveBusy(false);
    }
  };

  // ── Notification compose handlers ──────────────────────────
  const openCompose = () => {
    setNotifTitle("");
    setNotifSeverity("info");
    setNotifCategory("message");
    setNotifBody("");
    setNotifLink("");
    setNotifRecipient("admins");
    setComposeError(null);
    setComposeDone(null);
    setComposeOpen(true);
  };

  const sendNotification = async () => {
    if (!notifTitle.trim()) {
      setComposeError("Nhập tiêu đề thông báo");
      return;
    }
    setSending(true);
    setComposeError(null);
    setComposeDone(null);
    try {
      const payload = {
        title: notifTitle.trim(),
        severity: notifSeverity,
        category: notifCategory,
        body: notifBody.trim() || null,
        link: notifLink.trim() || null,
      };
      let res: { delivered_to: number };
      if (notifRecipient === "broadcast") {
        res = await api.post<{ delivered_to: number }>("/admin/notifications/broadcast", payload);
      } else {
        const role =
          notifRecipient === "admins"
            ? "admin"
            : notifRecipient === "super"
            ? "super_admin"
            : "org_admin";
        res = await api.post<{ delivered_to: number }>("/admin/notifications", {
          recipient_filter: { role },
          ...payload,
        });
      }
      setComposeDone(`Đã gửi tới ${res.delivered_to} người nhận.`);
      setNotifTitle("");
      setNotifBody("");
      setNotifLink("");
      setComposeOpen(false);
      void refresh();
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : "Gửi thất bại");
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    if (!composeDone) return;
    const t = setTimeout(() => setComposeDone(null), 6000);
    return () => clearTimeout(t);
  }, [composeDone]);

  // ESC đóng history panel
  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHistoryOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  // ── History list (computed) ───────────────────────────────
  const historyAll = notifications;
  const historyRead = useMemo(() => notifications.filter((n) => !!n.read_at), [notifications]);
  const visibleHistory = historyTab === "read" ? historyRead : historyAll;

  return (
    <div>
      <PageHeader
        title="Thông báo & Cảnh báo"
        description="Quản lý alert rules, lịch sử cảnh báo, và thông báo hệ thống (tính năng #14-15)"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
            </Button>
            <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)}>
              <History className="size-3.5" /> Lịch sử thông báo
              {unreadCount > 0 && (
                <Badge className="ml-1 bg-brand-50 text-brand-700 ring-brand-600/20">
                  {unreadCount} mới
                </Badge>
              )}
            </Button>
            {isSuperAdmin && (
              <Button size="sm" onClick={openCompose}>
                <Plus className="size-3.5" /> Tạo thông báo
              </Button>
            )}
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {composeDone && (
        <div className="mb-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" />
          {composeDone}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Alert rules"
          subtitle="Job quét chạy mỗi phút; mỗi rule + máy + ngày chỉ cảnh báo 1 lần"
          padded={false}
        >
          {loading && (rules?.length ?? 0) === 0 ? (
            <Spinner />
          ) : (rules?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Bell className="size-10" />}
              title="Chưa có rule nào"
              description="Tạo rule đầu tiên ở form bên phải."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {(rules ?? []).map((r) => {
                const meta = ALERT_RULE_TYPE_META[r.rule_type] ?? {
                  label: r.rule_type,
                  badge: "bg-slate-100 text-slate-600 ring-slate-500/20",
                };
                return (
                  <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                    <span
                      className={`flex size-9 items-center justify-center rounded-lg ${
                        r.enabled ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-400"
                      }`}
                    >
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
                          <Badge
                            key={c}
                            className="bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                          >
                            {ALERT_CHANNEL_META[c] ?? c}
                          </Badge>
                        ))}
                        {r.org_id === null && (
                          <Badge className="bg-violet-50 text-violet-700 ring-violet-600/20">
                            Toàn hệ thống
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        role="switch"
                        aria-checked={r.enabled}
                        aria-label={r.enabled ? `Tắt rule ${r.name}` : `Bật rule ${r.name}`}
                        onClick={() => void toggleRule(r)}
                        className={`relative h-6 w-10 cursor-pointer rounded-full transition-colors ${
                          r.enabled ? "bg-emerald-500" : "bg-slate-300"
                        }`}
                        title={r.enabled ? "Tắt rule" : "Bật rule"}
                      >
                        <span
                          className={`absolute top-1 size-4 rounded-full bg-white transition-all ${
                            r.enabled ? "left-5" : "left-1"
                          }`}
                        />
                      </button>
                      <IconButton
                        label={`Xóa rule ${r.name}`}
                        onClick={() => setRemoving(r)}
                        className="hover:bg-rose-50 hover:text-rose-600"
                      >
                        <Trash2 className="size-4" />
                      </IconButton>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <Pagination
            page={rulesPage}
            onChange={(newOffset) => {
              setRulesOffset(newOffset);
              void load(true);
            }}
          />
        </Card>

        <Card title="Tạo rule mới">
          <form onSubmit={create} className="space-y-3">
            <Field label="Tên rule" required>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="VD: Máy mất liên lạc 7 ngày"
                required
              />
            </Field>
            <Field label="Loại cảnh báo" required>
              <Select
                value={ruleType}
                onChange={(e) => setRuleType(e.target.value as AlertRuleType)}
              >
                {RULE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Field>
            {(orgs?.length ?? 0) > 0 && (
              <Field
                label="Phạm vi tổ chức"
                hint="Bỏ trống = toàn hệ thống (Super Admin)"
              >
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
                <Input
                  type="number"
                  min={1}
                  max={365}
                  value={thresholdDays}
                  onChange={(e) => setThresholdDays(Number(e.target.value))}
                />
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
                      className="size-4 rounded border-slate-300 text-blue-600 focus:ring-brand-600"
                    />
                    {ALERT_CHANNEL_META[c]}
                  </label>
                ))}
              </div>
            </Field>
            <Field
              label="Người nhận"
              hint="Email (phân cách bởi dấu phẩy / dòng mới). Telegram/Zalo dùng cấu hình bot ở server (.env)"
            >
              <Input
                value={targets}
                onChange={(e) => setTargets(e.target.value)}
                placeholder="it@example.gov.vn, admin@example.gov.vn"
              />
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
        subtitle={`${events?.length ?? 0} sự kiện gần nhất — gửi thành công qua kênh cấu hình hay chỉ ghi log`}
        padded={false}
      >
        {(events?.length ?? 0) === 0 ? (
          <EmptyState
            icon={<BellRing className="size-10" />}
            title="Chưa có cảnh báo nào"
            description="Cảnh báo sẽ xuất hiện khi rule kích hoạt."
          />
        ) : (
          <div className={TABLE_WRAP}>
            <table className={TABLE}>
              <thead className={THEAD}>
                <tr>
                  <th scope="col" className={TH}>
                    Thời gian
                  </th>
                  <th scope="col" className={TH}>
                    Mức độ
                  </th>
                  <th scope="col" className={TH}>
                    Nội dung
                  </th>
                  <th scope="col" className={TH}>
                    Kênh
                  </th>
                  <th scope="col" className={TH}>
                    Gửi
                  </th>
                </tr>
              </thead>
              <tbody>
                {(events ?? []).map((ev) => {
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
                        {(ev.channels ?? []).map((c) => ALERT_CHANNEL_META[c] ?? c).join(", ") ||
                          "—"}
                      </td>
                      <td className={TD}>
                        <Badge
                          className={
                            ev.delivered
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                              : "bg-slate-100 text-slate-500 ring-slate-500/20"
                          }
                        >
                          {ev.delivered ? "Đã gửi" : "Chưa gửi"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pagination
              page={eventsPage}
              onChange={(newOffset) => {
                setEventsOffset(newOffset);
                void load(true);
              }}
            />
          </div>
        )}
      </Card>

      {/* ── Slide-over: lịch sử thông báo ─────────────────────── */}
      {historyOpen && (
        <div
          className="fixed inset-0 z-40 flex justify-end"
          role="dialog"
          aria-modal="true"
          aria-labelledby="history-title"
        >
          <div
            className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
            onClick={() => setHistoryOpen(false)}
          />
          <div className="relative z-10 flex h-full w-full max-w-md flex-col bg-white shadow-2xl">
            <header className="flex items-center justify-between gap-3 border-b border-slate-100 bg-white/95 px-5 py-4 backdrop-blur">
              <div className="min-w-0">
                <h2 id="history-title" className="text-[15px] font-semibold text-slate-800">
                  Lịch sử thông báo
                </h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Tất cả {historyAll.length} · Đã đọc {historyRead.length} · Chưa đọc {unreadCount}
                </p>
              </div>
              <IconButton
                label="Đóng"
                onClick={() => setHistoryOpen(false)}
                className="hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="size-4" />
              </IconButton>
            </header>

            {/* Tab strip */}
            <div className="flex items-center gap-1 border-b border-slate-100 bg-slate-50/60 px-5 py-2">
              <button
                role="tab"
                aria-selected={historyTab === "all"}
                onClick={() => setHistoryTab("all")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  historyTab === "all"
                    ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200"
                    : "text-slate-600 hover:bg-white/60"
                }`}
              >
                <Bell className="size-3.5" />
                Tất cả
                <span className="text-xs text-slate-400">({historyAll.length})</span>
              </button>
              <button
                role="tab"
                aria-selected={historyTab === "read"}
                onClick={() => setHistoryTab("read")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  historyTab === "read"
                    ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200"
                    : "text-slate-600 hover:bg-white/60"
                }`}
              >
                <Check className="size-3.5" />
                Đã xem
                <span className="text-xs text-slate-400">({historyRead.length})</span>
              </button>

              {historyTab === "all" && unreadCount > 0 && (
                <button
                  onClick={() => void markAllRead()}
                  className="ml-auto text-xs font-medium text-brand-600 hover:underline"
                >
                  Đánh dấu tất cả đã đọc
                </button>
              )}
            </div>

            {/* List */}
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
              {visibleHistory.length === 0 ? (
                <EmptyState
                  icon={<Bell className="size-8" />}
                  title={historyTab === "read" ? "Chưa có thông báo đã đọc" : "Chưa có thông báo"}
                  description={
                    historyTab === "read"
                      ? "Các thông báo bạn đã đọc sẽ xuất hiện ở đây."
                      : "Notification sẽ xuất hiện khi có sự kiện: investigation xong, máy offline, alert security…"
                  }
                />
              ) : (
                <ul className="space-y-2">
                  {visibleHistory.map((n) => (
                    <HistoryRow
                      key={n.id}
                      n={n}
                      onOpen={() => {
                        if (!n.read_at) void markRead(n.id);
                        setHistoryOpen(false);
                        if (n.link) router.push(n.link);
                      }}
                      onDelete={() => void deleteOne(n.id)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: xác nhận xóa rule ──────────────────────────── */}
      <ConfirmDialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title="Xóa alert rule"
        danger
        loading={removeBusy}
        confirmLabel="Xóa rule"
        onConfirm={() => void removeRule()}
        message={
          <>
            Rule <b>{removing?.name}</b> sẽ bị xóa vĩnh viễn — máy mới / mất liên lạc sẽ không còn
            cảnh báo qua rule này.
          </>
        }
      />

      {/* ── Modal: tạo / push notification (giữ nguyên UX cũ) ── */}
      <Modal
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        title="Gửi thông báo tới Admin"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setComposeOpen(false)} disabled={sending}>
              Hủy
            </Button>
            <Button onClick={sendNotification} disabled={sending || !notifTitle.trim()}>
              {sending ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <SendHorizontal className="size-3.5" />
              )}
              Gửi thông báo
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {composeError && <ErrorBanner message={composeError} />}

          <Field
            label="Đối tượng nhận"
            hint="Admin gửi — chọn nhóm người nhận. Người gửi không nhận được thông báo của chính mình."
          >
            <Select value={notifRecipient} onChange={(e) => setNotifRecipient(e.target.value)}>
              {NOTIF_RECIPIENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Tiêu đề" required>
            <Input
              value={notifTitle}
              onChange={(e) => setNotifTitle(e.target.value)}
              placeholder="VD: Bảo trì hệ thống đêm nay 22:00–23:00"
              maxLength={200}
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Mức độ">
              <Select value={notifSeverity} onChange={(e) => setNotifSeverity(e.target.value)}>
                {NOTIF_SEVERITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Loại">
              <Select value={notifCategory} onChange={(e) => setNotifCategory(e.target.value)}>
                {NOTIF_CATEGORY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field
            label="Nội dung"
            hint="Hiển thị trong dropdown chuông thông báo và trang này."
          >
            <textarea
              rows={3}
              value={notifBody}
              onChange={(e) => setNotifBody(e.target.value)}
              placeholder="Chi tiết thông báo…"
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm transition-colors placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30"
            />
          </Field>

          <Field
            label="Link (tùy chọn)"
            hint="VD /machines hoặc /admin/llm-dfir/investigations — bấm thông báo sẽ chuyển tới đó."
          >
            <Input
              value={notifLink}
              onChange={(e) => setNotifLink(e.target.value)}
              placeholder="/dashboard"
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

// ── History slide-over row ──────────────────────────────────
function HistoryRow({
  n,
  onOpen,
  onDelete,
}: {
  n: NotificationOut;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const sev = (n.severity || "info").toLowerCase();
  const unread = !n.read_at;
  return (
    <li
      className={`group rounded-lg border border-slate-200 bg-white p-3 transition-colors hover:border-slate-300 ${
        unread ? "border-l-2 border-l-brand-600 bg-brand-50/30" : ""
      }`}
    >
      <div className="flex items-start gap-2">
        <button onClick={onOpen} className="min-w-0 flex-1 cursor-pointer text-left">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <Badge className={SEVERITY_BADGES[sev] ?? SEVERITY_BADGES.info}>{sev}</Badge>
            <span className="text-[11px] text-slate-500">{n.category}</span>
            {unread && (
              <span
                className="size-1.5 rounded-full bg-brand-600"
                aria-label="Chưa đọc"
              />
            )}
          </div>
          <div
            className={`text-sm ${
              unread ? "font-semibold text-slate-900" : "font-medium text-slate-700"
            }`}
          >
            {n.title}
          </div>
          {n.body && (
            <div className="mt-1 line-clamp-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
              {n.body}
            </div>
          )}
          <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-400">
            <span title={formatDateTime(n.created_at)}>{timeAgo(n.created_at)}</span>
            {n.link && (
              <span className="inline-flex items-center gap-0.5 font-medium text-brand-600">
                <ExternalLink className="size-3" /> có link
              </span>
            )}
          </div>
        </button>
        <IconButton
          label="Xoá thông báo"
          onClick={onDelete}
          className="shrink-0 opacity-60 hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100"
        >
          <Trash2 className="size-3.5" />
        </IconButton>
      </div>
    </li>
  );
}
