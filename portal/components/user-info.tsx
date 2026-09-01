"use client";

import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Bot, CheckCircle2, ExternalLink, KeyRound, Lock, LogOut, ShieldCheck, UserRound, XCircle } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { ROLE_META } from "@/lib/format";
import { api } from "@/lib/api";
import type { TelegramLinkStartOut, TelegramLinkStatusOut, TotpSetupResponse } from "@/lib/types";
import { Badge, Button, Field, Input, Modal } from "@/components/ui";

type Tab = "profile" | "password" | "twoFactor" | "telegram";

export function UserInfo() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  return <div className="flex items-center gap-2.5">
    <button type="button" onClick={() => setOpen(true)} title="Quản lý tài khoản" className="flex items-center gap-2.5 rounded-lg px-1 py-0.5 transition-colors hover:bg-slate-100">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600">{user.full_name.slice(0, 1).toUpperCase()}</div>
      <div className="hidden min-w-0 leading-tight text-left sm:block"><p className="truncate text-xs font-medium text-slate-900">{user.full_name}</p><p className="truncate text-[11px] text-slate-400">{user.email}</p></div>
    </button>
    <AccountModal open={open} onClose={() => setOpen(false)} />
    <button type="button" onClick={() => void logout()} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Đăng xuất" title="Đăng xuất"><LogOut className="size-4" /></button>
  </div>;
}

function AccountModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth(); const [tab, setTab] = useState<Tab>("profile");
  useEffect(() => { if (open) setTab("profile"); }, [open]);
  if (!user) return null;
  const tabs: Array<[Tab, string, typeof UserRound]> = [["profile", "Thông tin", UserRound], ["password", "Mật khẩu", KeyRound], ["twoFactor", "2FA", ShieldCheck], ["telegram", "Telegram", Bot]];
  return <Modal open={open} onClose={onClose} title="Tài khoản của tôi" wide>
    <div className="mb-5 flex items-center gap-3 rounded-xl bg-slate-50 px-4 py-3"><div className="flex size-10 items-center justify-center rounded-full bg-brand-100 text-base font-semibold text-brand-700">{user.full_name.slice(0, 1).toUpperCase()}</div><div className="min-w-0"><p className="truncate text-sm font-semibold">{user.full_name}</p><p className="truncate text-xs text-slate-500">{user.email}</p></div><Badge className={`ml-auto ${ROLE_META[user.role].badge}`}>{ROLE_META[user.role].label}</Badge></div>
    <div className="grid gap-5 md:grid-cols-[145px_minmax(0,1fr)]"><nav className="flex gap-1 overflow-x-auto md:flex-col" aria-label="Thiết lập tài khoản">{tabs.map(([id, label, Icon]) => <button key={id} type="button" onClick={() => setTab(id)} className={`inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm ${tab === id ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-50"}`}><Icon className="size-4" />{label}</button>)}</nav><section className="min-w-0 border-t border-slate-100 pt-5 md:border-l md:pl-5 md:pt-0">{tab === "profile" && <Profile />}{tab === "password" && <Password />}{tab === "twoFactor" && <TwoFactor />}{tab === "telegram" && <Telegram />}</section></div>
  </Modal>;
}

