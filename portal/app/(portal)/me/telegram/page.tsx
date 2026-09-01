"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ExternalLink,
  Info,
  KeyRound,
  Loader2,
  PlugZap,
  RefreshCw,
  Save,
  Search as SearchIcon,
  Settings,
  ShieldCheck,
  Trash2,
  Unlink,
  Users,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  ErrorBanner,
  Field,
  Input,
  Spinner,
  Toggle,
} from "@/components/ui";
import type {
  TelegramBotConfigOut,
  TelegramBotConfigTestOut,
  TelegramBotConfigUpdateIn,
  TelegramLinkedUser,
} from "@/lib/types";

/**
 * Cấu hình Telegram bot (Super Admin).
 *
 * Bot token + webhook secret lưu dạng AES-256-GCM trong DB (mask khi trả về).
 * User thường dùng bot này để nhận notification và liên kết tài khoản (modal
 * trong AccountModal — tab "Telegram").
 *
 * Phân biệt:
 *   - DB (`source="db"`): Super Admin đã set trên portal.
 *   - Env (`source="env"`): fallback từ `.env` — production vẫn dùng được nếu
 *     chưa vào portal set.
 *   - None: chưa có gì → báo "Bot chưa được cấu hình".
 */
export default function TelegramBotConfigPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [data, setData] = useState<TelegramBotConfigOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // Form state — track dirty để biết khi nào cần hiển thị nút Save.
  // `null` = không đổi (giữ nguyên giá trị DB/env); `""` = xoá; chuỗi/bool = set.
  const [botToken, setBotToken] = useState<string>("");
  const [botUsername, setBotUsername] = useState<string>("");
  const [webhookSecret, setWebhookSecret] = useState<string>("");
  const [enabled, setEnabled] = useState<boolean>(true);
  const [dirty, setDirty] = useState(false);

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TelegramBotConfigTestOut | null>(null);

  // Linked users panel state
  const [linkedUsers, setLinkedUsers] = useState<TelegramLinkedUser[]>([]);
  const [linkedTotal, setLinkedTotal] = useState(0);
  const [linkedLoading, setLinkedLoading] = useState(false);
  const [linkedQ, setLinkedQ] = useState("");
  const [linkedOffset, setLinkedOffset] = useState(0);
  const [linkedLimit] = useState(20);
  const [unlinking, setUnlinking] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get<TelegramBotConfigOut>("/admin/telegram-bot");
      setData(d);
      setBotUsername(d.bot_username ?? "");
      setEnabled(d.enabled);
      // Không pre-fill token/secret (mask không dùng để gửi lại).
      setBotToken("");
      setWebhookSecret("");
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được cấu hình");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadLinked = useCallback(
    async (q: string, offset: number) => {
      setLinkedLoading(true);
      try {
        const qs = new URLSearchParams({
          limit: String(linkedLimit),
          offset: String(offset),
        });
        if (q.trim()) qs.set("q", q.trim());
        const data = await api.get<{
          items: TelegramLinkedUser[];
          total: number;
        }>(`/admin/telegram-bot/linked-users?${qs.toString()}`);
        setLinkedUsers(data.items);
        setLinkedTotal(data.total);
      } catch (e) {
        // im lặng — panel phụ, không chặn flow chính
        console.warn("linked-users load failed:", e);
      } finally {
        setLinkedLoading(false);
      }
    },
    [linkedLimit],
  );

  useEffect(() => {
    if (isSuperAdmin) void loadLinked(linkedQ, linkedOffset);
  }, [isSuperAdmin, linkedQ, linkedOffset, loadLinked]);

  const forceUnlink = async (u: TelegramLinkedUser) => {
    if (
      !confirm(
        `Bỏ liên kết Telegram của ${u.email}?\nUser sẽ không nhận notification qua Telegram nữa.`,
      )
    ) {
      return;
    }
    setUnlinking(u.id);
    try {
      await api.delete(`/admin/telegram-bot/linked-users/${u.id}`);
      await loadLinked(linkedQ, linkedOffset);
      setInfo(`Đã bỏ liên kết Telegram của ${u.email}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không bỏ liên kết được");
    } finally {
      setUnlinking(null);
    }
  };

  const linkedPageCount = Math.max(1, Math.ceil(linkedTotal / linkedLimit));
  const linkedPage = Math.floor(linkedOffset / linkedLimit) + 1;

  if (!isSuperAdmin) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <Card>
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-5 text-rose-600" />
              <h2 className="text-base font-semibold tracking-tight text-slate-900">
                Không có quyền truy cập
              </h2>
            </div>
            <p className="text-sm text-slate-600">
              Trang này chỉ dành cho Super Admin. Bạn có thể liên kết tài khoản
              Telegram cá nhân trong mục <strong>Tài khoản</strong> ở góc trên
              phải → tab "Telegram".
            </p>
          </div>
        </Card>
      </div>
    );
  }

  if (loading) return <Spinner label="Đang tải cấu hình Telegram..." />;

  const isFromEnv = data?.source === "env";
  const isFromDb = data?.source === "db";

  const save = async () => {
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const payload: TelegramBotConfigUpdateIn = {};
      // bot_token: "" = xoá; chuỗi != rỗng = set; "không đổi" = không gửi field.
      // Dùng model_fields_set tương đương: nếu botToken !== "" thì user đã sửa.
      // Để xoá thì cần 1 toggle riêng (xem UI dưới).
      if (botToken !== "") {
        // botToken khác rỗng → gửi giá trị mới
        (payload as Record<string, unknown>).bot_token = botToken;
      }
      if (botUsername !== (data?.bot_username ?? "")) {
        (payload as Record<string, unknown>).bot_username = botUsername.trim() || null;
      }
      if (webhookSecret !== "") {
        (payload as Record<string, unknown>).webhook_secret = webhookSecret;
      }
      if (enabled !== data?.enabled) {
        (payload as Record<string, unknown>).enabled = enabled;
      }

      const updated = await api.put<TelegramBotConfigOut>(
        "/admin/telegram-bot",
        payload,
      );
      setData(updated);
      setBotToken("");
      setWebhookSecret("");
      setDirty(false);
      setInfo("Đã lưu cấu hình. Tất cả user sẽ dùng bot này để nhận notification.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được cấu hình");
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const r = await api.post<TelegramBotConfigTestOut>(
        "/admin/telegram-bot/test",
        {},
      );
      setTestResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không test được bot");
    } finally {
      setTesting(false);
    }
  };

  const clearToken = async () => {
    if (!confirm("Xoá token bot hiện tại? Sau khi xoá, bot sẽ ngừng gửi notification.")) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.put<TelegramBotConfigOut>(
        "/admin/telegram-bot",
        { bot_token: "" } as unknown as TelegramBotConfigUpdateIn,
      );
      setData(updated);
      setBotToken("");
      setDirty(false);
      setInfo("Đã xoá token bot.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không xoá được token");
    } finally {
      setSaving(false);
    }
  };

  const clearWebhookSecret = async () => {
    if (
      !confirm(
        "Xoá webhook secret? Telegram sẽ không verify được webhook → bot sẽ bỏ qua callback /start.",
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.put<TelegramBotConfigOut>(
        "/admin/telegram-bot",
        { webhook_secret: "" } as unknown as TelegramBotConfigUpdateIn,
      );
      setData(updated);
      setWebhookSecret("");
      setDirty(false);
      setInfo("Đã xoá webhook secret.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không xoá được secret");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="flex items-center gap-3">
        <Settings className="size-7 text-brand-600" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Cấu hình Telegram bot
          </h1>
          <p className="text-sm text-slate-500">
            Thiết lập bot Telegram dùng chung cho toàn hệ thống. User sẽ dùng
            bot này để nhận notification và liên kết tài khoản.
          </p>
        </div>
      </header>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}
      {info && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          <span>{info}</span>
        </div>
      )}

      {/* Status strip */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            {data?.configured ? (
              <span className="flex size-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
                <Bot className="size-5" />
              </span>
            ) : (
              <span className="flex size-9 items-center justify-center rounded-full bg-slate-100 text-slate-400">
                <XCircle className="size-5" />
              </span>
            )}
            <div>
              <p className="text-sm font-semibold tracking-tight text-slate-900">
                {data?.configured ? "Bot đã được cấu hình" : "Bot chưa được cấu hình"}
              </p>
              <p className="text-xs text-slate-500">
                Nguồn:&nbsp;
                <Badge
                  className={
                    isFromDb
                      ? "bg-sky-100 text-sky-700"
                      : isFromEnv
                        ? "bg-amber-100 text-amber-700"
                        : "bg-rose-100 text-rose-700"
                  }
                >
                  {isFromDb ? "Database (portal)" : isFromEnv ? "Biến môi trường (.env)" : "Chưa cấu hình"}
                </Badge>
                {data?.updated_at && (
                  <span className="ml-2 text-slate-400">
                    · cập nhật{" "}
                    {new Date(data.updated_at).toLocaleString("vi-VN")}
                  </span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void test()}
              loading={testing}
              disabled={!data?.bot_token_set}
            >
              {testing ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <PlugZap className="size-3.5" />
              )}
              Test kết nối
            </Button>
          </div>
        </div>
        {testResult && (
          <div
            className={`mt-4 flex items-start gap-2 rounded-md border p-3 text-sm ${
              testResult.ok
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : "border-rose-200 bg-rose-50 text-rose-800"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
            ) : (
              <XCircle className="mt-0.5 size-4 shrink-0" />
            )}
            <div>
              {testResult.ok ? (
                <p>
                  <strong>Kết nối thành công.</strong> Bot{" "}
                  <code className="rounded bg-emerald-100 px-1">
                    @{testResult.bot_username}
                  </code>{" "}
                  (id <code>{testResult.bot_id}</code>) đang live.
                </p>
              ) : (
                <p>{testResult.error ?? "Không rõ lỗi"}</p>
              )}
            </div>
          </div>
        )}
      </Card>

      {/* Form */}
      <Card
        title="Thông tin bot"
        subtitle="Lấy từ @BotFather trên Telegram. Token chỉ hiển thị 1 lần khi tạo."
      >
        <div className="space-y-5">
          <Field
            label="Bot Token"
            hint={
              data?.bot_token_set
                ? "Đã cấu hình. Nhập token mới để thay đổi."
                : "Chưa set. Bot sẽ không gửi được notification."
            }
          >
            <Input
              type="password"
              value={botToken}
              onChange={(e) => {
                setBotToken(e.target.value);
                setDirty(true);
              }}
              placeholder={
                data?.bot_token_set ? "Nhập token mới để thay đổi" : "1234567890:AAEhbp..."
              }
              autoComplete="off"
            />
          </Field>
          {data?.bot_token_set && (
            <div className="-mt-3 flex items-center gap-2 rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <KeyRound className="size-3 shrink-0 text-slate-400" />
              <span>
                Hiện tại:&nbsp;
                <code className="font-mono">
                  {data.bot_token_masked ?? "***"}
                </code>
              </span>
              <button
                type="button"
                onClick={() => void clearToken()}
                disabled={saving}
                className="ml-auto inline-flex items-center gap-1 rounded text-xs text-rose-600 underline-offset-2 hover:underline disabled:opacity-50"
              >
                <Trash2 className="size-3" />
                Xoá
              </button>
            </div>
          )}

          <Field
            label="Bot Username"
            hint="Không bao gồm '@'. Dùng để tạo deep-link https://t.me/<username>."
          >
            <Input
              value={botUsername}
              onChange={(e) => {
                setBotUsername(e.target.value);
                setDirty(true);
              }}
              placeholder="MyInventoryBot"
            />
          </Field>

          <Field
            label="Webhook Secret"
            hint={
              data?.webhook_secret_set
                ? "Đã cấu hình. Nhập secret mới để thay đổi."
                : "Telegram gửi kèm header X-Telegram-Bot-Api-Secret-Token để verify webhook."
            }
          >
            <Input
              type="password"
              value={webhookSecret}
              onChange={(e) => {
                setWebhookSecret(e.target.value);
                setDirty(true);
              }}
              placeholder={
                data?.webhook_secret_set ? "Nhập secret mới" : "Secret từ BotFather / tự sinh"
              }
              autoComplete="off"
            />
          </Field>
          {data?.webhook_secret_set && (
            <div className="-mt-3 flex items-center gap-2 rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <KeyRound className="size-3 shrink-0 text-slate-400" />
              <span>
                Hiện tại:&nbsp;
                <code className="font-mono">
                  {data.webhook_secret_masked ?? "***"}
                </code>
              </span>
              <button
                type="button"
                onClick={() => void clearWebhookSecret()}
                disabled={saving}
                className="ml-auto inline-flex items-center gap-1 rounded text-xs text-rose-600 underline-offset-2 hover:underline disabled:opacity-50"
              >
                <Trash2 className="size-3" />
                Xoá
              </button>
            </div>
          )}

          <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold tracking-tight text-slate-900">
                Bật gửi notification qua Telegram
              </p>
              <p className="text-xs text-slate-500">
                Khi tắt, hệ thống ngừng gửi message qua bot (user đã link vẫn
                nhận notification in-app).
              </p>
            </div>
            <Toggle
              checked={enabled}
              onChange={(v) => {
                setEnabled(v);
                setDirty(true);
              }}
              label="Bật gửi notification"
            />
          </div>

          <div className="flex items-center gap-3 pt-2">
            <Button
              onClick={() => void save()}
              loading={saving}
              disabled={!dirty || saving}
            >
              <Save className="size-4" />
              Lưu cấu hình
            </Button>
            {dirty && (
              <button
                type="button"
                onClick={() => {
                  setBotToken("");
                  setWebhookSecret("");
                  setBotUsername(data?.bot_username ?? "");
                  setEnabled(data?.enabled ?? true);
                  setDirty(false);
                }}
                className="text-sm text-slate-500 underline-offset-2 hover:underline"
              >
                Huỷ thay đổi
              </button>
            )}
          </div>
        </div>
      </Card>

      {/* Linked users panel — Super Admin quản lý user đã liên kết */}
      <Card
        title="Tài khoản đã liên kết"
        subtitle={
          linkedTotal > 0
            ? `${linkedTotal} user đang nhận notification qua Telegram bot`
            : "Chưa có user nào liên kết"
        }
      >
        <div className="space-y-4">
          {/* Search box */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                placeholder="Tìm theo email, họ tên hoặc chat ID…"
                value={linkedQ}
                onChange={(e) => {
                  setLinkedQ(e.target.value);
                  setLinkedOffset(0); // reset về trang 1 khi đổi filter
                }}
                className="h-9 w-full rounded-xs border border-slate-300 bg-white pl-8 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-600/15"
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void loadLinked(linkedQ, linkedOffset)}
              disabled={linkedLoading}
            >
              {linkedLoading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <RefreshCw className="size-3.5" />
              )}
              Tải lại
            </Button>
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-semibold">User</th>
                  <th className="px-3 py-2 font-semibold">Đơn vị</th>
                  <th className="px-3 py-2 font-semibold">Telegram Chat ID</th>
                  <th className="px-3 py-2 font-semibold">Liên kết</th>
                  <th className="px-3 py-2 font-semibold">Trạng thái</th>
                  <th className="px-3 py-2 font-semibold text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {linkedLoading && linkedUsers.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                      <Loader2 className="mx-auto size-5 animate-spin" />
                    </td>
                  </tr>
                )}
                {!linkedLoading && linkedUsers.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                      <Users className="mx-auto mb-1 size-5 text-slate-300" />
                      {linkedQ
                        ? `Không tìm thấy user khớp "${linkedQ}".`
                        : "Chưa có user nào liên kết Telegram."}
                    </td>
                  </tr>
                )}
                {linkedUsers.map((u) => (
                  <tr key={u.id} className="text-slate-700">
                    <td className="px-3 py-2">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium text-slate-900">
                          {u.full_name}
                        </span>
                        <span className="text-xs text-slate-500">{u.email}</span>
                        <span className="text-[10px] uppercase tracking-wider text-slate-400">
                          {u.role}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-slate-600">
                        {u.org_name ?? <span className="text-slate-400">—</span>}
                      </td>
                    <td className="px-3 py-2">
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-800">
                        {u.telegram_chat_id}
                      </code>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                        {u.telegram_linked_at
                          ? new Date(u.telegram_linked_at).toLocaleString("vi-VN")
                          : "—"}
                      </td>
                    <td className="px-3 py-2">
                      <Badge
                        className={
                          u.is_active
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-slate-200 text-slate-600"
                        }
                      >
                        {u.is_active ? "Active" : "Đã khoá"}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void forceUnlink(u)}
                        loading={unlinking === u.id}
                        title="Bỏ liên kết Telegram của user này"
                      >
                        <Unlink className="size-3.5 text-rose-600" />
                        Bỏ liên kết
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {linkedTotal > linkedLimit && (
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>
                Trang {linkedPage}/{linkedPageCount} · {linkedTotal} user
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={linkedPage === 1 || linkedLoading}
                  onClick={() =>
                    setLinkedOffset(Math.max(0, linkedOffset - linkedLimit))
                  }
                >
                  Trước
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={linkedPage === linkedPageCount || linkedLoading}
                  onClick={() => setLinkedOffset(linkedOffset + linkedLimit)}
                >
                  Sau
                </Button>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* URL callback + curl snippets */}
      <Card
        title="URL callback & lệnh thiết lập"
        subtitle="Submit URL này cho @BotFather (hoặc chạy lệnh curl) để Telegram biết gửi update về đâu."
      >
        <div className="space-y-5">
          <div>
            <p className="mb-1.5 text-[13px] font-medium text-slate-700">
              Callback URL
            </p>
            <div className="flex items-stretch gap-2">
              <code className="flex-1 break-all rounded-xs border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-900">
                {data?.callback_url ?? "—"}
              </code>
              <CopyButton text={data?.callback_url ?? ""} label="Copy URL" />
            </div>
            <p className="mt-1 text-xs leading-snug text-slate-500">
              URL dựa trên <code>agent_server_url</code> (cùng URL public backend
              dùng cho agent). Nếu sai, chỉnh trong{" "}
              <code>Cấu hình Agent</code>.
            </p>
          </div>

          {data?.webhook_set_command && (
            <div>
              <p className="mb-1.5 text-[13px] font-medium text-slate-700">
                Set webhook (curl)
              </p>
              <div className="relative">
                <pre className="overflow-x-auto rounded-xs border border-slate-300 bg-slate-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-emerald-100">
                  {data.webhook_set_command}
                </pre>
                <div className="absolute right-2 top-2">
                  <CopyButton
                    text={data.webhook_set_command}
                    label="Copy"
                  />
                </div>
              </div>
              <p className="mt-1 text-xs leading-snug text-slate-500">
                Chạy lệnh này trên <strong>server có HTTPS public</strong>{" "}
                (vd VPS, máy có domain + Let's Encrypt) — Telegram chỉ chấp
                nhận webhook qua HTTPS. Lệnh sẽ tự động kèm{" "}
                <code>secret_token</code> nếu đã set trong form.
              </p>
            </div>
          )}

          {data?.webhook_check_command && (
            <div>
              <p className="mb-1.5 text-[13px] font-medium text-slate-700">
                Kiểm tra trạng thái webhook
              </p>
              <div className="relative">
                <pre className="overflow-x-auto rounded-xs border border-slate-300 bg-slate-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-emerald-100">
                  {data.webhook_check_command}
                </pre>
                <div className="absolute right-2 top-2">
                  <CopyButton
                    text={data.webhook_check_command}
                    label="Copy"
                  />
                </div>
              </div>
            </div>
          )}

          {!data?.bot_token_set && (
            <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <p>
                Chưa có <strong>bot token</strong> — set trước rồi các lệnh curl
                mới có nội dung.
              </p>
            </div>
          )}
        </div>
      </Card>

      {/* Hướng dẫn */}
      <Card title="Hướng dẫn cấu hình">
        <ol className="list-decimal space-y-3 pl-5 text-sm text-slate-700">
          <li>
            Mở Telegram, tìm <strong>@BotFather</strong>, gõ{" "}
            <code className="rounded bg-slate-100 px-1">/newbot</code> và làm
            theo hướng dẫn để tạo bot. Lưu <strong>token</strong> BotFather trả
            về.
          </li>
          <li>
            Set webhook cho bot trỏ về <strong>URL callback</strong> ở trên (có 2
            cách):
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">
              <li>
                Qua BotFather: <code>/setwebhook</code> → paste URL → nhập{" "}
                <strong>webhook secret</strong> đã set ở form.
              </li>
              <li>
                Hoặc chạy lệnh <code>curl</code> ở mục "Set webhook" (chỉ chạy
                được từ server có HTTPS public).
              </li>
            </ul>
          </li>
          <li>
            Dán <strong>token</strong>, <strong>username</strong> và{" "}
            <strong>webhook secret</strong> vào form trên, bấm{" "}
            <strong>Lưu cấu hình</strong>.
          </li>
          <li>
            Bấm <strong>Test kết nối</strong> để xác nhận bot đang live.
          </li>
          <li>
            User trong hệ thống sẽ vào <strong>Tài khoản → Telegram</strong>{" "}
            (góc trên phải) để liên kết tài khoản website với Telegram cá nhân.
          </li>
        </ol>
      </Card>

      {isFromEnv && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div>
            <p className="font-semibold">Đang dùng fallback từ biến môi trường.</p>
            <p className="mt-1 text-xs">
              Các biến <code>TELEGRAM_BOT_TOKEN</code>,{" "}
              <code>TELEGRAM_BOT_USERNAME</code>,{" "}
              <code>TELEGRAM_WEBHOOK_SECRET</code> trong <code>.env</code> đang
              được dùng. Lưu qua portal sẽ ưu tiên giá trị DB kể từ lần đọc
              sau.
            </p>
          </div>
        </div>
      )}

      <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <Info className="mt-0.5 size-3.5 shrink-0 text-slate-400" />
        <p>
          Token + webhook secret được mã hoá AES-256-GCM trước khi lưu DB; giao
          diện chỉ hiển thị mask. Không có cách nào xem lại plaintext sau khi
          lưu — nếu mất, tạo token mới qua @BotFather.
        </p>
      </div>
    </div>
  );
}