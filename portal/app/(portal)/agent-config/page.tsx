"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CheckCircle2, RefreshCw, Save, ServerCog } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-context";
import { Badge, Button, Card, ErrorBanner, Field, Input, PageHeader, Spinner } from "@/components/ui";
import { formatDateTime } from "@/lib/format";

/** Cấu hình agent (Vận hành) — heartbeat, chu kỳ inventory, IP/Domain server đẩy dữ liệu.
 *  Agent tự đồng bộ qua GET /api/agent/config + heartbeat sau khi cài đặt. */
interface AgentSettings {
  heartbeat_interval_seconds: number;
  heartbeat_jitter_seconds: number;
  online_ttl_seconds: number;
  inventory_interval_hours: number;
  renew_before_percent: number;
  agent_server_url: string;
  defaults: Record<string, number | string>;
  overridden: Record<string, boolean>;
  updated_at: string | null;
  updated_by: string | null;
}

const NUM_FIELDS: Array<{ key: keyof AgentSettings & string; label: string; hint?: string; min: number; max: number }> = [
  {
    key: "heartbeat_interval_seconds",
    label: "Chu kỳ heartbeat (giây)",
    hint: "Agent gửi tín hiệu sống định kỳ theo chu kỳ này",
    min: 5,
    max: 3600,
  },
  {
    key: "heartbeat_jitter_seconds",
    label: "Jitter (± giây)",
    hint: "Tránh mọi máy gửi cùng lúc — agent gửi ngẫu nhiên trong [chu kỳ − jitter, chu kỳ + jitter]",
    min: 0,
    max: 600,
  },
  {
    key: "inventory_interval_hours",
    label: "Chu kỳ gửi inventory (giờ)",
    hint: "Agent gửi lại danh sách phần cứng/phần mềm đầy đủ định kỳ",
    min: 1,
    max: 168,
  },
];

export default function AgentConfigPage() {
  const { user } = useAuth();
  const [data, setData] = useState<AgentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  // Form state
  const [hb, setHb] = useState("");
  const [jitter, setJitter] = useState("");
  const [invHours, setInvHours] = useState("");
  const [serverUrl, setServerUrl] = useState("");

  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const load = useCallback(async () => {
    try {
      const s = await api.get<AgentSettings>("/agent-settings");
      setData(s);
      setHb(String(s.overridden.heartbeat_interval_seconds ? s.heartbeat_interval_seconds : ""));
      setJitter(String(s.overridden.heartbeat_jitter_seconds ? s.heartbeat_jitter_seconds : ""));
      setInvHours(String(s.overridden.inventory_interval_hours ? s.inventory_interval_hours : ""));
      setServerUrl(s.agent_server_url);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được cấu hình agent");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSavedMsg(null);
    try {
      await api.put("/agent-settings", {
        heartbeat_interval_seconds: hb === "" ? null : Number(hb),
        heartbeat_jitter_seconds: jitter === "" ? null : Number(jitter),
        inventory_interval_hours: invHours === "" ? null : Number(invHours),
        agent_server_url: serverUrl.trim(),
      });
      setSavedMsg("Đã lưu cấu hình — agent sẽ tự nhận khi heartbeat hoặc gọi /api/agent/config tiếp theo.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lưu cấu hình thất bại");
    }
  };

  if (loading) return <Spinner label="Đang tải cấu hình agent…" />;

  const ovKey = data ? (data.updated_at ? formatDateTime(data.updated_at) : null) : null;

  return (
    <div>
      <PageHeader
        title="Cấu hình Agent"
        description="Tham số agent tải về sau khi cài đặt: tần suất heartbeat, chu kỳ inventory, IP/Domain server đẩy dữ liệu"
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
          </Button>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {!isSuperAdmin && (
        <p className="mb-4 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500 ring-1 ring-inset ring-slate-200">
          Bạn đang ở chế độ chỉ đọc — chỉ Super Admin mới được chỉnh cấu hình.
        </p>
      )}

      <form onSubmit={save} className="grid gap-6 lg:grid-cols-3">
        <Card title="Tham số kết nối & đồng bộ" className="lg:col-span-2">
          <fieldset disabled={!isSuperAdmin} className="space-y-4 disabled:opacity-60">
            <div className="grid gap-4 sm:grid-cols-2">
              {NUM_FIELDS.map((f) => {
                const value = f.key === "heartbeat_interval_seconds" ? hb : f.key === "heartbeat_jitter_seconds" ? jitter : invHours;
                const setter = f.key === "heartbeat_interval_seconds" ? setHb : f.key === "heartbeat_jitter_seconds" ? setJitter : setInvHours;
                const overridden = data?.overridden[f.key as string];
                return (
                  <Field key={f.key} label={f.label} hint={f.hint}>
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        min={f.min}
                        max={f.max}
                        value={value}
                        onChange={(ev) => setter(ev.target.value)}
                        placeholder={`Mặc định: ${String(data?.defaults[f.key as string] ?? "")}`}
                        required
                      />
                      {overridden && <Badge className="bg-violet-50 text-violet-700 ring-violet-600/20">Đổi</Badge>}
                    </div>
                  </Field>
                );
              })}
              <Field
                label="IP / Domain server (agent đẩy dữ liệu về)"
                hint="URL kênh mTLS mà agent dùng để gửi heartbeat + inventory, VD: https://10.10.0.241:8000"
              >
                <Input value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} placeholder="https://agent.example.gov.vn" required />
              </Field>
            </div>

            {isSuperAdmin && (
              <div className="flex items-center gap-3 pt-1">
                <Button type="submit" size="sm">
                  <Save className="size-3.5" /> Lưu cấu hình
                </Button>
                {savedMsg && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700">
                    <CheckCircle2 className="size-4" /> {savedMsg}
                  </span>
                )}
              </div>
            )}
          </fieldset>
        </Card>

        <div className="space-y-6">
          <Card title="Trạng thái hiện tại">
            <dl className="space-y-2.5 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Online TTL</dt>
                <dd className="font-medium text-slate-900">{data?.online_ttl_seconds}s</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Gia hạn cert trước</dt>
                <dd className="font-medium text-slate-900">{data?.renew_before_percent}% vòng đời</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Cập nhật lần cuối</dt>
                <dd className="font-medium text-slate-900">{ovKey ?? "— (mặc định env)"}</dd>
              </div>
            </dl>
          </Card>

          <Card title="Cách agent nhận cấu hình">
            <div className="space-y-2.5 text-sm leading-relaxed text-slate-600">
              <p className="flex items-start gap-2">
                <ServerCog className="mt-0.5 size-4 shrink-0 text-brand-600" />
                Sau khi cài đặt và enroll thành công, agent gọi <code className="rounded bg-slate-100 px-1 font-mono text-xs">GET /api/agent/config</code> để tải tham số.
              </p>
              <p>
                Mỗi lần gửi heartbeat, server trả kèm chu kỳ mới nhất → thay đổi ở đây có hiệu lực trong vòng{" "}
                <b>1 chu kỳ heartbeat</b>, không cần cài lại agent.
              </p>
            </div>
          </Card>
        </div>
      </form>
    </div>
  );
}
