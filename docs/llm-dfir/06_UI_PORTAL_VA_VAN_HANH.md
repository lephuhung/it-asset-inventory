# 06 — UI Portal (Next.js) + Vận hành

---

## A. Cấu trúc trang portal

```
portal/src/app/(portal)/admin/llm-dfir/
├── settings/
│   └── page.tsx                    # Cấu hình LLM
├── investigations/
│   ├── page.tsx                    # Danh sách
│   └── [id]/
│       └── page.tsx                # Chi tiết + chat
└── _components/
    ├── LlmConfigForm.tsx
    ├── InvestigationCard.tsx
    ├── ReportViewer.tsx            # render markdown + severity badge
    └── ChatBox.tsx                 # Q&A với LLM
```

---

## B. Page: Settings (`settings/page.tsx`)

```tsx
"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/use-toast";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

type LlmConfig = {
  enabled: boolean;
  provider: string;
  base_url: string;
  api_key_masked: string;
  model: string;
  fallback_model: string | null;
  system_prompt: string | null;
  max_tokens: number;
  temperature: number;
  request_timeout: number;
  max_context_chars: number;
  allow_cloud: boolean;
  daily_token_budget: number | null;
  tokens_used_today: number;
  test_status: string | null;
  test_error: string | null;
  available_models: string[];
};

export default function LlmSettingsPage() {
  const { toast } = useToast();
  const [cfg, setCfg] = useState<LlmConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  // Form state
  const [form, setForm] = useState<Partial<LlmConfig>>({});
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    fetch("/api/admin/llm-dfir/config")
      .then((r) => r.json())
      .then((data) => {
        setCfg(data);
        setForm(data);
        setLoading(false);
      });
  }, []);

  const onSave = async () => {
    setSaving(true);
    const body = { ...form, api_key: apiKey || undefined };
    const r = await fetch("/api/admin/llm-dfir/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSaving(false);
    if (r.ok) {
      toast({ title: "Đã lưu cấu hình" });
      setApiKey("");
      const data = await r.json();
      setCfg(data);
      setForm(data);
    } else {
      const err = await r.json();
      toast({ title: "Lỗi", description: err.detail, variant: "destructive" });
    }
  };

  const onTest = async () => {
    setTesting(true);
    const r = await fetch("/api/admin/llm-dfir/config/test", { method: "POST" });
    const data = await r.json();
    setTesting(false);
    if (data.ok) {
      toast({
        title: "✓ Kết nối OK",
        description: `${data.latency_ms}ms · ${data.models.length} model khả dụng`,
      });
    } else {
      toast({ title: "✗ Lỗi kết nối", description: data.error, variant: "destructive" });
    }
    fetch("/api/admin/llm-dfir/config").then((r) => r.json()).then(setCfg);
  };

  if (loading) return <Loader2 className="animate-spin" />;
  if (!cfg) return <div>Không tải được cấu hình</div>;

  return (
    <div className="space-y-6 p-6 max-w-4xl">
      <h1 className="text-2xl font-bold">Cấu hình LLM (DFIR AI Assistant)</h1>

      <Card>
        <CardHeader>
          <CardTitle>Trạng thái</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Switch
              checked={form.enabled}
              onCheckedChange={(v) => setForm({ ...form, enabled: v })}
            />
            <Label>Bật tính năng LLM-DFIR</Label>
          </div>
          {cfg.test_status && (
            <div className="flex items-center gap-2 text-sm">
              {cfg.test_status === "ok" ? (
                <CheckCircle2 className="text-green-500 h-4 w-4" />
              ) : (
                <XCircle className="text-red-500 h-4 w-4" />
              )}
              <span>
                Test cuối: {cfg.test_status}
                {cfg.test_error && ` — ${cfg.test_error}`}
              </span>
            </div>
          )}
          <div className="text-sm text-muted-foreground">
            Tokens dùng hôm nay: <strong>{cfg.tokens_used_today}</strong>
            {cfg.daily_token_budget && ` / ${cfg.daily_token_budget}`}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Backend</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label>Provider</Label>
            <select
              className="w-full border rounded px-3 py-2"
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}
            >
              <option value="ollama">Ollama (local)</option>
              <option value="localai">LocalAI</option>
              <option value="vllm">vLLM</option>
              <option value="openai">OpenAI</option>
              <option value="qwen">Qwen / DashScope</option>
              <option value="deepseek">DeepSeek</option>
              <option value="custom">Custom OpenAI-compatible</option>
            </select>
          </div>

          <div>
            <Label>Base URL</Label>
            <Input
              value={form.base_url ?? ""}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              placeholder="http://127.0.0.1:11434/v1"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Endpoint OpenAI-compatible. Mặc định: Ollama local.
            </p>
          </div>

          <div>
            <Label>API Key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={cfg.api_key_masked}
            />
            <p className="text-xs text-muted-foreground mt-1">
              Hiện tại: <code>{cfg.api_key_masked}</code> (để trống nếu muốn giữ nguyên)
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Model chính</Label>
              <Input
                list="models-list"
                value={form.model ?? ""}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
              <datalist id="models-list">
                {cfg.available_models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            <div>
              <Label>Model dự phòng</Label>
              <Input
                list="models-list"
                value={form.fallback_model ?? ""}
                onChange={(e) =>
                  setForm({ ...form, fallback_model: e.target.value || null })
                }
                placeholder="(tuỳ chọn)"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tham số</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Max Tokens</Label>
              <Input
                type="number"
                value={form.max_tokens ?? 4096}
                onChange={(e) =>
                  setForm({ ...form, max_tokens: parseInt(e.target.value) })
                }
              />
            </div>
            <div>
              <Label>Temperature</Label>
              <Input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={form.temperature ?? 0}
                onChange={(e) =>
                  setForm({ ...form, temperature: parseFloat(e.target.value) })
                }
              />
            </div>
            <div>
              <Label>Timeout (giây)</Label>
              <Input
                type="number"
                value={form.request_timeout ?? 120}
                onChange={(e) =>
                  setForm({ ...form, request_timeout: parseInt(e.target.value) })
                }
              />
            </div>
            <div>
              <Label>Max Context (ký tự)</Label>
              <Input
                type="number"
                value={form.max_context_chars ?? 200000}
                onChange={(e) =>
                  setForm({
                    ...form,
                    max_context_chars: parseInt(e.target.value),
                  })
                }
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={form.allow_cloud}
              onCheckedChange={(v) => setForm({ ...form, allow_cloud: v })}
            />
            <Label>Cho phép gọi cloud API (OpenAI/Qwen)</Label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>System Prompt (nâng cao)</CardTitle>
        </CardHeader>
        <CardContent>
          <Textarea
            rows={8}
            value={form.system_prompt ?? ""}
            onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
            placeholder="(Để trống = dùng mặc định tiếng Việt cho DFIR)"
          />
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Button onClick={onSave} disabled={saving}>
          {saving && <Loader2 className="animate-spin mr-2 h-4 w-4" />}
          Lưu cấu hình
        </Button>
        <Button onClick={onTest} variant="outline" disabled={testing}>
          {testing && <Loader2 className="animate-spin mr-2 h-4 w-4" />}
          Test connection
        </Button>
      </div>
    </div>
  );
}
```

