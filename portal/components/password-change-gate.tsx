"use client";

import { useState, type FormEvent } from "react";
import { KeyRound, LogOut } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { api } from "@/lib/api";
import { Button, Card, Field, Input } from "@/components/ui";
import { LogoMark } from "@/components/logo";

/**
 * PasswordChangeGate — bắt buộc đổi mật khẩu mặc định sau lần đăng nhập đầu.
 *
 * Render toàn màn hình khi `user.must_change_password` (server đồng thời chặn
 * mọi API khác bằng 403 PASSWORD_CHANGE_REQUIRED). Không thể đóng/bỏ qua —
 * chỉ biến mất sau khi đổi mật khẩu thành công và refresh phiên.
 */
export function PasswordChangeGate() {
  const { user, refresh, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next.length < 8) {
      setError("Mật khẩu mới phải có ít nhất 8 ký tự");
      return;
    }
    if (next === current) {
      setError("Mật khẩu mới phải khác mật khẩu mặc định");
      return;
    }
    if (next !== confirm) {
      setError("Mật khẩu mới và xác nhận không khớp");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // /me giờ trả must_change_password=false → layout tự gỡ gate
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đổi mật khẩu thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-lg bg-brand-600 shadow-lg">
            <LogoMark size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Đổi mật khẩu lần đầu</h1>
          <p className="mt-1 text-sm text-slate-500">
            Tài khoản <span className="font-medium text-slate-700">{user?.email}</span> đang dùng mật
            khẩu mặc định
          </p>
        </div>

        <Card className="shadow-xl">
          <div className="mb-5 flex items-start gap-3 rounded-lg border border-amber-100 bg-amber-50 p-3">
            <KeyRound className="mt-0.5 size-5 shrink-0 text-amber-600" />
            <div className="text-sm text-amber-800">
              <p className="font-semibold">Bắt buộc đổi mật khẩu</p>
              <p className="mt-0.5 text-xs leading-relaxed">
                Vì an toàn hệ thống, bạn phải đặt mật khẩu mới trước khi sử dụng portal. Mật khẩu mới
                có ít nhất 8 ký tự, nên gồm chữ in hoa, số và ký hiệu.
              </p>
            </div>
          </div>

          <form onSubmit={submit}>
            <Field label="Mật khẩu hiện tại (mật khẩu mặc định)" required>
              <Input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoComplete="current-password"
              />
            </Field>
            <Field label="Mật khẩu mới" required>
              <Input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Nhập lại mật khẩu mới" required>
              <Input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
            <Button
              type="submit"
              className="mt-4 w-full"
              loading={busy}
              disabled={!current || !next || !confirm}
            >
              <KeyRound className="size-4" /> Đổi mật khẩu và tiếp tục
            </Button>
            <button
              type="button"
              onClick={() => void logout()}
              className="mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 text-center text-xs text-slate-400 transition-colors hover:text-slate-600"
            >
              <LogOut className="size-3.5" /> Đăng xuất
            </button>
          </form>
        </Card>
      </div>
    </div>
  );
}
