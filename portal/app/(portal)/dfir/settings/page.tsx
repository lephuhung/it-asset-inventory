"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, AlertTriangle, CheckCircle2, KeyRound, Loader2, PlugZap, Save, ShieldAlert, Trash2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Spinner,
} from "@/components/ui";
import type { VelociraptorConfig, VelociraptorTestResult } from "@/lib/types";
import { formatDateTime, timeAgo } from "@/lib/format";

/** Cài đặt Velociraptor Server (Super Admin).
 *
 *  - URL + API token (mã hoá AES-256-GCM phía server).
 *  - Allowlist artifact (chống lạm quyền — chỉ artifact này mới chạy được).
 *  - Test kết nối (không lưu DB) + nút Sync thủ công.
 */
export default function VelociraptorSettingsPage() {
  const router = useRouter();
  const [data, setData] = useState<VelociraptorConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const [enabled, setEnabled] = useState(false);
  const [serverUrl, setServerUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [allowlistText, setAllowlistText] = useState("");
  const [saving, setSaving] = useState(false);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<VelociraptorTestResult | null>(null);
  // Xác nhận xóa token đã lưu (thay window.confirm — native confirm là anti-pattern)
  const [confirmingClear, setConfirmingClear] = useState(false);
  // True sau khi user bấm "Lưu" thành công — Test button được enable.
  // Trước khi save, credentials chưa vào DB → Test sẽ trả "Chưa cấu hình".
  const [hasSaved, setHasSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await api.get<VelociraptorConfig>("/admin/velociraptor/config");
      setData(s);
      setEnabled(s.enabled);
      setServerUrl(s.server_url ?? s.defaults_server_url ?? "");
      setAllowlistText((s.allowlist ?? []).join("\n"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được cấu hình");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setSavedMsg(null);
    setError(null);
    try {
      const allowlist = allowlistText
        .split(/[\n,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const body: Record<string, unknown> = {
        enabled,
        server_url: serverUrl.trim(),
        allowlist,
      };
      // Token: chỉ gửi nếu user thực sự nhập (tránh overwrite giá trị đã set)
      if (username.trim() || password.trim()) {
        body.username = username.trim() || null;
        body.password = password.trim() || null;
      }
      await api.put("/admin/velociraptor/config", body);
      setSavedMsg("Đã lưu cấu hình Velociraptor.");
      setUsername("");
      setPassword("");
      setHasSaved(true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const clearToken = async () => {
    setSaving(true);
    try {
      await api.put("/admin/velociraptor/config", { username: "", password: "" });
      await load();
      setSavedMsg("Đã xóa API token.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xóa thất bại");
    } finally {
      setSaving(false);
      setConfirmingClear(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.post<VelociraptorTestResult>("/admin/velociraptor/test");
      setTestResult(r);
    } catch (e) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : "Test thất bại", client_count_sampled: null, server_url: serverUrl });
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <Spinner label="Đang tải cấu hình Velociraptor…" />;

  const syncStatus = data?.last_sync_error ? "error" : data?.last_sync_at ? "ok" : "pending";
  const allowlistCount = allowlistText.split("\n").filter((l) => l.trim()).length;

  // Test button chỉ enable khi:
  //   1. enabled = true
  //   2. server_url điền
  //   3. Có credentials — HOẶC đã lưu từ trước (data.basic_auth_set / client_config_set),
  //      HOẶC đang nhập mới (username + password). Nếu không có → Test sẽ fail với
  //      "Chưa cấu hình" vì server đọc credentials từ DB, không từ form state.
  const hasFreshCreds = username.trim() !== "" && password.trim() !== "";
  const hasSavedCreds = data?.basic_auth_set || data?.client_config_set;
  const hasAnyCreds = hasFreshCreds || hasSavedCreds;
  const canTest =
    hasSaved && enabled && serverUrl.trim() !== "" && hasAnyCreds;
  const testHint = !hasSaved
    ? "Bấm 'Lưu cấu hình' trước khi Test — credentials chỉ áp dụng sau khi lưu."
    : !enabled
      ? "Bật Velociraptor trước khi Test."
      : serverUrl.trim() === ""
        ? "Nhập Server URL trước khi Test."
        : !hasAnyCreds
          ? "Nhập Username + Password (hoặc paste YAML Client Config) trước khi Test."
          : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cài đặt Velociraptor (DFIR)"
        description="Tích hợp Velociraptor Server (https://github.com/velocidex/velociraptor) cho phép admin chạy hunt / collect artifact từ xa."
        actions={
          <Button variant="secondary" size="sm" onClick={() => router.push("/dfir")}>
            ← Quay lại DFIR dashboard
          </Button>
        }
      />

      {error && <ErrorBanner message={error} />}

      {savedMsg && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
          {savedMsg}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Form */}
        <Card title="Kết nối & Allowlist" className="lg:col-span-2">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-4 py-3 ring-1 ring-inset ring-slate-200">
              <div>
                <p className="text-sm font-medium text-slate-900">Bật Velociraptor</p>
                <p className="text-xs text-slate-500">
                  Khi bật: background sync hostname ↔ client_id mỗi 5 phút + admin có thể chạy hunt/collect.
                </p>
              </div>
              <label className="inline-flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="size-5 cursor-pointer accent-brand-600"
                />
                <span className="text-sm font-medium text-slate-700">{enabled ? "Enabled" : "Disabled"}</span>
              </label>
            </div>

            <Field
              label="Velociraptor Server URL"
              hint="URL giao diện GUI/API của Velociraptor (vd https://veloci.example.gov.vn:8889). Click 'Test' để kiểm tra sau khi nhập."
            >
              <Input
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                placeholder="https://velociraptor.example.gov.vn:8889"
              />
            </Field>

            {/* API Token — không dùng Field vì label có icon + badge (Field chỉ nhận string) */}
            <div className="block">
              <div className="mb-1.5 flex items-center gap-2 text-[13px] font-medium text-slate-700">
                <KeyRound className="size-3.5 text-slate-500" />
                <span>Username + Password (HTTP Basic)</span>
                {data?.basic_auth_set && (
                  <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">
                    <CheckCircle2 className="mr-1 size-3" /> Đã cấu hình
                  </Badge>
                )}
              </div>
              <div className="flex gap-2">
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin"
                  autoComplete="off"
                />
                <Input
                  type={showToken ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={data?.basic_auth_set ? "(giữ nguyên)" : "Password"}
                  autoComplete="off"
                  className="font-mono text-xs"
                />
                <Button variant="secondary" size="sm" onClick={() => setShowToken((v) => !v)}>
                  {showToken ? "Ẩn" : "Hiện"}
                </Button>
                {data?.basic_auth_set && (
                  <Button variant="secondary" size="sm" onClick={() => setConfirmingClear(true)} disabled={saving}>
                    <Trash2 className="size-3.5 text-rose-600" /> Xóa
                  </Button>
                )}
              </div>
              <p className="mt-1 text-xs leading-snug text-slate-400">
                {data?.basic_auth_set
                  ? "Username + password hiện tại được mã hoá AES-256-GCM. Để trống cả 2 ô nếu KHÔNG muốn đổi; nhập giá trị mới để thay thế."
                  : "Dùng tài khoản Velociraptor admin (mặc định user 'admin' tạo qua VELOCIRAPTOR_INITIAL_ADMIN_PASSWORD lúc khởi động container)."}
              </p>
            </div>

            {/* Allowlist — dùng div thay Field để label có số count động */}
            <div className="block">
              <div className="mb-1.5 flex items-center gap-2 text-[13px] font-medium text-slate-700">
                <span>Allowlist artifact</span>
                <span className="text-xs font-normal text-slate-500">({allowlistCount} artifact)</span>
              </div>
              <textarea
                value={allowlistText}
                onChange={(e) => setAllowlistText(e.target.value)}
                rows={10}
                className="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                placeholder={"Generic.Client.Info\nWindows.System.Services\nWindows.Network.Netstat"}
              />
              <p className="mt-1 text-xs leading-snug text-slate-400">
                Chỉ những artifact trong danh sách này admin mới được phép chạy. Mỗi dòng 1 artifact (Velociraptor artifact name).
              </p>
              <button
                type="button"
                onClick={() => setAllowlistText(data?.defaults_allowlist.join("\n") ?? "")}
                className="mt-1.5 text-[11px] font-medium text-brand-600 hover:underline"
              >
                Khôi phục danh sách mặc định (env)
              </button>
            </div>

            <div className="flex flex-col gap-2 pt-1">
              <div className="flex items-center gap-3">
                <Button onClick={save} size="sm" disabled={saving}>
                  {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                  Lưu cấu hình
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={testConnection}
                  disabled={testing || !canTest}
                  title={testHint ?? undefined}
                >
                  {testing ? <Loader2 className="size-3.5 animate-spin" /> : <PlugZap className="size-3.5" />}
                  Test kết nối
                </Button>
              </div>
              {testHint && (
                <p className="flex items-center gap-1.5 text-[11px] leading-snug text-slate-500">
                  <AlertTriangle className="size-3 shrink-0 text-amber-500" />
                  {testHint}
                </p>
              )}
              {testResult && (
                <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${testResult.ok ? "text-emerald-700" : "text-rose-700"}`}>
                  {testResult.ok ? (
                    <>
                      <CheckCircle2 className="size-4" />
                      Kết nối thành công ({testResult.client_count_sampled ?? 0} client mẫu)
                    </>
                  ) : (
                    <>
                      <XCircle className="size-4" />
                      {testResult.error ?? "Thất bại"}
                    </>
                  )}
                </span>
              )}
            </div>
          </div>
        </Card>

        {/* Trạng thái + hướng dẫn */}
        <div className="space-y-6">
          <Card title="Trạng thái sync">
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Lần sync cuối</span>
                {data?.last_sync_at ? (
                  <span className="font-medium text-slate-900">{timeAgo(data.last_sync_at)}</span>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </div>
              {data?.last_sync_at && (
                <div className="text-[11px] text-slate-400">{formatDateTime(data.last_sync_at)}</div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Trạng thái</span>
                {syncStatus === "ok" ? (
                  <Badge className="bg-emerald-100 text-emerald-700 ring-emerald-600/20">
                    <Activity className="mr-1 size-3" /> OK
                  </Badge>
                ) : syncStatus === "error" ? (
                  <Badge className="bg-rose-100 text-rose-700 ring-rose-600/20">
                    <AlertTriangle className="mr-1 size-3" /> Lỗi
                  </Badge>
                ) : (
                  <Badge className="bg-slate-100 text-slate-700 ring-slate-600/20">Chưa sync</Badge>
                )}
              </div>
              {data?.last_sync_linked != null && data?.last_sync_total != null && (
                <div className="text-xs text-slate-500">
                  Match: <strong>{data.last_sync_linked}/{data.last_sync_total}</strong> client
                </div>
              )}
              {data?.last_sync_error && (
                <div className="rounded-md bg-rose-50 p-2 text-[11px] text-rose-700 ring-1 ring-inset ring-rose-200">
                  {data.last_sync_error}
                </div>
              )}
            </div>
          </Card>

          <Card title="Cách hoạt động">
            <div className="space-y-2.5 text-sm leading-relaxed text-slate-600">
              <p>
                <ShieldAlert className="mr-1 inline size-3.5 align-text-top text-amber-500" />
                Cho phép admin thu thập bằng chứng số từ xa <strong>chỉ với những artifact đã được phê duyệt</strong> trong allowlist.
              </p>
              <p>
                Sync hostname ↔ client_id chạy tự động mỗi 5 phút — <strong>không phụ thuộc agent inventory</strong>.
                Một máy Windows sau khi cài Velociraptor Client sẽ tự động xuất hiện ở <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">/dfir</code>.
              </p>
              <p>
                Kết quả hunt/collect lưu trên Velociraptor Server (notebook / collected flows) — portal deep-link sang GUI, không cache payload.
              </p>
            </div>
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={confirmingClear}
        onClose={() => setConfirmingClear(false)}
        title="Xóa API token đã lưu"
        danger
        loading={saving}
        confirmLabel="Xóa token"
        onConfirm={() => void clearToken()}
        message="Backend sẽ ngừng sync và không cho phép chạy hunt cho tới khi nhập token mới."
      />
    </div>
  );
}