---

## C. Page: Investigation Detail với Chat

```tsx
// portal/src/app/(portal)/admin/llm-dfir/investigations/[id]/page.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { use } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Loader2, Send, AlertOctagon, ShieldAlert, AlertTriangle, Info, CheckCircle2 } from "lucide-react";
import ReactMarkdown from "react-markdown";

const SEVERITY_ICONS: Record<string, { icon: any; color: string; label: string }> = {
  critical: { icon: AlertOctagon, color: "bg-red-700", label: "Critical" },
  high: { icon: ShieldAlert, color: "bg-orange-600", label: "High" },
  medium: { icon: AlertTriangle, color: "bg-yellow-600", label: "Medium" },
  low: { icon: Info, color: "bg-blue-600", label: "Low" },
  info: { icon: CheckCircle2, color: "bg-green-600", label: "Info" },
};

export default function InvestigationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [inv, setInv] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatting, setChatting] = useState(false);
  const [polling, setPolling] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Polling nếu đang chạy
  useEffect(() => {
    const fetchInv = async () => {
      const r = await fetch(`/api/admin/llm-dfir/investigations/${id}`);
      if (r.ok) {
        const data = await r.json();
        setInv(data);
        if (["pending", "running", "collecting", "analyzing"].includes(data.status)) {
          setPolling(true);
        } else {
          setPolling(false);
          // Khi completed → load messages
          const r2 = await fetch(`/api/admin/llm-dfir/investigations/${id}/messages`);
          if (r2.ok) setMessages(await r2.json());
        }
      }
    };
    fetchInv();
    if (polling) {
      const t = setInterval(fetchInv, 5000);
      return () => clearInterval(t);
    }
  }, [id, polling]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const onChat = async () => {
    if (!chatInput.trim()) return;
    setChatting(true);
    const userMsg = { role: "user", content: chatInput, created_at: new Date().toISOString() };
    setMessages((m) => [...m, userMsg]);
    setChatInput("");

    const r = await fetch(`/api/admin/llm-dfir/investigations/${id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: chatInput }),
    });
    setChatting(false);
    if (r.ok) {
      const data = await r.json();
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.response,
          created_at: new Date().toISOString(),
        },
      ]);
    } else {
      const err = await r.json();
      alert("Lỗi: " + err.detail);
    }
  };

  if (!inv) return <Loader2 className="animate-spin" />;

  const severity = SEVERITY_ICONS[inv.severity] || SEVERITY_ICONS.info;
  const SeverityIcon = severity.icon;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
      {/* Report panel */}
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Điều tra: {inv.machine_hostname || inv.machine_id}</span>
              <Badge className={severity.color}>
                <SeverityIcon className="h-3 w-3 mr-1" />
                {severity.label}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div><strong>Trạng thái:</strong> {inv.status}</div>
              <div><strong>Phát hiện:</strong> {inv.findings_count ?? "—"}</div>
              <div><strong>Model:</strong> {inv.llm_model ?? "—"}</div>
              <div><strong>Tokens:</strong> {inv.input_tokens ?? 0} → {inv.output_tokens ?? 0}</div>
              {inv.estimated_cost_usd != null && (
                <div><strong>Chi phí:</strong> ${inv.estimated_cost_usd.toFixed(4)}</div>
              )}
              <div><strong>Artifacts:</strong> {inv.artifacts.length}</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Báo cáo</CardTitle>
          </CardHeader>
          <CardContent>
            {inv.status === "pending" && <p>⏳ Đang chờ worker xử lý…</p>}
            {inv.status === "running" && <p>🔄 Đang gọi Velociraptor…</p>}
            {inv.status === "collecting" && <p>📥 Đang thu thập dữ liệu từ endpoint…</p>}
            {inv.status === "analyzing" && <p>🤖 Đang gọi LLM phân tích…</p>}
            {inv.status === "failed" && (
              <div className="text-red-600">❌ Lỗi: {inv.error}</div>
            )}
            {inv.status === "completed" && inv.report_markdown && (
              <article className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{inv.report_markdown}</ReactMarkdown>
              </article>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Chat panel */}
      <div className="space-y-4">
        <Card className="flex flex-col h-[calc(100vh-200px)]">
          <CardHeader>
            <CardTitle>Hỏi tiếp LLM</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto space-y-3">
            {messages
              .filter((m) => m.role !== "system")
              .map((m, i) => (
                <div
                  key={i}
                  className={`p-3 rounded ${
                    m.role === "user"
                      ? "bg-blue-100 dark:bg-blue-900 ml-12"
                      : "bg-gray-100 dark:bg-gray-800 mr-12"
                  }`}
                >
                  <div className="text-xs text-muted-foreground mb-1">
                    {m.role === "user" ? "Bạn" : "AI Assistant"}
                  </div>
                  {m.role === "assistant" ? (
                    <ReactMarkdown>{m.content}</ReactMarkdown>
                  ) : (
                    <div className="whitespace-pre-wrap">{m.content}</div>
                  )}
                </div>
              ))}
            <div ref={chatEndRef} />
          </CardContent>
          <div className="p-4 border-t">
            <Textarea
              rows={2}
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="VD: Có dấu hiệu crypto miner không? Có kết nối ra ngoài đáng ngờ không?"
              disabled={inv.status !== "completed" || chatting}
            />
            <Button
              className="mt-2 w-full"
              onClick={onChat}
              disabled={!chatInput.trim() || chatting || inv.status !== "completed"}
            >
              {chatting ? <Loader2 className="animate-spin mr-2 h-4 w-4" /> : <Send className="mr-2 h-4 w-4" />}
              Gửi
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
```

---

## D. Vận hành — Runbook hàng ngày

### D.1 Khởi động hệ thống

```bash
# 1. Khởi Ollama (nếu dùng local)
systemctl status ollama   # Linux
# Hoặc mở app Ollama (Windows)

# 2. Khởi infrastructure
cd server/deploy && docker compose up -d postgres redis ollama

# 3. Khởi API
cd server && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. (Optional) Khởi portal
cd portal && pnpm dev
```

### D.2 Health check

```bash
# Ollama
curl http://127.0.0.1:11434/api/tags

# API
curl http://localhost:8000/health

# Test LLM config
curl -b cookies.txt -X POST http://localhost:8000/api/admin/llm-dfir/config/test
```

### D.3 Trigger investigation

```bash
# 1. Lấy machine_id
curl -b cookies.txt "http://localhost:8000/api/machines?limit=1"

# 2. Trigger
curl -b cookies.txt -X POST http://localhost:8000/api/admin/llm-dfir/investigations \
  -H "Content-Type: application/json" \
  -d '{"machine_id": "abc-123", "custom_instructions": "Tập trung vào lateral movement"}'

# 3. Poll mỗi 5s cho đến khi completed
INV_ID=...
while true; do
  STATUS=$(curl -sb cookies.txt http://localhost:8000/api/admin/llm-dfir/investigations/$INV_ID | jq -r .status)
  echo "$(date +%H:%M:%S) status=$STATUS"
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 5
done

# 4. Xem report
curl -sb cookies.txt http://localhost:8000/api/admin/llm-dfir/investigations/$INV_ID | jq .report_markdown
```

### D.4 Kiểm tra background worker có chạy không

```bash
# Log API sẽ có dòng như:
# "LLM-DFIR worker: 2 processed, 0 errors, 1234ms"
# Nếu không thấy → check:
grep -i "llm-dfir\|dfir_investigation" server/uvicorn.log | tail -20
```

### D.5 Thay model (không cần restart)

```bash
# Trên Ollama server
ollama pull qwen2.5:32b-instruct-q4_K_M

# Trên portal
# /admin/llm-dfir/settings → đổi model = "qwen2.5:32b-instruct-q4_K_M" → Test → Lưu
```

### D.6 Reset daily token counter (cron 0h hàng ngày)

Thêm vào `monitor.py`:
```python
# Reset tokens_used_today mỗi 0h
async def _reset_llm_daily_tokens():
    now = datetime.now(UTC)
    async with db_session.AsyncSessionLocal() as db:
        cfg = (await db.execute(select(LlmConfig).where(LlmConfig.id == 1))).scalar_one_or_none()
        if cfg and (cfg.tokens_reset_at is None or cfg.tokens_reset_at.date() < now.date()):
            cfg.tokens_used_today = 0
            cfg.tokens_reset_at = now
            await db.commit()
```

---

## E. Checklist triển khai pilot

- [ ] Cài Ollama trên 3 máy analyst (qwen2.5:14b-instruct-q4_K_M)
- [ ] Cấu hình LLM trên portal: provider=ollama, base_url=http://127.0.0.1:11434/v1
- [ ] Bấm "Test connection" → OK
- [ ] Trigger 1 investigation trên máy test → completed trong < 2 phút
- [ ] Đọc report → kiểm tra chất lượng tiếng Việt + định dạng markdown
- [ ] Hỏi 1 câu Q&A → response hợp lý
- [ ] Đo tốc độ: thời gian từ "Tạo" đến "Completed"
- [ ] Đo tài nguyên: RAM/CPU Ollama khi chạy
- [ ] Chạy trên 5 máy thật với 5 analyst khác nhau → khảo sát UX
- [ ] Review bảo mật: ai có quyền `require_super_admin`?
- [ ] Chuẩn bị tài liệu hướng dẫn sử dụng cho cán bộ CATP

---

## F. Tổng kết: Những gì đã có vs cần thêm

| Thành phần | Trạng thái | File |
|---|---|---|
| Tài liệu thiết kế | ✅ | `docs/llm-dfir/00_TONG_QUAN.md` |
| Hướng dẫn cài Ollama | ✅ | `docs/llm-dfir/01_CAI_DAT_OLLAMA.md` |
| Settings env + schema DB | ✅ (code mẫu) | `docs/llm-dfir/02_SETTINGS_VA_SCHEMA.md` |
| LLM service (OpenAI-compat) | ✅ (code mẫu) | `docs/llm-dfir/03_LLM_SERVICE.md` |
| Investigation orchestrator | ✅ (code mẫu) | `docs/llm-dfir/04_INVESTIGATION_FLOW.md` |
| API routes | ✅ (code mẫu) | `docs/llm-dfir/05_API_ROUTES.md` |
| UI Portal | ✅ (code mẫu) | `docs/llm-dfir/06_UI_PORTAL_VA_VAN_HANH.md` |
| Runbook vận hành | ✅ | Mục D ở trên |
| **TODO: tích hợp thực tế** | ⏳ | Áp dụng code mẫu vào codebase |
| **TODO: VelociraptorClient helper** | ⏳ | Bổ sung `collect_artifact`, `get_flow_status`, `get_flow_results` |
| **TODO: Test e2e** | ⏳ | Chạy pilot 5 máy thật |
