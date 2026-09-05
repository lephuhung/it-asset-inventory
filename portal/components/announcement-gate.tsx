"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { BellRing, Check, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { SystemAnnouncement } from "@/lib/types";
import { Button, Modal, Spinner } from "@/components/ui";

/**
 * AnnouncementGate — Hiển thị thông báo dạng Modal khi đăng nhập.
 *
 * Tuân thủ nghiêm ngặt theo Design.md:
 * - Modal nền trắng surface, viền hairline #e6e6e6, elevated Level-2.
 * - Tiêu đề đậm phong cách NotionInter với tracking-tight.
 * - Nút hành động chính (Primary CTA) dạng viên thuốc pill rounded-full với màu Notion Blue (#0075de).
 * - Sticker accent cho icon trang trí.
 */
export function AnnouncementGate({ disabled = false }: { disabled?: boolean }) {
  const [loading, setLoading] = useState(true);
  const [announcements, setAnnouncements] = useState<SystemAnnouncement[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPending = useCallback(async () => {
    if (disabled) {
      setLoading(false);
      return;
    }
    try {
      const items = await api.get<SystemAnnouncement[]>("/announcements/pending");
      if (Array.isArray(items) && items.length > 0) {
        setAnnouncements(items);
        setCurrentIndex(0);
      }
    } catch {
      // Không chặn người dùng nếu API lỗi hoặc chưa có dữ liệu
    } finally {
      setLoading(false);
    }
  }, [disabled]);

  useEffect(() => {
    void fetchPending();
  }, [fetchPending]);

  const current = announcements[currentIndex] ?? null;

  const handleAcknowledge = async () => {
    if (!current) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/announcements/${current.id}/read`);
      if (currentIndex + 1 < announcements.length) {
        setCurrentIndex((i) => i + 1);
      } else {
        // Đã xem hết tất cả thông báo
        setAnnouncements([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ghi nhận thất bại, vui lòng thử lại");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || !current) return null;

  const isMultiple = announcements.length > 1;
  const isLast = currentIndex === announcements.length - 1;

  return (
    <Modal
      open={true}
      onClose={() => {
        // Không đóng khi chưa click xác nhận nhằm đảm bảo người dùng đã đọc thông báo đăng nhập
      }}
      wide
      title={
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 items-center justify-center rounded-lg bg-sky-50 text-brand-600">
            {current.target_type === "FIRST_LOGIN" ? (
              <Sparkles className="size-4" />
            ) : (
              <BellRing className="size-4" />
            )}
          </span>
          <span className="font-bold tracking-tight text-slate-900">{current.title}</span>
          {isMultiple && (
            <span className="ml-2 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
              {currentIndex + 1} / {announcements.length}
            </span>
          )}
        </div>
      }
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          <div className="text-xs text-slate-400">
            {current.target_type === "FIRST_LOGIN" ? (
              <span>✨ Chào mừng bạn đến với hệ thống</span>
            ) : (
              <span>📌 Thông báo hệ thống</span>
            )}
          </div>
          <Button
            variant="primary"
            loading={submitting}
            onClick={handleAcknowledge}
            className="rounded-full px-6 shadow-sm"
          >
            <Check className="size-4" />
            {isLast ? "Tôi đã hiểu & Bắt đầu sử dụng" : "Tiếp tục"}
          </Button>
        </div>
      }
    >
      <div className="max-h-[60vh] overflow-y-auto pr-2">
        <div className="prose prose-slate max-w-none text-sm leading-relaxed text-slate-700">
          <ReactMarkdown
            components={{
              h1: ({ children }) => (
                <h1 className="mt-2 mb-3 text-lg font-bold tracking-tight text-slate-900 border-b border-slate-100 pb-2">
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className="mt-4 mb-2 text-base font-semibold tracking-tight text-slate-800">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="mt-3 mb-1.5 text-sm font-semibold text-slate-800">
                  {children}
                </h3>
              ),
              ul: ({ children }) => (
                <ul className="my-2 ml-5 list-disc space-y-1 text-slate-600">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="my-2 ml-5 list-decimal space-y-1 text-slate-600">{children}</ol>
              ),
              li: ({ children }) => <li className="leading-relaxed">{children}</li>,
              blockquote: ({ children }) => (
                <blockquote className="my-3 border-l-3 border-brand-500 bg-sky-50/50 px-3.5 py-2 text-xs italic text-slate-700 rounded-r-md">
                  {children}
                </blockquote>
              ),
              strong: ({ children }) => (
                <strong className="font-semibold text-slate-900">{children}</strong>
              ),
              code: ({ children }) => (
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-800">
                  {children}
                </code>
              ),
            }}
          >
            {current.content_md}
          </ReactMarkdown>
        </div>

        {error && (
          <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
