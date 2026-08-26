"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { KeyRound, Monitor, ShieldCheck } from "lucide-react";
import type { LoginResponse } from "@/lib/types";
import { Button, Card, Field, Input } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [requires2fa, setRequires2fa] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Đã đăng nhập → vào thẳng
    void fetch("/api/auth/session", { cache: "no-store" })
      .then((r) => (r.ok ? router.replace("/dashboard") : undefined))
      .catch(() => undefined);
  }, [router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          totp_code: requires2fa ? totpCode : undefined,
        }),
      });
      const data = (await res.json()) as LoginResponse & { detail?: string };
      if (!res.ok) {
        if (res.status === 401) {
          setError("Sai email hoặc mật khẩu" + (requires2fa ? " / mã 2FA không đúng" : ""));
        } else if (res.status === 429) {
          setError("Quá nhiều lần thử — vui lòng chờ 1 phút");
        } else {
          setError(data.detail ?? "Lỗi đăng nhập");
        }
        return;
      }
      if (data.requires_2fa) {
        setRequires2fa(true);
        return;
      }
      router.replace(next);
    } catch {
      setError("Không kết nối được máy chủ");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-2xl bg-[#635a5a] shadow-lg shadow-[#635a5a]/25">
            <Monitor className="size-7 text-white" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Asset Inventory</h1>
          <p className="mt-1 text-sm text-slate-500">
            Hệ thống quản lý tài sản máy tính — Portal quản trị
          </p>
        </div>

        <Card className="shadow-[0_8px_30px_rgba(15,23,42,0.08)]">
          {requires2fa ? (
            <>
              <div className="mb-5 flex items-start gap-3 rounded-lg border border-[#e8e8e8] bg-[#f5f5f5] p-3">
                <ShieldCheck className="mt-0.5 size-5 shrink-0 text-[#635a5a]" />
                <div className="text-sm text-[#3b3636]">
                  <p className="font-semibold">Xác thực 2 yếu tố (TOTP)</p>
                  <p className="mt-0.5 text-xs leading-relaxed">
                    Nhập mã 6 số từ ứng dụng xác thực (Google Authenticator / Authy / Microsoft
                    Authenticator).
                  </p>
                </div>
              </div>
              <form onSubmit={submit}>
                <Field label="Mã TOTP" required>
                  <Input
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="000000"
                    className="text-center text-lg tracking-[0.5em]"
                  />
                </Field>
                {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
                <Button type="submit" className="mt-4 w-full" loading={loading} disabled={totpCode.length !== 6}>
                  Xác thực
                </Button>
                <button
                  type="button"
                  onClick={() => setRequires2fa(false)}
                  className="mt-3 w-full text-center text-xs text-slate-400 transition-colors hover:text-slate-600"
                >
                  ← Đổi thông tin đăng nhập
                </button>
              </form>
            </>
          ) : (
            <form onSubmit={submit}>
              <div className="mb-5 flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <KeyRound className="mt-0.5 size-5 shrink-0 text-slate-400" />
                <p className="text-xs leading-relaxed text-slate-500">
                  Quản trị viên sử dụng tài khoản do server cấu hình (xem{" "}
                  <code className="rounded bg-slate-200 px-1 py-0.5 text-slate-600">SEED_ADMIN_EMAIL</code> trong file{" "}
                  <code className="rounded bg-slate-200 px-1 py-0.5 text-slate-600">.env</code> của backend).
                </p>
              </div>
              <Field label="Email" required>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="username"
                  placeholder="admin@example.gov.vn"
                  required
                />
              </Field>
              <Field label="Mật khẩu" required className="mt-4">
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  required
                />
              </Field>
              {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
              <Button type="submit" className="mt-5 w-full" loading={loading} disabled={!email || !password}>
                Đăng nhập
              </Button>
            </form>
          )}
        </Card>

        <p className="mt-6 text-center text-xs text-slate-400">
          Đăng nhập ghi vào audit log kèm IP. Truy cập giới hạn theo vai trò (RBAC).
        </p>
        <p className="mt-1.5 text-center text-[11px] text-slate-300">
          Agent read-only · không giám sát cá nhân (mục 6.6)
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
