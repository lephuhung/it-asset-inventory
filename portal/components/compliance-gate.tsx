"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { FileText } from "lucide-react";
import { api } from "@/lib/api";
import type { ComplianceNotice } from "@/lib/types";
import { Button, Modal } from "@/components/ui";

/**
 * ComplianceGate — theo mục 7.4: bắt buộc xác nhận thông báo tuân thủ
 * (bản đang hiệu lực) trước khi tiếp tục dùng portal.
 */
export function ComplianceGate({ disabled = false }: { disabled?: boolean }) {
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<ComplianceNotice | null>(null);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    if (disabled) return;
    try {
      const hasPending = await api.get<boolean>("/compliance/pending");
      setPending(hasPending);
      if (hasPending) {
        const current = await api.get<ComplianceNotice | null>("/compliance/current");
        if (current) {
          setNotice(current);
          setOpen(true);
        }
      }
    } catch {
      // Backend chưa có dữ liệu tuân thủ — không chặn người dùng.
    } finally {
      setLoading(false);
    }
  }, [disabled]);

  useEffect(() => {
    void check();
  }, [check]);

  const acknowledge = async () => {
    if (!notice) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/compliance/acknowledge", { notice_id: notice.id });
      setOpen(false);
      setPending(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xác nhận thất bại");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || (!open && !pending)) return null;

  return (
    <Modal
      open={open}
      onClose={() => {
        if (pending && !submitting) window.location.reload(); // chưa xác nhận → không vào hệ thống
        else setOpen(false);
      }}
      title={
        <span className="inline-flex items-center gap-2">
          <FileText className="size-4 text-brand-600" />
          {notice?.title ?? "Thông báo tuân thủ"}
          {notice && <span className="text-xs text-slate-400">v{notice.version}</span>}
        </span>
      }
      width="lg"
      footer={
        <>
          <Button variant="secondary" onClick={() => window.location.href = "/login"}>
            Trở về đăng nhập
          </Button>
          <Button variant="primary" loading={submitting} onClick={acknowledge}>
            Tôi đã đọc và đồng ý
          </Button>
        </>
      }
    >
      <div className="max-h-[50vh] overflow-y-auto pr-1">
        <div className="prose-md text-sm text-slate-700">
          <ReactMarkdown>{notice?.content_md ?? ""}</ReactMarkdown>
        </div>
        {error && (
          <p className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
        )}
        <p className="mt-4 text-xs text-slate-400">
          Việc xác nhận được ghi vào nhật ký (audit) kèm thời gian và địa chỉ IP theo quy định.
        </p>
      </div>
    </Modal>
  );
}