function Message({ value }: { value: string | null }) { return value ? <p className={`text-sm ${value.startsWith("Đã") ? "text-emerald-600" : "text-rose-600"}`}>{value}</p> : null; }
function Profile() {
  const { user, refresh } = useAuth(); const [name, setName] = useState(user?.full_name ?? ""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState<string | null>(null);
  useEffect(() => setName(user?.full_name ?? ""), [user?.full_name]);
  const save = async () => { setBusy(true); setMessage(null); try { await api.patch("/auth/me", { full_name: name.trim() }); await refresh(); setMessage("Đã cập nhật thông tin."); } catch (e) { setMessage(e instanceof Error ? e.message : "Không thể cập nhật thông tin"); } finally { setBusy(false); } };
  return <div className="space-y-4"><div><h4 className="font-semibold">Thông tin cá nhân</h4><p className="mt-1 text-xs text-slate-500">Email, đơn vị và quyền do Super Admin quản lý.</p></div><Field label="Họ và tên" required><Input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field><Field label="Email"><Input value={user?.email ?? ""} disabled /></Field><Button onClick={() => void save()} loading={busy} disabled={!name.trim()}>Lưu thay đổi</Button><Message value={message} /></div>;
}
function Password() {
  const [current, setCurrent] = useState(""); const [next, setNext] = useState(""); const [confirm, setConfirm] = useState(""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState<string | null>(null);
  const save = async () => { if (next.length < 8) return setMessage("Mật khẩu mới phải có ít nhất 8 ký tự"); if (next !== confirm) return setMessage("Mật khẩu mới và xác nhận không khớp"); setBusy(true); setMessage(null); try { await api.post("/auth/change-password", { current_password: current, new_password: next }); setCurrent(""); setNext(""); setConfirm(""); setMessage("Đã đổi mật khẩu thành công."); } catch (e) { setMessage(e instanceof Error ? e.message : "Đổi mật khẩu thất bại"); } finally { setBusy(false); } };
  return <div className="space-y-4"><div><h4 className="font-semibold">Đổi mật khẩu</h4><p className="mt-1 text-xs text-slate-500">Mật khẩu mới có ít nhất 8 ký tự.</p></div><Field label="Mật khẩu hiện tại" required><Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field><Field label="Mật khẩu mới" required><Input type="password" value={next} onChange={(e) => setNext(e.target.value)} /></Field><Field label="Nhập lại mật khẩu mới" required><Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field><Button onClick={() => void save()} loading={busy} disabled={!current || !confirm}>Đổi mật khẩu</Button><Message value={message} /></div>;
}
function TwoFactor() {
  const { user, refresh } = useAuth(); const [setup, setSetup] = useState<TotpSetupResponse | null>(null); const [code, setCode] = useState(""); const [password, setPassword] = useState(""); const [disableOpen, setDisableOpen] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const start = async () => { setBusy(true); setError(null); try { const r = await fetch("/api/auth/totp/setup", { method: "POST" }); const d = await r.json() as TotpSetupResponse & { detail?: string }; if (!r.ok) throw new Error(d.detail); setSetup(d); } catch (e) { setError(e instanceof Error ? e.message : "Không tạo được 2FA"); } finally { setBusy(false); } };
  const confirm = async () => { setBusy(true); setError(null); try { const r = await fetch("/api/auth/totp/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) }); const d = await r.json() as { detail?: string }; if (!r.ok) throw new Error(d.detail); setSetup(null); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : "Mã xác nhận không đúng"); } finally { setBusy(false); } };
  const disable = async () => { setBusy(true); setError(null); try { await api.post("/auth/totp/disable", { current_password: password }); setPassword(""); setDisableOpen(false); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : "Không thể tắt 2FA"); } finally { setBusy(false); } };
  return <div className="space-y-4"><div><h4 className="font-semibold">Xác thực hai yếu tố</h4><p className="mt-1 text-xs text-slate-500">Dùng Google Authenticator, Authy hoặc Microsoft Authenticator.</p></div><div className="rounded-xl border border-slate-200 p-4"><div className="flex items-center gap-2 text-sm font-medium">{user?.is_2fa_enabled ? <CheckCircle2 className="size-5 text-emerald-600" /> : <XCircle className="size-5 text-slate-400" />}{user?.is_2fa_enabled ? "2FA đang được bật" : "2FA chưa được bật"}</div>{user?.is_2fa_enabled ? <Button className="mt-3" variant="outline" size="sm" onClick={() => setDisableOpen(!disableOpen)}><Lock className="size-3.5" />Tắt 2FA</Button> : <Button className="mt-3" size="sm" onClick={() => void start()} loading={busy}><KeyRound className="size-3.5" />Bật 2FA</Button>}</div>{disableOpen && <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">Nhập mật khẩu hiện tại để tắt 2FA.</p><Field label="Mật khẩu hiện tại" required><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field><Button variant="danger" size="sm" onClick={() => void disable()} loading={busy} disabled={!password}>Xác nhận tắt 2FA</Button></div>}{setup && <div className="space-y-4 rounded-xl border border-slate-200 p-4"><p className="text-sm font-medium">Quét mã QR rồi nhập mã 6 số để xác nhận</p><div className="flex justify-center rounded-xl bg-white p-3"><QRCodeSVG value={setup.uri} size={180} level="M" /></div><p className="break-all rounded-lg bg-slate-50 p-2 font-mono text-xs">{setup.secret}</p><p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">Backup codes: {setup.backup_codes.join(" · ")}</p><Field label="Mã 6 số" required><Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" placeholder="000000" /></Field><Button onClick={() => void confirm()} loading={busy} disabled={code.length !== 6}>Xác nhận và kích hoạt</Button></div>}<Message value={error} /></div>;
}
function Telegram() {
  const [status, setStatus] = useState<TelegramLinkStatusOut | null>(null); const [link, setLink] = useState<TelegramLinkStartOut | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const load = async () => { try { setStatus(await api.get<TelegramLinkStatusOut>("/me/telegram/status")); } catch (e) { setError(e instanceof Error ? e.message : "Không tải được trạng thái Telegram"); } }; useEffect(() => { void load(); }, []);
  const action = async () => { setBusy(true); setError(null); try { if (status?.linked) { await api.delete("/me/telegram/link"); setLink(null); await load(); } else setLink(await api.post<TelegramLinkStartOut>("/me/telegram/link", {})); } catch (e) { setError(e instanceof Error ? e.message : "Không thể cập nhật liên kết"); } finally { setBusy(false); } };
  return <div className="space-y-4"><div><h4 className="font-semibold">Liên kết Telegram</h4><p className="mt-1 text-xs text-slate-500">Nhận thông báo từ bot trên tài khoản Telegram cá nhân.</p></div><div className="rounded-xl border border-slate-200 p-4"><div className="flex items-center gap-2 text-sm font-medium">{status?.linked ? <CheckCircle2 className="size-5 text-emerald-600" /> : <XCircle className="size-5 text-slate-400" />}{status?.linked ? "Đã liên kết" : "Chưa liên kết"}</div><Button className="mt-3" variant={status?.linked ? "outline" : "primary"} size="sm" onClick={() => void action()} loading={busy}>{status?.linked ? "Bỏ liên kết" : "Tạo liên kết mới"}</Button></div>{link && !status?.linked && <div className="rounded-xl bg-blue-50 p-4 text-sm text-blue-950"><p className="font-medium">Mở Telegram và bấm Start</p><a className="mt-2 inline-flex break-all text-xs text-blue-700 underline" href={link.bot_url} target="_blank" rel="noopener noreferrer">{link.bot_url}<ExternalLink className="ml-1 size-3.5 shrink-0" /></a><p className="mt-2 text-xs">Link hết hạn lúc {new Date(link.expires_at).toLocaleString("vi-VN")}.</p><Button className="mt-3" size="sm" variant="outline" onClick={() => void load()}>Tải lại trạng thái</Button></div>}<Message value={error} /></div>;
}
