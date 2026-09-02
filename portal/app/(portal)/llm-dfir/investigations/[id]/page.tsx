"use client";

import { use, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertOctagon,
  ArrowLeft,
  Brain,
  CheckCircle2,
  Clock,
  Info,
  Loader2,
  RefreshCcw,
  ShieldAlert,
  Trash2,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  ErrorBanner,
  Spinner,
} from "@/components/ui";
import type {
  DfirInvestigation,
  DfirInvestigationMessage,
  InvestigationSeverity,
  InvestigationStatus,
} from "@/lib/types";
import { formatDateTime } from "@/lib/format";
import { InvestigationMarkdown } from "@/components/investigation-markdown";
import { InvestigationChatPanel } from "@/components/investigation-chat-panel";

/* Badge pill tinted theo Design.md — màu đã remap trong globals.css */
const STATUS_META: Record<InvestigationStatus, { label: string; badge: string; icon: any }> = {
  pending: { label: "Chờ", badge: "bg-slate-100 text-slate-700 ring-slate-600/20", icon: Clock },
  running: { label: "Đang khởi động", badge: "bg-blue-100 text-blue-700 ring-blue-600/20", icon: Loader2 },
  collecting: { label: "Đang thu thập dữ liệu", badge: "bg-sky-50 text-sky-700 ring-sky-600/20", icon: RefreshCcw },
  analyzing: { label: "AI đang phân tích", badge: "bg-violet-100 text-violet-700 ring-violet-600/20", icon: Brain },
  completed: { label: "Hoàn thành", badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", icon: CheckCircle2 },
  failed: { label: "Lỗi", badge: "bg-rose-100 text-rose-700 ring-rose-600/20", icon: XCircle },
};

const SEVERITY_META: Record<InvestigationSeverity, { label: string; badge: string; icon: any }> = {
  critical: { label: "Critical", badge: "bg-rose-100 text-rose-700 ring-rose-600/20", icon: AlertOctagon },
  high: { label: "High", badge: "bg-amber-100 text-amber-700 ring-amber-600/20", icon: ShieldAlert },
  medium: { label: "Medium", badge: "bg-amber-50 text-amber-800 ring-amber-600/20", icon: ShieldAlert },
  low: { label: "Low", badge: "bg-blue-100 text-blue-700 ring-blue-600/20", icon: Info },
  info: { label: "Info", badge: "bg-emerald-100 text-emerald-700 ring-emerald-600/20", icon: CheckCircle2 },
};

export default function InvestigationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  // Lưu URL trang trước (từ máy hoặc từ stats/list) để "Quay lại" thông minh
  const fromPath = searchParams.get("from");
  const [inv, setInv] = useState<DfirInvestigation | null>(null);
  const [messages, setMessages] = useState<DfirInvestigationMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get<DfirInvestigation>(`/admin/llm-dfir/investigations/${id}`);
      setInv(data);
      setNotFound(false);
      if (data.status === "completed" || data.status === "failed") {
        const msgs = await api.get<DfirInvestigationMessage[]>(
          `/admin/llm-dfir/investigations/${id}/messages`,
        );
        setMessages(msgs);
      }
      setError(null);
    } catch (e: any) {
      // 404: investigation không tồn tại — hiển thị trang not-found thay vì error
      if (e?.status === 404) {
        setNotFound(true);
        setError(null);
      } else {
        setError(e instanceof Error ? e.message : "Không tải được");
      }
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Polling khi đang chạy
  useEffect(() => {
    if (!inv) return;
    const active = ["pending", "running", "collecting", "analyzing"].includes(inv.status);
    if (!active) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [inv, load]);

  /** Gửi chat qua panel — parent chịu trách nhiệm optimistic add + endpoint.
   *  Panel giữ `chatInput`/`chatting` local; panel đã clear input trước khi gọi
   *  callback nên ta chỉ push 2 message tạm vào state messages. */
  const sendChat = async (msg: string) => {
    if (!msg || !inv) return;
    // Optimistic add user message
    setMessages((m) => [
      ...m,
      {
        id: `tmp-${Date.now()}`,
        role: "user",
        content: msg,
        tokens: null,
        created_at: new Date().toISOString(),
      },
    ]);
    try {
      const res = await api.post<{ response: string; model: string }>(
        `/admin/llm-dfir/investigations/${id}/chat`,
        { message: msg },
      );
      setMessages((m) => [
        ...m,
        {
          id: `tmp-${Date.now()}-r`,
          role: "assistant",
          content: res.response,
          tokens: null,
          created_at: new Date().toISOString(),
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chat lỗi");
    }
  };

  const onDelete = async () => {
    setDeleting(true);
    try {
      await api.delete(`/admin/llm-dfir/investigations/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xoá lỗi");
      setDeleting(false);
    }
  };

  /** Nút "Quay lại" — ưu tiên URL `?from=` nếu có, fallback về list. */
  const goBack = () => {
    if (fromPath && fromPath.startsWith("/")) {
      router.push(fromPath);
    } else {
      // Fallback: dùng browser back nếu history tồn tại, ngược lại về list
      if (typeof window !== "undefined" && window.history.length > 1) {
        router.back();
      } else {
        router.push("/llm-dfir/investigations");
      }
    }
  };

  if (notFound) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <Button
          variant="ghost"
          onClick={goBack}
          size="sm"
        >
          <ArrowLeft className="size-4" />
          Quay lại danh sách
        </Button>
        <Card>
          <div className="space-y-3 py-12 text-center">
            <div className="text-6xl font-bold tracking-tight text-slate-900">404</div>
            <h2 className="text-xl font-semibold tracking-tight text-slate-900">
              Investigation không tồn tại
            </h2>
            <p className="text-sm text-slate-500">
              ID <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">{id}</code>{" "}
              không hợp lệ hoặc đã bị xoá.
            </p>
            <Button
              variant="outline"
              onClick={() => router.push("/llm-dfir/investigations")}
            >
              Xem danh sách investigations
            </Button>
          </div>
        </Card>
      </div>
    );
  }
  if (error && !inv) return <ErrorBanner message={error} onRetry={load} />;
  if (!inv) return <Spinner />;

  const statusInfo = STATUS_META[inv.status];
  const StatusIcon = statusInfo.icon;
  const sevInfo = inv.severity ? SEVERITY_META[inv.severity] : null;
  const SevIcon = sevInfo?.icon;
  const isActive = ["pending", "running", "collecting", "analyzing"].includes(inv.status);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <Button
          variant="ghost"
          onClick={goBack}
          size="sm"
        >
          <ArrowLeft className="size-4" />
          Quay lại
        </Button>
        {!isActive && (
          <Button
            variant="danger"
            size="sm"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="size-3.5" />
            Xoá
          </Button>
        )}
      </div>

      {error && <ErrorBanner message={error} />}

      {/* Header card */}
      <Card>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-bold tracking-tight text-slate-900">
              {inv.machine_hostname || inv.machine_id.slice(0, 8)}
            </h2>
            <Badge className={statusInfo.badge}>
              <StatusIcon className={`size-3.5 ${isActive ? "animate-spin" : ""}`} />
              {statusInfo.label}
            </Badge>
            {sevInfo && SevIcon && (
              <Badge className={sevInfo.badge}>
                <SevIcon className="size-3.5" />
                {sevInfo.label}
              </Badge>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm md:grid-cols-4">
            <div>
              <div className="text-xs text-slate-500">Tạo lúc</div>
              <div className="text-slate-900">{formatDateTime(inv.created_at)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Bắt đầu</div>
              <div className="text-slate-900">{inv.started_at ? formatDateTime(inv.started_at) : "—"}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Hoàn thành</div>
              <div className="text-slate-900">{inv.completed_at ? formatDateTime(inv.completed_at) : "—"}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Phát hiện</div>
              <div className="font-semibold text-slate-900">{inv.findings_count ?? "—"}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Model</div>
              <div className="truncate text-slate-900">{inv.llm_model ?? "—"}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Tokens</div>
              <div className="text-slate-900">
                {inv.input_tokens ?? 0} → {inv.output_tokens ?? 0}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Chi phí</div>
              <div className="text-slate-900">
                {inv.estimated_cost_usd != null
                  ? `$${inv.estimated_cost_usd.toFixed(4)}`
                  : "$0.00"}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Artifacts</div>
              <div className="truncate text-slate-900">{inv.artifacts.length}</div>
            </div>
          </div>
          {inv.artifacts.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {inv.artifacts.map((a) => (
                <Badge key={a} className="bg-slate-100 text-slate-700 ring-slate-600/20">
                  {a}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Báo cáo" bodyClass="flex flex-col min-h-0" className="min-h-[400px] max-h-[600px] flex flex-col">
          {inv.status === "pending" && (
            <p className="text-sm text-slate-500">⏳ Đang chờ worker xử lý…</p>
          )}
          {inv.status === "running" && (
            <p className="text-sm text-blue-700">🔄 Đang gọi Velociraptor thu thập dữ liệu…</p>
          )}
          {inv.status === "collecting" && (
            <p className="text-sm text-sky-700">📥 Đang thu thập dữ liệu từ endpoint…</p>
          )}
          {inv.status === "analyzing" && (
            <div className="flex items-center gap-2 text-sm text-violet-700">
              <Loader2 className="size-4 animate-spin" />
              AI đang phân tích log (có thể mất 30-60 giây)…
            </div>
          )}
          {inv.status === "failed" && (
            <div className="space-y-2">
              <div className="text-sm font-medium text-rose-700">❌ Điều tra thất bại</div>
              {inv.error && (
                <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-rose-200 bg-rose-50 p-3 font-mono text-xs leading-relaxed text-rose-700">
                  {inv.error}
                </pre>
              )}
            </div>
          )}
          {inv.status === "completed" && inv.report_markdown && (
            <div className="flex-1 overflow-y-auto rounded-md border border-slate-200 p-3">
              <InvestigationMarkdown content={inv.report_markdown} />
            </div>
          )}
        </Card>

        {/* Chat panel — input state local trong component con */}
        <InvestigationChatPanel
          investigationId={id}
          status={inv.status}
          messages={messages}
          onSend={sendChat}
        />
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Xoá cuộc điều tra?"
        message="Báo cáo và toàn bộ lịch sử chat sẽ bị xoá vĩnh viễn. Không thể hoàn tác."
        confirmLabel="Xoá"
        danger
        loading={deleting}
        onConfirm={onDelete}
      />
    </div>
  );
}
