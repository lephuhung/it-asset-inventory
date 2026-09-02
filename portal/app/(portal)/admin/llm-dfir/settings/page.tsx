"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Loader2,
  PlugZap,
  RefreshCw,
  Save,
  XCircle,
  Sparkles,
  ShieldAlert,
  Clock,
  Zap,
  Database,
  Brain,
} from "lucide-react";
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
import type { LlmConfig, LlmConfigUpdate, LlmModelsResult, LlmTestResult } from "@/lib/types";
import { formatDateTime } from "@/lib/format";

/**
 * Cấu hình LLM (Super Admin) — Ollama local / OpenAI / Qwen / vLLM.
 *
 * Style theo Design.md:
 *  - Trang trên canvas giấy ấm (`slate-50`); card trắng + hairline (`slate-200`)
 *  - Một accent cấu trúc duy nhất — brand-600 (Notion blue) cho toggle ON,
 *    primary CTA, focus ring
 *  - Status pill: sticker palette (emerald/amber/rose) — không dùng cho CTA
 *  - Pill CTA (`rounded-full`), input vuông nhẹ (`rounded-xs`), hairline border
 *  - Typography: heading heavy 700 + tracking âm, body 15-16px line-height 1.5
 *
 * Layout (sau khi chỉnh):
 *  1. Status strip — Trạng thái / Kết nối / Tokens (1 hàng full-width)
 *  2. Backend — full-width card
 *  3. Kết quả test — full-width card, CHỈ hiển thị khi đã test (không có quick guide)
 *  4. Tham số — full-width card
 *  5. System Prompt — full-width card với textarea lớn (rows=20, auto-grow)
 *  6. Sticky action bar
 */
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
  const [maxTokens, setMaxTokens] = useState(64000);
  const [temperature, setTemperature] = useState(0.0);
  const [requestTimeout, setRequestTimeout] = useState(120);
  const [maxContextChars, setMaxContextChars] = useState(200000);
  const [allowCloud, setAllowCloud] = useState(false);
  const [dailyTokenBudget, setDailyTokenBudget] = useState<number | "">("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);

  // Auto-grow textarea cho System Prompt — bám theo nội dung, tối thiểu ~20 dòng
  const promptRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const ta = promptRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.max(ta.scrollHeight, 480)}px`;
  }, [systemPrompt]);

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
      setAvailableModels(s.available_models ?? []);
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
        external_orchestrator: "deepagent",
        deepagent_enabled: true,
      };
      if (apiKey) body.api_key = apiKey;
      const updated = await api.put<LlmConfig>("/admin/llm-dfir/config", body);
      setData(updated);
      setSavedMsg("Đã lưu cấu hình LLM.");
      setApiKey("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const loadModels = async () => {
    setLoadingModels(true);
    setError(null);
    try {
      const result = await api.post<LlmModelsResult>("/admin/llm-dfir/config/models");
      setAvailableModels(result.models);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách model");
    } finally {
      setLoadingModels(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setError(null);
    try {
      const res = await api.post<LlmTestResult>("/admin/llm-dfir/config/test");
      setTestResult(res);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test thất bại");
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <Spinner label="Đang tải cấu hình..." />;
  if (error && !data) return <ErrorBanner message={error} onRetry={load} />;

  const testStatus = data?.test_status ?? null;
  const testBadge =
    testStatus === "ok"
      ? "bg-emerald-100 text-emerald-700 ring-emerald-600/20"
      : testStatus === "error"
        ? "bg-rose-100 text-rose-700 ring-rose-600/20"
        : "bg-slate-100 text-slate-700 ring-slate-600/20";

  const tokenBudgetUsed = data?.tokens_used_today ?? 0;
  const tokenBudgetMax = data?.daily_token_budget ?? null;
  const tokenBudgetPct =
    tokenBudgetMax && tokenBudgetMax > 0
      ? Math.min(100, Math.round((tokenBudgetUsed / tokenBudgetMax) * 100))
      : null;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      {error && <ErrorBanner message={error} />}
      {savedMsg && (
        <div
          role="status"
          className="flex items-center gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800"
        >
          <span className="flex size-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
            <CheckCircle2 className="size-3.5" />
          </span>
          {savedMsg}
        </div>
      )}

      {/* ── Status strip ─────────────────────────────────────── */}
      <section className="ai-card px-5 py-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
          <div className="flex items-center gap-3">
            <span
              className={`flex size-9 items-center justify-center rounded-lg ${
                enabled ? "bg-brand-50 text-brand-600" : "bg-slate-100 text-slate-400"
              }`}
            >
              <Brain className="size-5" />
            </span>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Trạng thái
              </p>
              <p className="text-sm font-semibold tracking-tight text-slate-900">
                {enabled ? "LLM đang hoạt động" : "LLM đã tắt"}
              </p>
            </div>
            <Toggle
              checked={enabled}
              onChange={setEnabled}
              label={enabled ? "Tắt LLM" : "Bật LLM"}
              className="ml-2"
            />
          </div>

          <span className="hidden h-10 w-px bg-slate-200 sm:block" aria-hidden />

          <div className="flex items-center gap-3">
            <span
              className={`flex size-9 items-center justify-center rounded-lg ${
                testStatus === "ok"
                  ? "bg-emerald-100 text-emerald-700"
                  : testStatus === "error"
                    ? "bg-rose-100 text-rose-700"
                    : "bg-slate-100 text-slate-500"
              }`}
            >
              {testStatus === "ok" ? (
                <CheckCircle2 className="size-5" />
              ) : testStatus === "error" ? (
                <XCircle className="size-5" />
              ) : (
                <Activity className="size-5" />
              )}
            </span>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Kết nối
              </p>
              <div className="flex items-center gap-2">
                <Badge className={testBadge}>{testStatus ?? "chưa test"}</Badge>
                {data?.test_at && (
                  <span className="text-xs text-slate-500">
                    lúc {formatDateTime(data.test_at)}
                  </span>
                )}
              </div>
              {data?.test_error && (
                <p className="mt-0.5 text-xs text-rose-600">— {data.test_error}</p>
              )}
            </div>
          </div>

          <span className="hidden h-10 w-px bg-slate-200 sm:block" aria-hidden />

          <div className="flex min-w-[180px] items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
              <Zap className="size-5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Tokens hôm nay
              </p>
              <p className="text-sm font-semibold tracking-tight tabular-nums text-slate-900">
                {tokenBudgetUsed.toLocaleString("vi-VN")}
                {tokenBudgetMax ? (
                  <span className="font-normal text-slate-500">
                    {" "}
                    / {tokenBudgetMax.toLocaleString("vi-VN")}
                  </span>
                ) : null}
              </p>
              {tokenBudgetPct !== null && (
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      tokenBudgetPct >= 90
                        ? "bg-rose-500"
                        : tokenBudgetPct >= 70
                          ? "bg-amber-500"
                          : "bg-emerald-500"
                    }`}
                    style={{ width: `${tokenBudgetPct}%` }}
                    aria-label={`${tokenBudgetPct}% ngân sách đã dùng`}
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* ── Backend (full-width) ─────────────────────────────── */}
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            <Database className="size-4 text-slate-400" />
            Backend
          </span>
        }
        subtitle="Chọn nhà cung cấp LLM và thông tin kết nối"
      >
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Field label="Provider">
              <Select
                value={provider}
                onChange={(e) => {
                  const v = e.target.value;
                  setProvider(v);
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
            <Field label="Base URL" className="md:col-span-2">
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://127.0.0.1:11434/v1"
              />
            </Field>
          </div>

          <Field label="API Key" hint="Để trống nếu muốn giữ nguyên giá trị hiện tại.">
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={data?.api_key_masked ?? "(chưa đặt)"}
            />
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-500">
              <span>Hiện tại:</span>
              <code className="rounded-xs bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                {data?.api_key_masked}
              </code>
            </div>
          </Field>

          {/* Model chính — input full-width, nút Tải model đặt DƯỚI input (icon + label nowrap) */}
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
                {availableModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <button
                type="button"
                onClick={loadModels}
                disabled={loadingModels}
                title="Nạp model từ cấu hình LLM đã lưu"
                className="mt-2 inline-flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-white px-3 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-300 transition-all duration-150 hover:bg-slate-50 active:bg-slate-100 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loadingModels ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="size-3.5" />
                )}
                Tải model từ backend
              </button>
            </Field>
            <Field label="Model dự phòng" hint="Tùy chọn. Dùng khi model chính lỗi.">
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

      {/* ── Kết quả test — chỉ hiển thị khi đã test, full-width ── */}
      {testResult && (
        <Card
          title={
            <span className="inline-flex items-center gap-2">
              <PlugZap className="size-4 text-slate-400" />
              Kết quả test
            </span>
          }
          subtitle={data?.test_at ? `Test lúc ${formatDateTime(data.test_at)}` : undefined}
          actions={
            <Button variant="outline" size="sm" onClick={testConnection} disabled={testing}>
              {testing ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <PlugZap className="size-3.5" />
              )}
              Test lại
            </Button>
          }
        >
          <div className="space-y-4">
            <div
              role="status"
              className={`flex items-center gap-2.5 rounded-lg px-4 py-3 text-sm font-semibold ${
                testResult.ok
                  ? "bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200"
                  : "bg-rose-50 text-rose-800 ring-1 ring-inset ring-rose-200"
              }`}
            >
              {testResult.ok ? (
                <CheckCircle2 className="size-4 shrink-0" />
              ) : (
                <XCircle className="size-4 shrink-0" />
              )}
              {testResult.ok ? "Kết nối thành công" : `Lỗi: ${testResult.error}`}
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Latency
                </p>
                <p className="mt-0.5 text-base font-bold tabular-nums tracking-tight text-slate-900">
                  {testResult.latency_ms}ms
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Models khả dụng
                </p>
                <p className="mt-0.5 text-base font-bold tabular-nums tracking-tight text-slate-900">
                  {testResult.models.length}
                </p>
              </div>
              {testResult.models[0] && (
                <div className="col-span-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Model mặc định
                  </p>
                  <p className="mt-0.5 truncate text-sm font-semibold tracking-tight text-slate-900">
                    {testResult.models[0]}
                  </p>
                </div>
              )}
            </div>

            {testResult.models.length > 0 && (
              <div>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Danh sách model
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {testResult.models.map((m) => (
                    <Badge key={m} className="bg-slate-100 text-slate-700 ring-slate-600/20">
                      {m}
                    </Badge>
                  ))}
                  {testResult.models.length > 20 && (
                    <Badge className="bg-slate-100 text-slate-700 ring-slate-600/20">
                      +{testResult.models.length - 20} nữa
                    </Badge>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* ── Tham số ─────────────────────────────────────────── */}
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            <Sparkles className="size-4 text-slate-400" />
            Tham số
          </span>
        }
        subtitle="Giới hạn & chi phí cho mỗi phiên gọi LLM"
      >
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Field
            label="Max Tokens"
            hint="Độ dài tối đa của câu trả lời (64 – 32 000)."
          >
            <Input
              type="number"
              min={64000}
              max={128000}
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value) || 64000)}
            />
          </Field>
          <Field label="Temperature" hint="0 = chính xác, 1 = sáng tạo.">
            <Input
              type="number"
              step="0.1"
              min={0}
              max={2}
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value) || 0)}
            />
          </Field>
          <Field label="Timeout" hint="Giây — hết thời gian chờ.">
            <div className="relative">
              <Input
                type="number"
                min={10}
                max={600}
                value={requestTimeout}
                onChange={(e) => setRequestTimeout(parseInt(e.target.value) || 120)}
              />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">
                giây
              </span>
            </div>
          </Field>
          <Field label="Daily Token Budget" hint="0 = không giới hạn.">
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

        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field
            label="Max Context (ký tự)"
            hint="Log Velociraptor được cắt còn tối đa số ký tự này trước khi gửi LLM (tránh OOM local LLM)."
          >
            <Input
              type="number"
              min={1000}
              max={1_000_000}
              value={maxContextChars}
              onChange={(e) => setMaxContextChars(parseInt(e.target.value) || 200000)}
            />
          </Field>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold tracking-tight text-slate-900">
                  Cho phép gọi cloud API
                </p>
                <p className="mt-0.5 text-xs leading-snug text-slate-500">
                  Cần bật để đặt API key cho endpoint public (OpenAI, Qwen, …).
                </p>
              </div>
              <Toggle
                checked={allowCloud}
                onChange={setAllowCloud}
                label="Cho phép gọi cloud API"
              />
            </div>
            {allowCloud && (
              <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  Dữ liệu log sẽ được gửi tới nhà cung cấp bên thứ ba. Cân nhắc khi xử lý dữ
                  liệu nhạy cảm.
                </span>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* ── System Prompt — textarea lớn, auto-grow ──────────── */}
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            <Brain className="size-4 text-slate-400" />
            System Prompt của LangGraph
          </span>
        }
        subtitle="Áp dụng cho mọi cuộc điều tra mới. Policy DFIR và allowlist hệ thống luôn được giữ nguyên."
      >
        <div className="rounded-lg border border-slate-200 bg-white p-1 ring-1 ring-inset ring-slate-200 focus-within:border-brand-600 focus-within:ring-brand-600/30">
          <textarea
            ref={promptRef}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Ưu tiên đánh giá hành vi PowerShell, persistence và kết nối C2; trình bày kết luận ngắn gọn cho quản trị viên."
            spellCheck={false}
            className="block w-full resize-none rounded-md border-0 bg-transparent px-3 py-3 font-mono text-[13px] leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0"
            style={{ minHeight: 480 }}
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span className="tabular-nums">
            {systemPrompt.length.toLocaleString("vi-VN")} ký tự ·{" "}
            {systemPrompt.split(/\s+/).filter(Boolean).length.toLocaleString("vi-VN")} từ
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" />
            Áp dụng cho cuộc điều tra tiếp theo
          </span>
        </div>
      </Card>

      {/* ── Sticky action bar ────────────────────────────────── */}
      <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-full border border-slate-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur">
        <div className="min-w-0 pl-2 text-xs text-slate-500">
          {saving ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-brand-700">
              <Loader2 className="size-3 animate-spin" />
              Đang lưu…
            </span>
          ) : savedMsg ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-emerald-700">
              <CheckCircle2 className="size-3" />
              Đã lưu cấu hình
            </span>
          ) : (
            "Thay đổi sẽ được áp dụng sau khi lưu."
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={testConnection} disabled={testing} variant="outline">
            {testing ? <Loader2 className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
            Test connection
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            Lưu cấu hình
          </Button>
        </div>
      </div>
    </div>
  );
}
