"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, CheckCircle2, ExternalLink, Loader2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, ErrorBanner, Spinner } from "@/components/ui";
import type { TelegramLinkStartOut, TelegramLinkStatusOut } from "@/lib/types";

export default function TelegramSettingsPage() {
  const [status, setStatus] = useState<TelegramLinkStatusOut | null>(null);
  const [linkInfo, setLinkInfo] = useState<TelegramLinkStartOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.get<TelegramLinkStatusOut>("/me/telegram/status");
      setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được trạng thái");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const startLink = async () => {
    setGenerating(true);
    setError(null);
    try {
      const info = await api.post<TelegramLinkStartOut>("/me/telegram/link", {});
      setLinkInfo(info);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tạo được link");
    } finally {
      setGenerating(false);
    }
  };

  const unlink = async () => {
    if (!confirm("Bỏ liên kết Telegram? Bạn sẽ không nhận notification qua Telegram nữa.")) return;
    setUnlinking(true);
    try {
      await api.delete("/me/telegram/link");
      await load();
      setLinkInfo(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không bỏ link được");
    } finally {
      setUnlinking(false);
    }
  };

  if (loading) return <Spinner label="Đang tải trạng thái Telegram..." />;

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Bot className="h-7 w-7 text-blue-500" />
        <div>
          <h1 className="text-2xl font-bold">Liên kết Telegram</h1>
          <p className="text-sm text-muted-foreground">
            Nhận notification (investigation xong, alert, ...) qua Telegram bot cá nhân
          </p>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}

      <Card>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {status?.linked ? (
              <>
                <CheckCircle2 className="h-5 w-5 text-green-500" />
                <span className="font-semibold text-green-700">Đã liên kết</span>
              </>
            ) : (
              <>
                <XCircle className="h-5 w-5 text-slate-400" />
                <span className="font-semibold text-muted-foreground">Chưa liên kết</span>
              </>
            )}
          </div>

          {status?.linked && (
            <div className="text-sm space-y-1 text-muted-foreground">
              <div>Chat ID: <code className="bg-muted px-1.5 py-0.5 rounded">{status.telegram_chat_id}</code></div>
              {status.linked_at && (
                <div>Liên kết lúc: {new Date(status.linked_at).toLocaleString("vi-VN")}</div>
              )}
            </div>
          )}

          <div className="pt-2">
            {status?.linked ? (
              <Button variant="outline" onClick={unlink} disabled={unlinking}>
                {unlinking && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Bỏ liên kết
              </Button>
            ) : (
              <Button onClick={startLink} disabled={generating}>
                {generating && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                <Bot className="h-4 w-4 mr-2" />
                Tạo liên kết mới
              </Button>
            )}
          </div>
        </div>
      </Card>

      {linkInfo && !status?.linked && (
        <Card>
          <div className="space-y-3">
            <h3 className="font-semibold">Bước tiếp theo</h3>
            <ol className="list-decimal ml-5 space-y-2 text-sm">
              <li>
                Mở Telegram và bấm vào link bên dưới (hoặc copy và dán vào Telegram):
                <div className="mt-2 p-3 bg-blue-50 border border-blue-200 rounded text-xs break-all">
                  <a
                    href={linkInfo.bot_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-700 underline inline-flex items-center gap-1"
                  >
                    {linkInfo.bot_url} <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </li>
              <li>
                Trong Telegram, bấm nút <strong>Start</strong> (hoặc gõ <code>/start</code>).
              </li>
              <li>
                Quay lại trang này và bấm <strong>Tải lại</strong> để xác nhận đã liên kết.
              </li>
            </ol>
            <div className="text-xs text-muted-foreground">
              Link hết hạn lúc: {new Date(linkInfo.expires_at).toLocaleString("vi-VN")} (5 phút).
            </div>
            <Button variant="outline" onClick={load}>
              Tải lại trạng thái
            </Button>
          </div>
        </Card>
      )}

      <Card>
        <h3 className="font-semibold mb-2">Lưu ý</h3>
        <ul className="text-sm space-y-1 list-disc ml-5 text-muted-foreground">
          <li>Notification qua Telegram chỉ gửi khi bạn cũng nhận notification trong app.</li>
          <li>Bot Telegram chưa được cấu hình? Liên hệ Super Admin.</li>
          <li>Bot cần được cấu hình webhook về <code>/api/external/telegram/callback</code> trước khi dùng.</li>
        </ul>
      </Card>
    </div>
  );
}
