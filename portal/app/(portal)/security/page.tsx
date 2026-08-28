"use client";

import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Check, Copy, KeyRound, Lock, ShieldCheck, Smartphone } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import type { TotpSetupResponse } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  PageHeader,
} from "@/components/ui";

function CopyText({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      className="inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
      onClick={() => void copy()}
    >
      {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
      {copied ? "Đã copy" : label}
    </button>
  );
}

export default function SecurityPage() {
  const { user, refresh } = useAuth();
  const [setup, setSetup] = useState<TotpSetupResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmCode, setConfirmCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(false);

  const startSetup = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/totp/setup", { method: "POST" });
      const data = (await res.json()) as TotpSetupResponse & { detail?: string };
      if (!res.ok) {
        setError(data.detail ?? "Không tạo được 2FA");
        return;
      }
      setSetup(data);
    } catch {
      setError("Không kết nối được máy chủ");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/totp/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: confirmCode }),
      });
      const data = (await res.json()) as { detail?: string };
      if (!res.ok) {
        setError(data.detail ?? "Mã xác nhận không đúng");
        return;
      }
      setSetup(null);
      setConfirmCode("");
      setEnabled(true);
      await refresh();
    } catch {
      setError("Không kết nối được máy chủ");
    } finally {
      setBusy(false);
    }
  };

  const isOn = user?.is_2fa_enabled || enabled;

  return (
    <div>
      <PageHeader
        title="Bảo mật tài khoản"
        description="Xác thực 2 yếu tố TOTP (RFC 6238) — bắt buộc với Admin toàn cục và Admin cơ quan (mục 5.3)"
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Trạng thái 2FA">
          <div className="flex items-start gap-3">
            <span
              className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${
                isOn ? "bg-emerald-50" : "bg-slate-100"
              }`}
            >
              <ShieldCheck className={`size-5 ${isOn ? "text-emerald-600" : "text-slate-400"}`} />
            </span>
            <div>
              <p className="text-sm text-slate-700">
                {isOn ? (
                  <>Tài khoản đã bật xác thực 2 yếu tố.</>
                ) : (
                  <>Tài khoản chưa bật 2FA — nên bật ngay vì vai trò hiện tại sinh token và xem dữ liệu nhạy cảm.</>
                )}
              </p>
              {isOn ? (
                <Badge className="mt-2 bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                  <Check className="size-3.5" /> Đã bật
                </Badge>
              ) : (
                <Button className="mt-4" onClick={() => void startSetup()} loading={busy}>
                  <KeyRound className="size-4" /> Bật xác thực 2 yếu tố
                </Button>
              )}
            </div>
          </div>
          <div className="mt-5 space-y-2 border-t border-slate-100 pt-4 text-xs text-slate-500">
            <p className="flex items-center gap-1.5">
              <Smartphone className="size-3.5" /> Hoạt động với Google Authenticator / Authy /
              Microsoft Authenticator.
            </p>
            <p className="flex items-center gap-1.5">
              <Lock className="size-3.5" /> Nhập sai N lần sẽ khóa tạm thời; seed mã hóa AES-256-GCM
              khi lưu; mọi đăng nhập ghi audit log.
            </p>
          </div>
        </Card>

        {setup && (
          <Card title="Bước 1 — Quét mã QR" subtitle="Mở app xác thực và quét mã dưới đây">
            <div className="flex flex-col items-center gap-4">
              <div className="rounded-2xl border border-slate-200 bg-white p-4">
                <QRCodeSVG value={setup.uri} size={200} level="M" />
              </div>
              <div className="w-full rounded-lg bg-slate-50 px-3 py-2.5">
                <p className="mb-1 text-xs font-medium text-slate-500">Hoặc nhập secret thủ công</p>
                <div className="flex items-center justify-between gap-2">
                  <code className="break-all font-mono text-xs text-slate-700">{setup.secret}</code>
                  <CopyText text={setup.secret} label="Copy" />
                </div>
              </div>
              <div className="w-full rounded-lg bg-amber-50 px-3 py-2.5">
                <p className="mb-1.5 text-xs font-semibold text-amber-800">
                  Backup codes (dùng 1 lần — lưu cẩn thận!)
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {(setup.backup_codes ?? []).map((c, i) => (
                    <code key={i} className="rounded bg-white px-1.5 py-0.5 font-mono text-[11px] text-amber-900 ring-1 ring-inset ring-amber-200">
                      {c}
                    </code>
                  ))}
                </div>
                <div className="mt-2">
                  <CopyText text={setup.backup_codes.join("\n")} label="Copy toàn bộ backup codes" />
                </div>
              </div>
              <Field label="Bước 2 — Nhập mã 6 số từ app để xác nhận" required className="w-full">
                <Input
                  value={confirmCode}
                  onChange={(e) => setConfirmCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  inputMode="numeric"
                  placeholder="000000"
                  className="text-center text-lg tracking-[0.5em]"
                />
              </Field>
              {error && <p className="w-full text-sm text-rose-600">{error}</p>}
              <Button className="w-full" onClick={() => void confirm()} loading={busy} disabled={confirmCode.length !== 6}>
                Xác nhận và kích hoạt
              </Button>
            </div>
          </Card>
        )}

        {!setup && error && <p className="text-sm text-rose-600">{error}</p>}

        <Card title="Bảo vệ dữ liệu cá nhân" subtitle="Theo mục 7.3 & Nghị định 13/2023/NĐ-CP">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-600">
            <li>Số điện thoại nhập tại token được mã hóa <b>AES-256-GCM</b>, UI/export mask mặc định.</li>
            <li>Quyền giải mã chỉ ở endpoint có phân quyền; khóa nằm trong Vault/KMS.</li>
            <li>Thông báo tuân thủ liệt kê đúng trường dữ liệu, mục đích, thời hạn lưu trữ.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}