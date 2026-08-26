"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  KeyRound,
  Lock,
  LockOpen,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserCog,
  UserPlus,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ManagedUser, Organization, UserCreatePayload, UserRole } from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { ROLE_META, formatDateTime } from "@/lib/format";

const ROLE_OPTIONS: Array<{ value: UserRole; label: string }> = [
  { value: "super_admin", label: "Super Admin (toàn hệ thống)" },
  { value: "org_admin", label: "Admin cơ quan (org + cấp dưới)" },
  { value: "viewer", label: "Người xem (read-only)" },
];

const ROLE_CHOICES: UserRole[] = ["super_admin", "org_admin", "viewer"];

function roleBadge(role: string) {
  const meta = ROLE_META[role as UserRole];
  return meta ? meta.badge : "bg-slate-100 text-slate-600 ring-slate-500/20";
}

function roleLabel(role: string) {
  const meta = ROLE_META[role as UserRole];
  return meta ? meta.label : role;
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form tạo user
  const [showCreate, setShowCreate] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);
  const [form, setForm] = useState<UserCreatePayload>({
    email: "",
    full_name: "",
    role: "org_admin",
    org_id: "",
    password: "",
    phone: "",
  });

  // Reset password / khóa
  const [resetUser, setResetUser] = useState<ManagedUser | null>(null);
  const [resetPass, setResetPass] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const list = await api.get<ManagedUser[]>("/users");
      setUsers(list);
      setError(null);
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : "Không tải được danh sách tài khoản");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    api
      .get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
  }, [load]);

  const createUser = async (e: FormEvent) => {
    e?.preventDefault?.();
    setCreateErr(null);
    setCreateBusy(true);
    try {
      await api.post<ManagedUser>("/users", { ...form, phone: form.phone || undefined });
      setShowCreate(false);
      setForm({ email: "", full_name: "", role: "org_admin", org_id: "", password: "", phone: "" });
      await load(true);
    } catch (err) {
      setCreateErr(err instanceof Error ? err.message : "Không tạo được tài khoản");
    } finally {
      setCreateBusy(false);
    }
  };

  const doResetPassword = async () => {
    if (!resetUser) return;
    setResetBusy(true);
    try {
      await api.post(`/users/${resetUser.id}/reset-password`, { new_password: resetPass });
      setResetUser(null);
      setResetPass("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset mật khẩu thất bại");
    } finally {
      setResetBusy(false);
    }
  };

  const toggleActive = async (u: ManagedUser) => {
    setBusyId(u.id);
    try {
      await api.patch<ManagedUser>(`/users/${u.id}`, { is_active: !u.is_active });
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Thao tác thất bại");
    } finally {
      setBusyId(null);
    }
  };

  const reset2fa = async (u: ManagedUser) => {
    setBusyId(u.id);
    try {
      await api.post(`/users/${u.id}/reset-2fa`, {});
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset 2FA thất bại");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Quản trị tài khoản"
        description="Tạo tài khoản admin, cấp vai trò, đặt lại mật khẩu — chỉ Super Admin (mọi thao tác ghi audit log)"
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
            </Button>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <UserPlus className="size-3.5" /> Tạo tài khoản
            </Button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && users.length === 0 ? (
        <Spinner label="Đang tải danh sách tài khoản…" />
      ) : users.length === 0 ? (
        <EmptyState
          icon={<UserCog className="size-10" />}
          title="Chưa có tài khoản nào"
          description="Tạo tài khoản đầu tiên bằng nút 'Tạo tài khoản'."
        />
      ) : (
        <Card padded={false} title={`${users.length} tài khoản`}>
          <div className={TABLE_WRAP}>
            <table className={TABLE}>
              <thead className={THEAD}>
                <tr>
                  <th className={TH}>Người dùng</th>
                  <th className={TH}>Tổ chức</th>
                  <th className={TH}>Vai trò</th>
                  <th className={TH}>Trạng thái</th>
                  <th className={TH}>2FA</th>
                  <th className={TH}>Tạo lúc</th>
                  <th className={`${TH} text-right`}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className={TR_HOVER}>
                    <td className={TD}>
                      <p className="font-medium text-slate-800">{u.full_name}</p>
                      <p className="text-xs text-slate-400">{u.email}</p>
                    </td>
                    <td className={`${TD} text-xs text-slate-500`}>{u.org_name ?? "—"}</td>
                    <td className={TD}>
                      <Badge className={roleBadge(u.role)}>{roleLabel(u.role)}</Badge>
                    </td>
                    <td className={TD}>
                      {u.is_active ? (
                        <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">Hoạt động</Badge>
                      ) : (
                        <Badge className="bg-rose-50 text-rose-700 ring-rose-600/20">Đã khóa</Badge>
                      )}
                    </td>
                    <td className={TD}>
                      {u.is_2fa_enabled ? (
                        <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">
                          <ShieldCheck className="size-3.5" /> Bật
                        </Badge>
                      ) : (
                        <Badge className="bg-amber-50 text-amber-700 ring-amber-600/20">Chưa bật</Badge>
                      )}
                    </td>
                    <td className={`${TD} text-xs`}>{formatDateTime(u.created_at)}</td>
                    <td className={`${TD} text-right`}>
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={u.id === me?.id}
                          title={u.id === me?.id ? "Không reset mật khẩu chính mình" : "Đặt lại mật khẩu"}
                          onClick={() => setResetUser(u)}
                        >
                          <KeyRound className="size-3.5" /> Mật khẩu
                        </Button>
                        {u.is_2fa_enabled && (
                          <Button variant="outline" size="sm" disabled={busyId === u.id} onClick={() => void reset2fa(u)}>
                            Reset 2FA
                          </Button>
                        )}
                        <Button
                          variant={u.is_active ? "danger" : "success"}
                          size="sm"
                          disabled={busyId === u.id || u.id === me?.id}
                          onClick={() => void toggleActive(u)}
                        >
                          {u.is_active ? <Lock className="size-3.5" /> : <LockOpen className="size-3.5" />}
                          {u.is_active ? "Khóa" : "Kích hoạt"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Modal: tạo tài khoản */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="Tạo tài khoản"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Hủy</Button>
            <Button loading={createBusy} onClick={() => void createUser(null as unknown as FormEvent)}>
              <UserPlus className="size-4" /> Tạo tài khoản
            </Button>          </>
        }
      >
        <form onSubmit={createUser} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Họ tên" required>
              <Input
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                placeholder="Nguyễn Văn A"
                required
              />
            </Field>
            <Field label="Email" required>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="a@example.gov.vn"
                required
              />
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Vai trò" required>
              <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}>
                {ROLE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="Tổ chức" required hint="Super Admin thuộc tổ chức gốc">
              <Select
                value={form.org_id}
                onChange={(e) => setForm({ ...form, org_id: e.target.value })}
                required
              >
                <option value="">Chọn tổ chức…</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Mật khẩu" required hint="Tối thiểu 8 ký tự">
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="••••••••"
                minLength={8}
                required
              />
            </Field>
            <Field label="Số điện thoại (tùy chọn)" hint="Mã hóa AES-256-GCM">
              <Input
                value={form.phone ?? ""}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="0983…"
              />
            </Field>
          </div>
          {createErr && <p className="text-sm text-rose-600">{createErr}</p>}
          <p className="text-xs text-slate-400">
            Tài khoản tạo xong có thể đăng nhập ngay. Admin nên bật 2FA ở trang "Bảo mật tài khoản".
          </p>
        </form>
      </Modal>

      {/* Modal: reset mật khẩu */}
      <Modal
        open={resetUser !== null}
        onClose={() => setResetUser(null)}
        title={`Đặt lại mật khẩu — ${resetUser?.full_name ?? ""}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setResetUser(null)}>Hủy</Button>
            <Button loading={resetBusy} disabled={resetPass.length < 8} onClick={() => void doResetPassword()}>
              <KeyRound className="size-4" /> Xác nhận đặt lại
            </Button>
          </>
        }
      >
        <Field label="Mật khẩu mới" required hint="Tối thiểu 8 ký tự">
          <Input
            type="password"
            value={resetPass}
            onChange={(e) => setResetPass(e.target.value)}
            placeholder="••••••••"
            minLength={8}
          />
        </Field>
        <p className="mt-3 text-xs text-slate-400">
          Hành động ghi vào audit log. Người dùng phải đăng nhập bằng mật khẩu mới.
        </p>
      </Modal>
    </div>
  );
}
