"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, CheckCircle2, Loader2, PlugZap, Save, ServerCog, ShieldCheck, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  Select,
  Spinner,
  Textarea,
  Toggle,
} from "@/components/ui";
import type { DeepAgentTestResult, LlmConfig, LlmConfigUpdate, LlmTestResult } from "@/lib/types";
import { formatDateTime } from "@/lib/format";

/** Cấu hình LLM (Super Admin) — Ollama local / OpenAI / Qwen / vLLM.
 *  Style theo Design.md: card surface trắng + hairline, toggle = primary blue,
 *  trạng thái OK/WARN/BAD bằng pill tinted (emerald/amber/rose). */
export default function LlmSettingsPage() {
  const [data, setData] = useState<LlmConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  // Form state
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState("ollama");
  const [modelTouched, setModelTouched] = useState(false);
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:11434/v1");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("qwen2.5:14b-instruct-q4_K_M");
  const [fallbackModel, setFallbackModel] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [maxTokens, setMaxTokens] = useState(4096);
  const [temperature, setTemperature] = useState(0.0);
  const [requestTimeout, setRequestTimeout] = useState(120);
  const [maxContextChars, setMaxContextChars] = useState(200000);
  const [allowCloud, setAllowCloud] = useState(false);
  const [dailyTokenBudget, setDailyTokenBudget] = useState<number | "">("");
  const [deepAgentEnabled, setDeepAgentEnabled] = useState(false);
  const [deepAgentUrl, setDeepAgentUrl] = useState("");
  const [deepAgentToken, setDeepAgentToken] = useState("");

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [deepAgentTest, setDeepAgentTest] = useState<DeepAgentTestResult | null>(null);
  const [testingDeepAgent, setTestingDeepAgent] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await api.get<LlmConfig>("/admin/llm-dfir/config");
      setData(s);
      setEnabled(s.enabled);
      setProvider(s.provider);
      setBaseUrl(s.base_url);
      setModel(s.model);
      setFallbackModel(s.fallback_model ?? "");
      setSystemPrompt(s.system_prompt ?? "");
      setMaxTokens(s.max_tokens);
      setTemperature(s.temperature);
      setRequestTimeout(s.request_timeout);
      setMaxContextChars(s.max_context_chars);
      setAllowCloud(s.allow_cloud);
      setDailyTokenBudget(s.daily_token_budget ?? "");
      setDeepAgentEnabled(s.deepagent_enabled);
      setDeepAgentUrl(s.deepagent_url ?? "");
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
      const body: LlmConfigUpdate = {
        enabled,
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
        fallback_model: fallbackModel.trim() || null,
        system_prompt: systemPrompt.trim() || null,
        max_tokens: maxTokens,
        temperature,
        request_timeout: requestTimeout,
        max_context_chars: maxContextChars,
        allow_cloud: allowCloud,
        daily_token_budget: dailyTokenBudget === "" ? null : Number(dailyTokenBudget),
        external_orchestrator: deepAgentEnabled ? "deepagent" : "",
        deepagent_enabled: deepAgentEnabled,
        deepagent_url: deepAgentUrl.trim() || null,
      };
      // Chỉ gửi api_key nếu user nhập mới
      if (apiKey) body.api_key = apiKey;
      if (deepAgentToken) body.deepagent_service_token = deepAgentToken;
      const updated = await api.put<LlmConfig>("/admin/llm-dfir/config", body);
      setData(updated);
      setSavedMsg("Đã lưu cấu hình LLM.");
      setApiKey("");
      setDeepAgentToken("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const testDeepAgent = async () => {
    setTestingDeepAgent(true);
    setDeepAgentTest(null);
    try {
      setDeepAgentTest(await api.post<DeepAgentTestResult>("/admin/llm-dfir/deepagent/test"));
    } catch (e) {
      setDeepAgentTest({ ok: false, service_ok: false, mcp_ok: false, tools: [], client_count_sampled: null, error: e instanceof Error ? e.message : "Test thất bại" });
    } finally {
      setTestingDeepAgent(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setError(null);
    try {
      const res = await api.post<LlmTestResult>("/admin/llm-dfir/config/test");
      setTestResult(res);
      await load(); // refresh test_status
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test thất bại");
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <Spinner label="Đang tải cấu hình..." />;
  if (error && !data) return <ErrorBanner message={error} onRetry={load} />;

  const testBadge =
    data?.test_status === "ok"
      ? "bg-emerald-100 text-emerald-700 ring-emerald-600/20"
      : data?.test_status === "error"
        ? "bg-rose-100 text-rose-700 ring-rose-600/20"
        : "bg-slate-100 text-slate-700 ring-slate-600/20";

  return (
    <div className="max-w-4xl space-y-6">
      {error && <ErrorBanner message={error} />}
      {savedMsg && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
          {savedMsg}
        </div>
      )}

      {/* Trạng thái */}
      <Card title="Trạng thái">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <Toggle
              checked={enabled}
              onChange={setEnabled}
              label={enabled ? "Tắt LLM" : "Bật LLM"}
            />
            <span className="text-sm font-medium text-slate-700">
              {enabled ? "Đã bật" : "Đã tắt"}
            </span>
            <Activity className="size-4 text-slate-300" aria-hidden />
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <Badge className={testBadge}>
              {data?.test_status === "ok" ? (
                <CheckCircle2 className="size-3" />
              ) : data?.test_status === "error" ? (
                <XCircle className="size-3" />
              ) : (
                <Activity className="size-3" />
              )}
              {data?.test_status ?? "chưa test"}
            </Badge>
            {data?.test_at && (
              <span className="text-xs text-slate-400">lúc {formatDateTime(data.test_at)}</span>
            )}
            {data?.test_error && (
              <span className="text-xs text-rose-600">— {data.test_error}</span>
            )}
          </div>
          <div className="text-sm text-slate-500">
            Tokens dùng hôm nay:{" "}
            <strong className="font-semibold text-slate-900">{data?.tokens_used_today ?? 0}</strong>
            {data?.daily_token_budget ? ` / ${data.daily_token_budget}` : ""}
          </div>
        </div>
      </Card>

      {/* Backend */}
      <Card title="Backend">
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Provider">
              <Select
                value={provider}
                onChange={(e) => {
                  const v = e.target.value;
                  setProvider(v);
                  // Auto-suggest model mặc định theo provider (trừ khi user đã tự sửa)
                  if (!modelTouched) {
                    if (v === "ollama") setModel("qwen2.5:14b-instruct-q4_K_M");
                    else if (v === "openai") setModel("gpt-4o-mini");
                    else if (v === "qwen") setModel("qwen-plus");
                    else if (v === "deepseek") setModel("deepseek-chat");
                  }
                }}
              >
                <option value="ollama">Ollama (local, privacy-first)</option>
                <option value="localai">LocalAI</option>
                <option value="vllm">vLLM (high-perf server)</option>
                <option value="openai">OpenAI</option>
                <option value="qwen">Qwen / DashScope</option>
                <option value="deepseek">DeepSeek</option>
                <option value="custom">Custom OpenAI-compatible</option>
              </Select>
            </Field>
            <Field label="Base URL">
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://127.0.0.1:11434/v1"
              />
            </Field>
          </div>
          <Field label="API Key">
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={data?.api_key_masked ?? "(chưa đặt)"}
            />
            <p className="mt-1 text-xs text-slate-400">
              Hiện tại:{" "}
              <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                {data?.api_key_masked}
              </code>
              {" — "}để trống nếu muốn giữ nguyên
            </p>
          </Field>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Model chính">
              <Input
                list="llm-models"
                value={model}
                onChange={(e) => {
                  setModel(e.target.value);
                  setModelTouched(true);
                }}
                placeholder="qwen2.5:14b-instruct-q4_K_M"
              />
              <datalist id="llm-models">
                {(data?.available_models ?? []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </Field>
            <Field label="Model dự phòng (tuỳ chọn)">
              <Input
                list="llm-models"
                value={fallbackModel}
                onChange={(e) => setFallbackModel(e.target.value)}
                placeholder="qwen2.5:7b-instruct-q4_K_M"
              />
            </Field>
          </div>
        </div>
      </Card>

      {/* Tham số */}
      <Card title="Tham số">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Field label="Max Tokens">
              <Input
                type="number"
                min={64}
                max={32000}
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value) || 4096)}
              />
            </Field>
            <Field label="Temperature">
              <Input
                type="number"
                step="0.1"
                min={0}
                max={2}
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value) || 0)}
              />
            </Field>
            <Field label="Timeout (giây)">
              <Input
                type="number"
                min={10}
                max={600}
                value={requestTimeout}
                onChange={(e) => setRequestTimeout(parseInt(e.target.value) || 120)}
              />
            </Field>
            <Field label="Daily Token Budget">
              <Input
                type="number"
                min={0}
                value={dailyTokenBudget}
                onChange={(e) =>
                  setDailyTokenBudget(e.target.value === "" ? "" : parseInt(e.target.value))
                }
                placeholder="Không giới hạn"
              />
            </Field>
          </div>
          <Field label="Max Context (ký tự)">
            <Input
              type="number"
              min={1000}
              max={1_000_000}
              value={maxContextChars}
              onChange={(e) => setMaxContextChars(parseInt(e.target.value) || 200000)}
            />
            <p className="mt-1 text-xs text-slate-400">
              Log Velociraptor được cắt còn tối đa số ký tự này trước khi gửi LLM
              (tránh OOM local LLM).
            </p>
          </Field>
          <div className="flex items-center gap-3">
            <Toggle
              checked={allowCloud}
              onChange={setAllowCloud}
              label="Cho phép gọi cloud API"
            />
            <span className="text-sm text-slate-600">
              Cho phép gọi cloud API (OpenAI/Qwen) — cần bật để đặt API key cho endpoint public
            </span>
          </div>
        </div>
      </Card>

      <Card title="DeepAgent & MCP Velociraptor">
        <div className="space-y-4">
          <div className="rounded-lg bg-violet-50 p-4 ring-1 ring-inset ring-violet-200">
            <div className="flex items-start gap-3">
              <ServerCog className="mt-0.5 size-5 text-violet-700" />
              <div className="text-sm text-violet-950">
                <p className="font-semibold">LangGraph điều phối DFIR read-only</p>
                <p className="mt-1 text-violet-800">DeepAgent chạy riêng; lệnh MCP nằm tại máy DeepAgent. File api_client.yaml được quản lý ở trang cấu hình Velociraptor, không hiển thị tại đây.</p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Toggle checked={deepAgentEnabled} onChange={setDeepAgentEnabled} label="Bật DeepAgent" />
            <span className="text-sm text-slate-600">Khi bật, investigation mới dùng orchestrator DeepAgent/LangGraph.</span>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="DeepAgent URL" hint="Ví dụ http://10.10.0.242:8090">
              <Input value={deepAgentUrl} onChange={(e) => setDeepAgentUrl(e.target.value)} placeholder="http://10.10.0.242:8090" />
            </Field>
            <Field label="DeepAgent service token" hint={data?.deepagent_service_token_set ? "Đã lưu — để trống nếu giữ nguyên" : "Token xác thực backend → DeepAgent"}>
              <Input type="password" value={deepAgentToken} onChange={(e) => setDeepAgentToken(e.target.value)} placeholder={data?.deepagent_service_token_set ? "(giữ nguyên)" : "Nhập service token"} />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" onClick={testDeepAgent} disabled={testingDeepAgent}>
              {testingDeepAgent ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
              Test DeepAgent → MCP → Velociraptor
            </Button>
            {deepAgentTest && <span className={deepAgentTest.ok ? "text-sm font-medium text-emerald-700" : "text-sm font-medium text-rose-700"}>{deepAgentTest.ok ? `MCP sẵn sàng · ${deepAgentTest.tools.length} tools · ${deepAgentTest.client_count_sampled ?? 0} client mẫu` : deepAgentTest.error}</span>}
          </div>
        </div>
      </Card>

      {/* Agent profile */}
      <Card title="System Prompt của LangGraph">
        <div className="space-y-2">
          <p className="text-xs text-slate-400">
            Đây là cấu hình chung cho DeepAgent, áp dụng cho mọi cuộc điều tra mới. Policy DFIR và allowlist của hệ thống luôn được giữ nguyên.
          </p>
          <Textarea
            rows={8}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Ưu tiên đánh giá hành vi PowerShell, persistence và kết nối C2; trình bày kết luận ngắn gọn cho quản trị viên."
          />
        </div>
      </Card>

      {/* Test result */}
      {testResult && (
        <Card title="Kết quả test">
          <div className="space-y-2">
            <div className="text-sm text-slate-600">
              Latency: <strong className="font-semibold text-slate-900">{testResult.latency_ms}ms</strong>
              {" — "}
              {testResult.models.length} model khả dụng
            </div>
            {testResult.models.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {testResult.models.slice(0, 10).map((m) => (
                  <Badge key={m} className="bg-slate-100 text-slate-700 ring-slate-600/20">
                    {m}
                  </Badge>
                ))}
                {testResult.models.length > 10 && (
                  <Badge className="bg-slate-100 text-slate-700 ring-slate-600/20">
                    +{testResult.models.length - 10} nữa
                  </Badge>
                )}
              </div>
            )}
            {testResult.ok ? (
              <p className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
                <CheckCircle2 className="size-4" /> Kết nối thành công
              </p>
            ) : (
              <p className="flex items-center gap-1.5 text-sm font-medium text-rose-700">
                <XCircle className="size-4" /> Lỗi: {testResult.error}
              </p>
            )}
          </div>
        </Card>
      )}

      <div className="flex gap-3">
        <Button onClick={save} disabled={saving}>
          {saving && <Loader2 className="size-4 animate-spin" />}
          <Save className="size-4" />
          Lưu cấu hình
        </Button>
        <Button onClick={testConnection} disabled={testing} variant="outline">
          {testing && <Loader2 className="size-4 animate-spin" />}
          <PlugZap className="size-4" />
          Test connection
        </Button>
      </div>
    </div>
  );
}
