"use client";

import { useEffect, useRef, useState } from "react";
import { KeyRound, LogOut } from "lucide-react";
import { useAuth } from "@/components/auth-context";
import { ROLE_META } from "@/lib/format";
import { api } from "@/lib/api";
import { Badge, Button, Field, Input, Modal } from "@/components/ui";

/** Khối thông tin quản trị viên hiển thị ở góc trên phải màn hình.
 *  Click vào avatar/tên → dropdown gồm "Đổi mật khẩu" + "Đăng xuất".
 *  "Đổi mật khẩu" mở modal yêu cầu nhập mật khẩu hiện tại + mới — chống chiếm
 *  đoạt phiên khi máy bị mất/khoá nhưng cookie còn hợp lệ. */
export function UserInfo() {
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [changeOpen, setChangeOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Click ngoài → đóng dropdown
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  if (!user) return null;

  return (
    <div className="flex items-center gap-2.5">
      {/* Avatar + tên → bấm mở dropdown */}
      <div ref={menuRef} className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className="flex items-center gap-2.5 rounded-lg px-1 py-0.5 transition-colors hover:bg-slate-100"
          title="Tài khoản"
        >
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600">
            {user.full_name.slice(0, 1).toUpperCase()}
          </div>
          <div className="hidden min-w-0 leading-tight text-left sm:block">
            <p className="truncate text-xs font-medium text-slate-900">{user.full_name}</p>
            <p className="truncate text-[11px] text-slate-400">{user.email}</p>
          </div>
        </button>

        {menuOpen && (
          <div
            role="menu"
            className="absolute right-0 top-full z-40 mt-1.5 w-56 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg"
          >
            <div className="border-b border-slate-100 px-3 py-2">
              <Badge className={ROLE_META[user.role].badge}>{ROLE_META[user.role].label}</Badge>
            </div>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                setChangeOpen(true);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
            >
              <KeyRound className="size-4 text-slate-400" />
              Đổi mật khẩu
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                void logout();
              }}
              className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
            >
              <LogOut className="size-4 text-slate-400" />
              Đăng xuất
            </button>
          </div>
        )}
      </div>

      <ChangePasswordModal open={changeOpen} onClose={() => setChangeOpen(false)} />
    </div>
  );
}

/** Modal đổi mật khẩu — gọi POST /api/auth/change-password (yêu cầu mật khẩu hiện tại). */
function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  // Reset form khi mở/đóng
  useEffect(() => {
    if (open) {
      setCurrent("");
      setNext("");
      setConfirm("");
      setError(null);
      setOk(false);
    }
  }, [open]);

  const submit = async () => {
    setError(null);
    if (next.length < 8) {
      setError("Mật khẩu mới phải có ít nhất 8 ký tự");
      return;
    }
    if (next !== confirm) {
      setError("Mật khẩu mới và xác nhận không khớp");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      setOk(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Đổi mật khẩu thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Đổi mật khẩu của tôi"
      footer={
        <>
          {ok ? (
            <Button onClick={onClose}>Đóng</Button>
          ) : (
            <>
              <Button variant="secondary" onClick={onClose} disabled={busy}>
                Hủy
              </Button>
              <Button onClick={() => void submit()} loading={busy} disabled={!current || !confirm}>
                Đổi mật khẩu
              </Button>
            </>
          )}
        </>
      }
    >
      {ok ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">
            ✔ Đổi mật khẩu thành công. Lần đăng nhập kế tiếp bạn sẽ dùng mật khẩu mới.
          </p>
          <p className="text-xs text-slate-500">
            Phiên hiện tại vẫn hoạt động cho đến khi hết hạn hoặc bạn đăng xuất. Để chắc chắn an toàn,
            hãy đăng xuất và đăng nhập lại.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-slate-500">
            Nhập mật khẩu hiện tại + mật khẩu mới (tối thiểu 8 ký tự). Hành động được ghi vào audit log.
          </p>
          <Field label="Mật khẩu hiện tại" required>
            <Input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
          </Field>
          <Field label="Mật khẩu mới" required hint="Tối thiểu 8 ký tự">
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
          {error && <p className="text-sm text-rose-600">{error}</p>}
        </div>
      )}
    </Modal>
  );
}