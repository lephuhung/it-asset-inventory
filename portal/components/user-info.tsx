"use client";

import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import {
  Bot,
  CheckCircle2,
  ExternalLink,
  KeyRound,
  Lock,
  LogOut,
  ShieldCheck,
  UserRound,
  XCircle,
  ChevronDown,
} from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { ROLE_META } from "@/lib/format";
import { api } from "@/lib/api";
import type {
  TelegramLinkStartOut,
  TelegramLinkStatusOut,
  TotpSetupResponse,
} from "@/lib/types";
import { Badge, Button, Field, Input, Modal } from "@/components/ui";

type Tab = "profile" | "password" | "twoFactor" | "telegram";

/**
 * Header user button + Account modal.
 * Theo Design.md:
 *  - Nút mở modal = surface trắng, hairline, avatar tròn (rounded.full), pill nhẹ
 *  - Modal = ex-modal-card (surface trắng + rounded.xl + shadow Level-2)
 *  - Một accent duy nhất (brand-600) cho active tab indicator & nút CTA
 *  - Sticker palette (violet/sky/amber/emerald) chỉ dùng cho avatar tile & status pill
 */
export function UserInfo() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  const initial = user.full_name.slice(0, 1).toUpperCase();
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Quản lý tài khoản"
        aria-label="Quản lý tài khoản"
        aria-haspopup="dialog"
        className="group flex items-center gap-2.5 rounded-full border border-slate-200 bg-white py-1 pl-1 pr-3 transition-all duration-150 hover:border-slate-300 hover:bg-slate-50 hover:shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-violet-100 text-[13px] font-semibold tracking-tight text-violet-700">
          {initial}
        </span>
        <span className="hidden min-w-0 text-left leading-tight sm:block">
          <span className="block truncate text-[13px] font-semibold tracking-tight text-slate-900">
            {user.full_name}
          </span>
          <span className="block truncate text-[11px] text-slate-500">{user.email}</span>
        </span>
        <ChevronDown
          className="hidden size-3.5 shrink-0 text-slate-400 transition-transform duration-150 group-hover:text-slate-600 sm:block"
          aria-hidden
        />
      </button>
      <button
        type="button"
        onClick={() => void logout()}
        className="flex size-9 items-center justify-center rounded-full text-slate-400 transition-colors duration-150 hover:bg-slate-100 hover:text-rose-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
        aria-label="Đăng xuất"
        title="Đăng xuất"
      >
        <LogOut className="size-4" />
      </button>
      <AccountModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function AccountModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("profile");
  useEffect(() => {
    if (open) setTab("profile");
  }, [open]);
  if (!user) return null;

  const tabs: Array<[Tab, string, typeof UserRound]> = [
    ["profile", "Thông tin", UserRound],
    ["password", "Mật khẩu", KeyRound],
    ["twoFactor", "2FA", ShieldCheck],
    ["telegram", "Telegram", Bot],
  ];

  return (
    <Modal open={open} onClose={onClose} title="Tài khoản của tôi" wide>
      {/* Tab layout — sidebar dọc (md+) / ngang mobile.
          Header strip đã bỏ — avatar/tên/email/role được dồn vào tab "Thông tin"
          làm đầu trang gọn gàng (Design.md: figure/ground dựa trên hairline, không cần
          surface nhẹ trên surface trắng). */}
      <div className="grid gap-5 md:grid-cols-[152px_minmax(0,1fr)]">
        <nav
          className="-mx-1 flex gap-1 overflow-x-auto px-1 md:flex-col md:gap-0.5 md:overflow-visible md:px-0"
          aria-label="Thiết lập tài khoản"
        >
          {tabs.map(([id, label, Icon]) => {
            const active = tab === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                aria-current={active ? "page" : undefined}
                className={`inline-flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 ${
                  active
                    ? "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-100"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                <Icon
                  className={`size-4 shrink-0 ${active ? "text-brand-600" : "text-slate-400"}`}
                  aria-hidden
                />
                {label}
              </button>
            );
          })}
        </nav>
        <section className="min-w-0 border-t border-slate-100 pt-5 md:border-l md:border-t-0 md:pl-5 md:pt-0">
          {tab === "profile" && <Profile />}
          {tab === "password" && <Password />}
          {tab === "twoFactor" && <TwoFactor />}
          {tab === "telegram" && <Telegram />}
        </section>
      </div>
    </Modal>
  );
}

function Message({ value }: { value: string | null }) {
  return value ? (
    <p
      role="status"
      className={`text-sm font-medium ${value.startsWith("Đã") ? "text-emerald-700" : "text-rose-600"}`}
    >
      {value}
    </p>
  ) : null;
}

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h4 className="text-[15px] font-bold tracking-tight text-slate-900">{title}</h4>
      <p className="mt-1 text-xs leading-snug text-slate-500">{description}</p>
    </div>
  );
}

function Profile() {
  const { user, refresh } = useAuth();
  const [name, setName] = useState(user?.full_name ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => setName(user?.full_name ?? ""), [user?.full_name]);
  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await api.patch("/auth/me", { full_name: name.trim() });
      await refresh();
      setMessage("Đã cập nhật thông tin.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Không thể cập nhật thông tin");
    } finally {
      setBusy(false);
    }
  };
  if (!user) return null;
  const initial = user.full_name.slice(0, 1).toUpperCase();
  return (
    <div className="space-y-5">
      {/* Identity block — gọn 1 hàng: avatar sticker tile + tên + email + role pill */}
      <div className="flex items-center gap-3">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-full bg-violet-100 text-lg font-semibold tracking-tight text-violet-700">
          {initial}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <p className="truncate text-[15px] font-bold tracking-tight text-slate-900">
              {user.full_name}
            </p>
            <Badge className={ROLE_META[user.role].badge}>
              {ROLE_META[user.role].label}
            </Badge>
          </div>
          <p className="truncate text-xs text-slate-500">{user.email}</p>
        </div>
      </div>

      <div className="h-px bg-slate-100" aria-hidden />

      <div>
        <h4 className="text-[15px] font-bold tracking-tight text-slate-900">
          Thông tin cá nhân
        </h4>
        <p className="mt-1 text-xs leading-snug text-slate-500">
          Email, đơn vị và quyền do Super Admin quản lý.
        </p>
      </div>

      <Field label="Họ và tên" required>
        <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Email">
        <Input value={user?.email ?? ""} disabled />
      </Field>
      <div className="flex items-center gap-3 pt-1">
        <Button onClick={() => void save()} loading={busy} disabled={!name.trim()}>
          Lưu thay đổi
        </Button>
        <Message value={message} />
      </div>
    </div>
  );
}

function Password() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const save = async () => {
    if (next.length < 8) return setMessage("Mật khẩu mới phải có ít nhất 8 ký tự");
    if (next !== confirm) return setMessage("Mật khẩu mới và xác nhận không khớp");
    setBusy(true);
    setMessage(null);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      setMessage("Đã đổi mật khẩu thành công.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Đổi mật khẩu thất bại");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4">
      <SectionHeader
        title="Đổi mật khẩu"
        description="Mật khẩu mới có ít nhất 8 ký tự. Dùng ký tự in hoa, số và ký hiệu để an toàn hơn."
      />
      <Field label="Mật khẩu hiện tại" required>
        <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </Field>
      <Field label="Mật khẩu mới" required>
        <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
      </Field>
      <Field label="Nhập lại mật khẩu mới" required>
        <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <div className="flex items-center gap-3 pt-1">
        <Button onClick={() => void save()} loading={busy} disabled={!current || !confirm}>
          Đổi mật khẩu
        </Button>
        <Message value={message} />
      </div>
    </div>
  );
}

function TwoFactor() {
  const { user, refresh } = useAuth();
  const [setup, setSetup] = useState<TotpSetupResponse | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [disableOpen, setDisableOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/auth/totp/setup", { method: "POST" });
      const d = (await r.json()) as TotpSetupResponse & { detail?: string };
      if (!r.ok) throw new Error(d.detail);
      setSetup(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tạo được 2FA");
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/auth/totp/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const d = (await r.json()) as { detail?: string };
      if (!r.ok) throw new Error(d.detail);
      setSetup(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Mã xác nhận không đúng");
    } finally {
      setBusy(false);
    }
  };
  const disable = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/totp/disable", { current_password: password });
      setPassword("");
      setDisableOpen(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể tắt 2FA");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader
        title="Xác thực hai yếu tố"
        description="Dùng Google Authenticator, Authy hoặc Microsoft Authenticator."
      />

      {/* Trạng thái 2FA — status row kiểu Notion (icon tile + nhãn) */}
      <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={`flex size-9 shrink-0 items-center justify-center rounded-full ${
              user?.is_2fa_enabled
                ? "bg-emerald-100 text-emerald-700"
                : "bg-slate-100 text-slate-400"
            }`}
          >
            {user?.is_2fa_enabled ? (
              <CheckCircle2 className="size-5" />
            ) : (
              <XCircle className="size-5" />
            )}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold tracking-tight text-slate-900">
              {user?.is_2fa_enabled ? "2FA đang được bật" : "2FA chưa được bật"}
            </p>
            <p className="text-xs text-slate-500">
              {user?.is_2fa_enabled
                ? "Tài khoản được bảo vệ bởi mã TOTP 6 số."
                : "Bật 2FA để thêm một lớp bảo mật cho đăng nhập."}
            </p>
          </div>
        </div>
        {user?.is_2fa_enabled ? (
          <Button variant="outline" size="sm" onClick={() => setDisableOpen(!disableOpen)}>
            <Lock className="size-3.5" />
            Tắt 2FA
          </Button>
        ) : (
          <Button size="sm" onClick={() => void start()} loading={busy}>
            <KeyRound className="size-3.5" />
            Bật 2FA
          </Button>
        )}
      </div>

      {/* Disable confirm — dùng tone amber (sticker palette, không phải brand) */}
      {disableOpen && (
        <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium text-amber-900">
            Nhập mật khẩu hiện tại để tắt 2FA.
          </p>
          <Field label="Mật khẩu hiện tại" required>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Button
            variant="danger"
            size="sm"
            onClick={() => void disable()}
            loading={busy}
            disabled={!password}
          >
            Xác nhận tắt 2FA
          </Button>
        </div>
      )}

      {/* Setup wizard */}
      {setup && (
        <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-sm font-semibold tracking-tight text-slate-900">
            Quét mã QR rồi nhập mã 6 số để xác nhận
          </p>
          <div className="flex justify-center rounded-lg border border-slate-200 bg-white p-3">
            <QRCodeSVG value={setup.uri} size={180} level="M" />
          </div>
          <p className="break-all rounded-md bg-slate-50 p-2 font-mono text-[11px] text-slate-700">
            {setup.secret}
          </p>
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <p className="font-semibold">Backup codes</p>
            <p className="mt-1 break-all font-mono text-[11px]">
              {setup.backup_codes.join(" · ")}
            </p>
          </div>
          <Field label="Mã 6 số" required>
            <Input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              placeholder="000000"
            />
          </Field>
          <div className="flex items-center gap-3">
            <Button onClick={() => void confirm()} loading={busy} disabled={code.length !== 6}>
              Xác nhận
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSetup(null)}>
              Hủy
            </Button>
          </div>
        </div>
      )}

      <Message value={error} />
    </div>
  );
}

function Telegram() {
  const [status, setStatus] = useState<TelegramLinkStatusOut | null>(null);
  const [link, setLink] = useState<TelegramLinkStartOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setStatus(await api.get<TelegramLinkStatusOut>("/me/telegram/status"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được trạng thái Telegram");
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const action = async () => {
    setBusy(true);
    setError(null);
    try {
      if (status?.linked) {
        await api.delete("/me/telegram/link");
        setLink(null);
        await load();
      } else {
        setLink(await api.post<TelegramLinkStartOut>("/me/telegram/link", {}));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể cập nhật liên kết");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader
        title="Liên kết Telegram"
        description="Nhận thông báo từ bot trên tài khoản Telegram cá nhân."
      />

      {/* Trạng thái liên kết — sticker sky khi OK, slate khi chưa */}
      <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={`flex size-9 shrink-0 items-center justify-center rounded-full ${
              status?.linked
                ? "bg-sky-100 text-sky-700"
                : "bg-slate-100 text-slate-400"
            }`}
          >
            <Bot className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold tracking-tight text-slate-900">
              {status?.linked ? "Đã liên kết" : "Chưa liên kết"}
            </p>
            <p className="text-xs text-slate-500">
              {status?.linked
                ? "Bot sẽ gửi thông báo về Telegram cá nhân."
                : "Tạo liên kết để nhận thông báo qua Telegram."}
            </p>
          </div>
        </div>
        <Button
          variant={status?.linked ? "outline" : "primary"}
          size="sm"
          onClick={() => void action()}
          loading={busy}
        >
          {status?.linked ? "Bỏ liên kết" : "Tạo liên kết mới"}
        </Button>
      </div>

      {/* Link start info — dùng tone brand-50 (màu hành động duy nhất) cho inline link */}
      {link && !status?.linked && (
        <div className="rounded-lg border border-brand-100 bg-brand-50 p-4 text-sm text-brand-900">
          <p className="font-semibold tracking-tight">Mở Telegram và bấm Start</p>
          <a
            className="mt-2 inline-flex items-center break-all text-xs text-brand-700 underline underline-offset-2 hover:text-brand-800"
            href={link.bot_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {link.bot_url}
            <ExternalLink className="ml-1 size-3.5 shrink-0" />
          </a>
          <p className="mt-2 text-xs text-slate-500">
            Link hết hạn lúc {new Date(link.expires_at).toLocaleString("vi-VN")}.
          </p>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => void load()}>
            Tải lại trạng thái
          </Button>
        </div>
      )}

      <Message value={error} />
    </div>
  );
}
