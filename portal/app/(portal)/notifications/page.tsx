"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  Check,
  ExternalLink,
  Loader2,
  Plus,
  SendHorizontal,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, IconButton, Input, Modal, PageHeader, Select, Textarea } from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import {
  SEVERITY_BADGES,
  useNotifications,
} from "@/components/notification-bell";
import type { NotificationOut } from "@/lib/types";

const SEVERITY_OPTIONS = [
  { value: "info", label: "Info" },
  { value: "success", label: "Success" },
  { value: "warning", label: "Warning" },
  { value: "error", label: "Error" },
  { value: "critical", label: "Critical" },
];

const CATEGORY_OPTIONS = [
  { value: "message", label: "Tin nhắn" },
  { value: "investigation", label: "Điều tra" },
  { value: "alert", label: "Cảnh báo" },
  { value: "system", label: "Hệ thống" },
  { value: "machine", label: "Máy" },
  { value: "security", label: "Bảo mật" },
];

const RECIPIENT_OPTIONS = [
  { value: "admins", label: "Tất cả Admin (Super + Org)" },
  { value: "super", label: "Chỉ Super Admin" },
  { value: "org_admins", label: "Admin tổ chức (Org Admin)" },
  { value: "broadcast", label: "Toàn hệ thống (mọi người dùng)" },
];

