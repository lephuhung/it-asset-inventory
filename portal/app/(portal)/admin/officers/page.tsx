"use client";

/**
 * Danh sách cán bộ phụ trách (đầu mối SuperAdmin) — toàn cục.
 *
 * Cán bộ đại diện tổ chức bên ngoài hệ thống (Sở TT&TT, đơn vị tư vấn…),
 * KHÔNG gắn vào `organizations`. 1 cán bộ có thể được chỉ định cho nhiều
 * hồ sơ cấp độ (FK `system_profiles.officer_id`). Chỉ Super Admin CRUD.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Briefcase, Edit3, Plus, Trash2, UserCircle } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { validateEmail, validatePhoneVN } from "@/lib/validators";
import type { Officer, OfficerPayload } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
  Textarea,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";

export default function AdminOfficersPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [items, setItems] = useState<Officer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  // Modal thêm/sửa
  const [modal, setModal] = useState<Officer | "new" | null>(null);
  const [oName, setOName] = useState("");
  const [oOrg, setOOrg] = useState("");
  const [oTitle, setOTitle] = useState("");
  const [oPhone, setOPhone] = useState("");
  const [oEmail, setOEmail] = useState("");
  const [oNote, setONote] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<Officer | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<Officer[]>("/officers", { q: q || undefined });
      setItems(rows);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Không tải được danh sách cán bộ");
    } finally {
      setLoading(false);
    }
  }, [q]);

  useEffect(() => {
    void load();
  }, [load]);

  const openModal = (o: Officer | "new") => {
    setError(null);
    if (o === "new") {
      setOName("");
      setOOrg("");
      setOTitle("");
      setOPhone("");
      setOEmail("");
      setONote("");
    } else {
      setOName(o.name);
      setOOrg(o.organization ?? "");
      setOTitle(o.title ?? "");
      setOPhone(o.phone ?? "");
      setOEmail(o.email ?? "");
      setONote(o.note ?? "");
    }
    setModal(o);
  };

  const oEmailError = validateEmail(oEmail);
  const oPhoneError = validatePhoneVN(oPhone);

  const save = async () => {
    if (!modal || !oName.trim()) return;
    if (oEmailError || oPhoneError) {
      setError(oEmailError ?? oPhoneError ?? "Vui lòng kiểm tra lại email/điện thoại");
      return;
    }
    const payload: OfficerPayload = {
      name: oName.trim(),
      organization: oOrg.trim() || null,
      title: oTitle.trim() || null,
      phone: oPhone.trim() || null,
      email: oEmail.trim() || null,
      note: oNote.trim() || null,
    };
    setBusy(true);
    setError(null);
    try {
      if (modal === "new") {
        await api.post("/officers", payload);
      } else {
        await api.patch(`/officers/${modal.id}`, payload);
      }
      setModal(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Không lưu được cán bộ");
    } finally {
      setBusy(false);
    }
  };

  if (!isSuperAdmin) {
    return (
      <ErrorBanner message="Chỉ Super Admin mới quản lý được danh sách cán bộ phụ trách." />
    );
  }

  return (
    <div>
      <PageHeader
        title="Cán bộ phụ trách (đầu mối SuperAdmin)"
        description="Danh sách cán bộ đại diện tổ chức bên ngoài hệ thống. Mỗi cán bộ có thể được chỉ định phụ trách nhiều hồ sơ cấp độ."
        actions={
          <Button onClick={() => openModal("new")}>
            <Plus className="size-4" /> Thêm cán bộ
          </Button>
        }
      />

      {error && <ErrorBanner message={error} />}

      <Card className="mb-4" title="Bộ lọc" padded={false}>
        <div className="grid gap-3 p-4 sm:grid-cols-2">
          <Field label="Tìm theo tên / tổ chức / chức vụ">
            <Input
              value={q}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQ(e.target.value)}
              placeholder="Nguyễn Văn A, Sở TT&TT, Phó giám đốc…"
            />
          </Field>
        </div>
      </Card>

      {loading && items.length === 0 ? (
        <Spinner label="Đang tải danh sách cán bộ…" />
      ) : items.length === 0 && !error ? (
        <EmptyState
          icon={<UserCircle className="size-8 text-slate-400" />}
          title="Chưa có cán bộ nào"
          description="Thêm cán bộ phụ trách để chỉ định cho các hồ sơ cấp độ (Super Admin)."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th className={TH}>Họ tên</th>
                <th className={TH}>Tổ chức / Chức vụ</th>
                <th className={TH}>Điện thoại</th>
                <th className={TH}>Email</th>
                <th className={TH}>Hồ sơ phụ trách</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.id} className={TR_HOVER}>
                  <td className={TD}>
                    <div className="flex items-center gap-2 font-medium">
                      <Briefcase className="size-4 text-amber-600" />
                      {o.name}
                    </div>
                    {o.note && (
                      <div className="text-xs text-slate-500">{o.note}</div>
                    )}
                  </td>
                  <td className={`${TD} text-sm`}>
                    {o.organization || <span className="italic text-slate-400">—</span>}
                    {o.title && (
                      <div className="text-xs text-slate-500">{o.title}</div>
                    )}
                  </td>
                  <td className={`${TD} text-sm`}>{o.phone || "—"}</td>
                  <td className={`${TD} text-sm`}>{o.email || "—"}</td>
                  <td className={TD}>
                    {o.profile_count > 0 ? (
                      <Badge className="bg-brand-50 text-brand-700 ring-brand-600/20">
                        {o.profile_count} hồ sơ
                      </Badge>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className={TD}>
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => openModal(o)}
                      >
                        <Edit3 className="size-3.5" /> Sửa
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => setConfirmDelete(o)}
                      >
                        <Trash2 className="size-3.5" /> Xóa
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs text-slate-400">
        Sau khi thêm, chỉ định cán bộ cho hồ sơ cấp độ ở trang chi tiết hồ sơ (tab "Tổng quan" → mục "Cán bộ phụ trách").{" "}
        <Link href="/system-profiles" className="text-brand-600 hover:underline">
          Xem danh sách hồ sơ →
        </Link>
      </p>

      {/* Modal thêm/sửa */}
      <Modal
        open={modal !== null}
        onClose={() => !busy && setModal(null)}
        title={modal === "new" ? "Thêm cán bộ" : "Sửa cán bộ"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(null)} disabled={busy}>
              Hủy
            </Button>
            <Button onClick={() => void save()} loading={busy}>
              Lưu
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {error && <ErrorBanner message={error} />}
          <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-200">
            Cán bộ đại diện tổ chức bên ngoài hệ thống (không thuộc cây tổ chức UBND).
            Thông tin cán bộ sống ở đây — chỉnh sửa 1 chỗ áp dụng cho mọi hồ sơ đang gán.
          </p>
          <Field label="Họ tên cán bộ" required>
            <Input
              value={oName}
              onChange={(e) => setOName(e.target.value)}
              placeholder="Nguyễn Văn A"
            />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Tổ chức">
              <Input
                value={oOrg}
                onChange={(e) => setOOrg(e.target.value)}
                placeholder="Sở TT&TT, Công ty ABC…"
              />
            </Field>
            <Field label="Chức vụ">
              <Input
                value={oTitle}
                onChange={(e) => setOTitle(e.target.value)}
                placeholder="Phó giám đốc, Trưởng phòng…"
              />
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Điện thoại" error={oPhoneError ?? undefined}>
              <Input
                value={oPhone}
                onChange={(e) => setOPhone(e.target.value)}
                placeholder="0912345678"
              />
            </Field>
            <Field label="Email" error={oEmailError ?? undefined}>
              <Input
                type="email"
                value={oEmail}
                onChange={(e) => setOEmail(e.target.value)}
                placeholder="ten@donvi.vn"
              />
            </Field>
          </div>
          <Field label="Ghi chú">
            <Textarea
              value={oNote}
              onChange={(e) => setONote(e.target.value)}
              rows={2}
              placeholder="Phạm vi phụ trách, vai trò…"
            />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Xóa cán bộ?"
        message={
          confirmDelete
            ? `Xóa "${confirmDelete.name}" khỏi danh sách. ${
                confirmDelete.profile_count > 0
                  ? `Cảnh báo: ${confirmDelete.profile_count} hồ sơ đang gán cán bộ này — sẽ tự set officer_id=NULL.`
                  : "Không ảnh hưởng hồ sơ nào."
              }`
            : ""
        }
        danger
        loading={busy}
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => {
          const o = confirmDelete;
          setConfirmDelete(null);
          if (!o) return;
          setBusy(true);
          void api
            .delete(`/officers/${o.id}`)
            .then(load)
            .catch((e) => setError(e instanceof ApiError ? e.detail : "Không xóa được cán bộ"))
            .finally(() => setBusy(false));
        }}
      />
    </div>
  );
}
