"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Check, CheckCircle2, Clock, FileText, History } from "lucide-react";
import { api } from "@/lib/api";
import type { ComplianceNotice } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Spinner,
} from "@/components/ui";

export default function CompliancePage() {
  const [notice, setNotice] = useState<ComplianceNotice | null>(null);
  const [pending, setPending] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ackBusy, setAckBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [current, hasPending] = await Promise.all([
        api.get<ComplianceNotice | null>("/compliance/current"),
        api.get<boolean>("/compliance/pending"),
      ]);
      setNotice(current);
      setPending(hasPending);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được thông báo tuân thủ");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const acknowledge = async () => {
    if (!notice) return;
    setAckBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/proxy/compliance/acknowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notice_id: notice.id }),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { detail?: string } | null;
        setError(data?.detail ?? "Không xác nhận được");
        return;
      }
      setPending(false);
    } catch {
      setError("Không kết nối được máy chủ");
    } finally {
      setAckBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Thông báo tuân thủ"
        description="Minh bạch việc thu thập dữ liệu — phù hợp Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading ? (
        <Spinner label="Đang tải thông báo…" />
      ) : !notice ? (
        <EmptyState
          icon={<FileText className="size-10" />}
          title="Chưa có thông báo tuân thủ hiệu lực"
          description="Server chưa phát hành bản thông báo nào (bảng compliance_notices)."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card
            className="lg:col-span-2"
            title={
              <span className="inline-flex items-center gap-2">
                <FileText className="size-4 text-brand-600" />
                {notice.title}
                <Badge className="bg-brand-50 text-brand-700 ring-brand-600/20">v{notice.version}</Badge>
              </span>
            }
            subtitle={`Hiệu lực từ ${new Date(notice.effective_from).toLocaleDateString("vi-VN")}`}
          >
            <div className="prose-md text-sm text-slate-700">
              <ReactMarkdown>{notice.content_md}</ReactMarkdown>
            </div>
          </Card>

          <div className="space-y-4">
            <Card title="Trạng thái xác nhận của bạn">
              {pending === null ? (
                <p className="text-sm text-slate-500">Đang kiểm tra…</p>
              ) : pending ? (
                <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
                  <Clock className="mt-0.5 size-4 shrink-0" />
                  <span>
                    Bạn chưa xác nhận bản này — hệ thống sẽ yêu cầu xác nhận trước khi tiếp tục sử
                    dụng.
                  </span>
                </div>
              ) : (
                <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                  Bạn đã xác nhận bản thông báo hiện hành.
                </div>
              )}
              {pending && (
                <Button className="mt-3 w-full" onClick={() => void acknowledge()} loading={ackBusy}>
                  <Check className="size-4" /> Tôi đã đọc và đồng ý
                </Button>
              )}
              <p className="mt-3 text-xs leading-relaxed text-slate-400">
                Xác nhận được ghi vào <code>user_acknowledgments</code> kèm thời gian + IP +
                nguồn (portal/installer), và ghi audit log — theo mục 7.4.
              </p>
            </Card>
            <Card title="Lịch sử các bản phát hành">
              <div className="flex items-start gap-3 text-sm text-slate-600">
                <History className="mt-0.5 size-4 shrink-0 text-slate-400" />
                <p>
                  Backend chưa có endpoint liệt kê lịch sử (bảng <code>compliance_notices</code>{" "}
                  version hóa) — bổ sung ở Phase 2 khi quản trị bản thông báo ra đời.
                </p>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}