export default function NotificationsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";
  const { notifications, unreadCount, refresh, markAllRead, markRead, deleteOne } = useNotifications();
  const [filter, setFilter] = useState<"all" | "unread">("all");

  // Compose modal
  const [composeOpen, setComposeOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("info");
  const [category, setCategory] = useState("message");
  const [body, setBody] = useState("");
  const [link, setLink] = useState("");
  const [recipient, setRecipient] = useState("admins");
  const [sending, setSending] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composeDone, setComposeDone] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const openCompose = () => {
    setTitle("");
    setSeverity("info");
    setCategory("message");
    setBody("");
    setLink("");
    setRecipient("admins");
    setComposeError(null);
    setComposeDone(null);
    setComposeOpen(true);
  };

  const sendNotification = async () => {
    if (!title.trim()) {
      setComposeError("Nhập tiêu đề thông báo");
      return;
    }
    setSending(true);
    setComposeError(null);
    setComposeDone(null);
    try {
      const payload = {
        title: title.trim(),
        severity,
        category,
        body: body.trim() || null,
        link: link.trim() || null,
      };
      let res: { delivered_to: number };
      if (recipient === "broadcast") {
        res = await api.post<{ delivered_to: number }>("/admin/notifications/broadcast", payload);
      } else {
        const role = recipient === "admins" ? "admin" : recipient === "super" ? "super_admin" : "org_admin";
        res = await api.post<{ delivered_to: number }>("/admin/notifications", {
          recipient_filter: { role },
          ...payload,
        });
      }
      setComposeDone(`Đã gửi tới ${res.delivered_to} người nhận.`);
      setTitle("");
      setBody("");
      setLink("");
      // Đóng modal ngay sau khi gửi thành công — để danh sách phía sau thao tác
      // được bình thường (trước đây modal vẫn mở nên click nút xóa trên row
      // bị backdrop nuốt → chỉ đóng modal chứ không xóa).
      setComposeOpen(false);
      void refresh();
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : "Gửi thất bại");
    } finally {
      setSending(false);
    }
  };

  // Tự ẩn banner "đã gửi" sau 6s
  useEffect(() => {
    if (!composeDone) return;
    const t = setTimeout(() => setComposeDone(null), 6000);
    return () => clearTimeout(t);
  }, [composeDone]);

  const visible = filter === "unread" ? notifications.filter((n) => !n.read_at) : notifications;

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Thông báo"
        description={
          unreadCount > 0
            ? `${unreadCount} thông báo chưa đọc`
            : "Đã đọc tất cả thông báo"
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {isSuperAdmin && (
              <Button size="sm" onClick={openCompose}>
                <Plus className="size-3.5" /> Tạo thông báo
              </Button>
            )}
            <Button
              variant={filter === "all" ? "primary" : "outline"}
              size="sm"
              onClick={() => setFilter("all")}
            >
              Tất cả ({notifications.length})
            </Button>
            <Button
              variant={filter === "unread" ? "primary" : "outline"}
              size="sm"
              onClick={() => setFilter("unread")}
            >
              Chưa đọc ({unreadCount})
            </Button>
            {unreadCount > 0 && (
              <Button variant="outline" size="sm" onClick={() => void markAllRead()}>
                <Check className="size-3.5" /> Đánh dấu tất cả
              </Button>
            )}
          </div>
        }
      />

      {composeDone && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" />
          {composeDone}
        </div>
      )}

      {visible.length === 0 ? (
        <EmptyState
          icon={<Bell className="size-8" />}
          title="Chưa có thông báo nào"
          description="Notification sẽ xuất hiện ở đây khi có sự kiện: investigation xong, máy offline, alert security..."
        />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {visible.map((n) => (
            <NotificationRow
              key={n.id}
              n={n}
              onOpen={() => {
                if (!n.read_at) void markRead(n.id);
                if (n.link) router.push(n.link);
              }}
              onDelete={() => void deleteOne(n.id)}
            />
          ))}
        </ul>
      )}

      {/* Modal tạo / push notification */}
      <Modal
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        title="Gửi thông báo tới Admin"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setComposeOpen(false)} disabled={sending}>
              Hủy
            </Button>
            <Button onClick={sendNotification} disabled={sending || !title.trim()}>
              {sending ? <Loader2 className="size-3.5 animate-spin" /> : <SendHorizontal className="size-3.5" />}
              Gửi thông báo
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {composeError && <ErrorBanner message={composeError} />}

          <Field label="Đối tượng nhận" hint="Admin gửi — chọn nhóm người nhận. Người gửi không nhận được thông báo của chính mình.">
            <Select value={recipient} onChange={(e) => setRecipient(e.target.value)}>
              {RECIPIENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Tiêu đề" required>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="VD: Bảo trì hệ thống đêm nay 22:00–23:00"
              maxLength={200}
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Mức độ">
              <Select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                {SEVERITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Loại">
              <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="Nội dung" hint="Hiển thị trong dropdown chuông thông báo và trang này.">
            <Textarea
              rows={3}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Chi tiết thông báo…"
            />
          </Field>

          <Field label="Link (tùy chọn)" hint="VD /machines hoặc /admin/llm-dfir/investigations — bấm thông báo sẽ chuyển tới đó.">
            <Input
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="/dashboard"
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

function NotificationRow({
  n,
  onOpen,
  onDelete,
}: {
  n: NotificationOut;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const sev = (n.severity || "info").toLowerCase();
  const unread = !n.read_at;
  return (
    <li className="min-w-0">
      <Card
        className={`h-full transition-colors duration-150 motion-reduce:transition-none hover:border-slate-300 ${
          unread ? "bg-brand-50/40!" : ""
        }`}
      >
        <div className="flex items-start gap-3">
          <button onClick={onOpen} className="min-w-0 flex-1 cursor-pointer text-left">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Badge className={SEVERITY_BADGES[sev] ?? SEVERITY_BADGES.info}>{sev}</Badge>
              <span className="text-xs text-slate-500">{n.category}</span>
              {n.source && n.source !== "user" && (
                <span className="text-xs text-slate-400">via {n.source}</span>
              )}
              {unread && <span className="size-1.5 rounded-full bg-brand-600" aria-label="Chưa đọc" />}
            </div>
            <div
              className={`text-sm ${
                unread ? "font-semibold text-slate-900" : "font-medium text-slate-700"
              }`}
            >
              {n.title}
            </div>
            {n.body && (
              <div className="mt-1 line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-500">
                {n.body}
              </div>
            )}
            <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-400">
              <span>{new Date(n.created_at).toLocaleString("vi-VN")}</span>
              {n.link && (
                <span className="inline-flex items-center gap-0.5 font-medium text-brand-600">
                  <ExternalLink className="size-3" /> có link
                </span>
              )}
            </div>
          </button>
          <IconButton
            label="Xoá thông báo"
            onClick={onDelete}
            className="shrink-0 hover:bg-rose-50 hover:text-rose-600"
          >
            <Trash2 className="size-4" />
          </IconButton>
        </div>
      </Card>
    </li>
  );
}
