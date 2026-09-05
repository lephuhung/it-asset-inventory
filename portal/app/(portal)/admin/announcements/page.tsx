"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  BellRing,
  Building2,
  Check,
  Edit3,
  Eye,
  Plus,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AnnouncementCreatePayload,
  AnnouncementTargetType,
  AnnouncementUpdatePayload,
  Organization,
  SystemAnnouncement,
} from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  Textarea,
  Toggle,
} from "@/components/ui";

const ROLE_OPTIONS = [
  { value: "super_admin", label: "Super Admin" },
  { value: "org_admin", label: "Quản trị viên đơn vị (Org Admin)" },
  { value: "viewer", label: "Người xem (Viewer)" },
];

export default function AdminAnnouncementsPage() {
  const { user } = useAuth();
  const [announcements, setAnnouncements] = useState<SystemAnnouncement[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form State (Thêm / Sửa)
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [contentMd, setContentMd] = useState("");
  const [targetType, setTargetType] = useState<AnnouncementTargetType>("ALL");
  const [targetRole, setTargetRole] = useState<string>("");
  const [orgId, setOrgId] = useState<string>("");
  const [isActive, setIsActive] = useState<boolean>(true);
  const [formTab, setFormTab] = useState<"edit" | "preview">("edit");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Preview Modal
  const [previewItem, setPreviewItem] = useState<{ title: string; content_md: string; target_type: string } | null>(
    null
  );

  // Delete State
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [annList, orgList] = await Promise.all([
        api.get<SystemAnnouncement[]>("/announcements/admin"),
        api.get<Organization[]>("/orgs"),
      ]);
      setAnnouncements(annList);
      setOrgs(orgList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách thông báo");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isSuperAdmin) {
      void loadData();
    }
  }, [isSuperAdmin, loadData]);

  const openCreateModal = () => {
    setEditingId(null);
    setTitle("");
    setContentMd(
      `# Chào mừng bạn đến với Hệ thống Quản lý Tài sản Máy tính\n\n` +
      `Hệ thống giúp bạn theo dõi thông tin máy tính công vụ, cấu hình phần cứng và tình trạng bảo mật.\n\n` +
      `### 💡 Các tính năng nổi bật:\n` +
      `- **Quản lý máy tính**: Tra cứu cấu hình chi tiết, phần mềm đã cài đặt và lịch sử hoạt động.\n` +
      `- **Báo cáo & Thống kê**: Tự động tổng hợp dữ liệu kiểm kê phục vụ công tác quản lý tài sản số.\n` +
      `- **Bảo mật & Tuân thủ**: Bảo vệ an toàn dữ liệu và tuân thủ các quy chuẩn an ninh mạng.\n\n` +
      `> **Lưu ý bảo mật:** Hãy đổi mật khẩu định kỳ và không chia sẻ tài khoản với người khác.`
    );
    setTargetType("ALL");
    setTargetRole("");
    setOrgId("");
    setIsActive(true);
    setFormTab("edit");
    setFormError(null);
    setEditModalOpen(true);
  };

  const openEditModal = (ann: SystemAnnouncement) => {
    setEditingId(ann.id);
    setTitle(ann.title);
    setContentMd(ann.content_md);
    setTargetType(ann.target_type);
    setTargetRole(ann.target_role ?? "");
    setOrgId(ann.org_id ?? "");
    setIsActive(ann.is_active);
    setFormTab("edit");
    setFormError(null);
    setEditModalOpen(true);
  };

  const handleSave = async () => {
    if (!title.trim()) {
      setFormError("Vui lòng nhập tiêu đề thông báo");
      return;
    }
    if (!contentMd.trim()) {
      setFormError("Vui lòng nhập nội dung thông báo");
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      if (editingId) {
        const payload: AnnouncementUpdatePayload = {
          title: title.trim(),
          content_md: contentMd.trim(),
          target_type: targetType,
          target_role: targetType === "ROLE" ? targetRole : null,
          org_id: orgId ? orgId : null,
          is_active: isActive,
        };
        await api.put(`/announcements/admin/${editingId}`, payload);
      } else {
        const payload: AnnouncementCreatePayload = {
          title: title.trim(),
          content_md: contentMd.trim(),
          target_type: targetType,
          target_role: targetType === "ROLE" ? targetRole : null,
          org_id: orgId ? orgId : null,
          is_active: isActive,
        };
        await api.post("/announcements/admin", payload);
      }
      setEditModalOpen(false);
      await loadData();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Lưu thông báo thất bại");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    setDeleting(true);
    try {
      await api.delete(`/announcements/admin/${deleteId}`);
      setDeleteId(null);
      await loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xóa thông báo thất bại");
    } finally {
      setDeleting(false);
    }
  };

  if (!isSuperAdmin) {
    return (
      <div className="py-12">
        <EmptyState
          title="Không có quyền truy cập"
          description="Chức năng quản lý thông báo đăng nhập chỉ dành cho SuperAdmin."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quản lý thông báo đăng nhập"
        description="Tạo và quản lý thông báo dạng Modal tự động hiển thị cho người dùng khi đăng nhập vào hệ thống."
        actions={
          <Button
            variant="primary"
            className="rounded-full px-4 shadow-sm"
            onClick={openCreateModal}
          >
            <Plus className="size-4" />
            Tạo thông báo mới
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void loadData()} />}

      {loading ? (
        <Spinner label="Đang tải danh sách thông báo…" />
      ) : announcements.length === 0 ? (
        <EmptyState
          icon={<BellRing className="size-10 text-slate-400" />}
          title="Chưa có thông báo nào"
          description="Bấm 'Tạo thông báo mới' để thiết lập thông báo chào mừng hoặc thông báo hệ thống khi người dùng đăng nhập."
          action={
            <Button variant="primary" className="rounded-full" onClick={openCreateModal}>
              <Plus className="size-4" />
              Tạo thông báo đầu tiên
            </Button>
          }
        />
      ) : (
        <Card padded={false} className="overflow-hidden border border-slate-200 shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-600">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-5 py-3.5">Tiêu đề thông báo</th>
                  <th className="px-4 py-3.5">Đối tượng nhận</th>
                  <th className="px-4 py-3.5">Đơn vị áp dụng</th>
                  <th className="px-4 py-3.5">Trạng thái</th>
                  <th className="px-4 py-3.5">Người tạo / Ngày</th>
                  <th className="px-5 py-3.5 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {announcements.map((ann) => (
                  <tr key={ann.id} className="transition-colors hover:bg-slate-50/70">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2 font-medium text-slate-900">
                        {ann.target_type === "FIRST_LOGIN" ? (
                          <Sparkles className="size-4 shrink-0 text-amber-500" />
                        ) : (
                          <BellRing className="size-4 shrink-0 text-brand-600" />
                        )}
                        <span>{ann.title}</span>
                      </div>
                    </td>

                    <td className="px-4 py-4 whitespace-nowrap">
                      {ann.target_type === "ALL" && (
                        <Badge className="bg-slate-100 text-slate-700 ring-slate-200">
                          <Users className="size-3" /> Tất cả người dùng
                        </Badge>
                      )}
                      {ann.target_type === "FIRST_LOGIN" && (
                        <Badge className="bg-amber-50 text-amber-700 ring-amber-200">
                          <Sparkles className="size-3" /> Đăng nhập lần đầu
                        </Badge>
                      )}
                      {ann.target_type === "ROLE" && (
                        <Badge className="bg-sky-50 text-sky-700 ring-sky-200">
                          Vai trò: {ann.target_role}
                        </Badge>
                      )}
                    </td>

                    <td className="px-4 py-4 whitespace-nowrap">
                      {ann.org_name ? (
                        <span className="inline-flex items-center gap-1.5 text-xs text-slate-700 font-medium">
                          <Building2 className="size-3.5 text-slate-400" />
                          {ann.org_name}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                          <Building2 className="size-3.5 text-slate-400" />
                          Tất cả đơn vị
                        </span>
                      )}
                    </td>

                    <td className="px-4 py-4 whitespace-nowrap">
                      {ann.is_active ? (
                        <StatusBadge
                          badge="bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                          dot="bg-emerald-500"
                        >
                          Đang kích hoạt
                        </StatusBadge>
                      ) : (
                        <StatusBadge
                          badge="bg-slate-100 text-slate-500 ring-slate-200"
                          dot="bg-slate-400"
                        >
                          Tạm dừng
                        </StatusBadge>
                      )}
                    </td>

                    <td className="px-4 py-4 text-xs text-slate-500 whitespace-nowrap">
                      <div>{ann.creator_name ?? "Hệ thống"}</div>
                      <div className="text-[11px] text-slate-400">
                        {new Date(ann.created_at).toLocaleDateString("vi-VN", {
                          hour: "2-digit",
                          minute: "2-digit",
                          day: "2-digit",
                          month: "2-digit",
                          year: "numeric",
                        })}
                      </div>
                    </td>

                    <td className="px-5 py-4 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1.5">
                        <IconButton
                          label="Xem trước modal"
                          onClick={() => setPreviewItem(ann)}
                        >
                          <Eye className="size-4" />
                        </IconButton>
                        <IconButton
                          label="Chỉnh sửa thông báo"
                          onClick={() => openEditModal(ann)}
                        >
                          <Edit3 className="size-4" />
                        </IconButton>
                        <IconButton
                          label="Xóa thông báo"
                          className="hover:bg-rose-50 hover:text-rose-600"
                          onClick={() => setDeleteId(ann.id)}
                        >
                          <Trash2 className="size-4" />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Modal Thêm / Sửa Thông Báo */}
      <Modal
        open={editModalOpen}
        onClose={() => setEditModalOpen(false)}
        wide
        title={
          <span className="font-bold tracking-tight text-slate-900">
            {editingId ? "Chỉnh sửa thông báo" : "Tạo thông báo đăng nhập mới"}
          </span>
        }
        footer={
          <div className="flex w-full items-center justify-between gap-3">
            <Button
              variant="secondary"
              onClick={() => {
                setPreviewItem({
                  title: title || "Tiêu đề xem trước",
                  content_md: contentMd || "Nội dung xem trước...",
                  target_type: targetType,
                });
              }}
            >
              <Eye className="size-4" />
              Xem trước Modal
            </Button>
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={() => setEditModalOpen(false)}>
                Hủy
              </Button>
              <Button variant="primary" loading={saving} onClick={handleSave}>
                <Check className="size-4" />
                Lưu thông báo
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
          {formError && (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
              {formError}
            </div>
          )}

          <Field label="Tiêu đề thông báo" required>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="VD: Chào mừng bạn đến với hệ thống & Giới thiệu tính năng"
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Đối tượng nhận" required>
              <Select
                value={targetType}
                onChange={(e) => setTargetType(e.target.value as AnnouncementTargetType)}
              >
                <option value="ALL">Tất cả người dùng</option>
                <option value="FIRST_LOGIN">Chỉ người dùng đăng nhập lần đầu</option>
                <option value="ROLE">Theo vai trò người dùng</option>
              </Select>
            </Field>

            {targetType === "ROLE" ? (
              <Field label="Vai trò áp dụng" required>
                <Select
                  value={targetRole}
                  onChange={(e) => setTargetRole(e.target.value)}
                >
                  <option value="">-- Chọn vai trò --</option>
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : (
              <Field label="Đơn vị áp dụng (Tùy chọn)">
                <Select
                  value={orgId}
                  onChange={(e) => setOrgId(e.target.value)}
                >
                  <option value="">Tất cả các đơn vị trong hệ thống</option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </div>

          {targetType === "ROLE" && (
            <Field label="Đơn vị áp dụng (Tùy chọn)">
              <Select
                value={orgId}
                onChange={(e) => setOrgId(e.target.value)}
              >
                <option value="">Tất cả các đơn vị trong hệ thống</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[13px] font-medium text-slate-700">
                Nội dung thông báo (hỗ trợ Markdown) <span className="text-rose-500">*</span>
              </span>
              <div className="flex items-center gap-1 rounded-md bg-slate-100 p-0.5 text-xs font-medium text-slate-600">
                <button
                  type="button"
                  onClick={() => setFormTab("edit")}
                  className={`rounded px-2.5 py-1 transition-colors ${
                    formTab === "edit" ? "bg-white text-slate-900 shadow-xs" : "hover:text-slate-900"
                  }`}
                >
                  Soạn thảo
                </button>
                <button
                  type="button"
                  onClick={() => setFormTab("preview")}
                  className={`rounded px-2.5 py-1 transition-colors ${
                    formTab === "preview" ? "bg-white text-slate-900 shadow-xs" : "hover:text-slate-900"
                  }`}
                >
                  Xem trước trực tiếp
                </button>
              </div>
            </div>

            {formTab === "edit" ? (
              <Textarea
                rows={10}
                value={contentMd}
                onChange={(e) => setContentMd(e.target.value)}
                placeholder="Nhập nội dung thông báo định dạng Markdown..."
                className="font-mono text-xs"
              />
            ) : (
              <div className="min-h-52 rounded-xs border border-slate-200 bg-slate-50/50 p-4 prose prose-slate max-w-none text-xs leading-relaxed text-slate-700">
                <ReactMarkdown>{contentMd || "*Chưa có nội dung soạn thảo*"}</ReactMarkdown>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/50 p-3.5">
            <div>
              <p className="text-sm font-medium text-slate-900">Kích hoạt thông báo</p>
              <p className="text-xs text-slate-500">
                Khi bật, người dùng thỏa mãn điều kiện sẽ thấy Modal này khi đăng nhập.
              </p>
            </div>
            <Toggle
              checked={isActive}
              onChange={setIsActive}
              label="Kích hoạt thông báo"
            />
          </div>
        </div>
      </Modal>

      {/* Modal Xem Trước (Live Preview Modal) */}
      {previewItem && (
        <Modal
          open={true}
          onClose={() => setPreviewItem(null)}
          wide
          title={
            <div className="flex items-center gap-2.5">
              <span className="flex size-7 items-center justify-center rounded-lg bg-sky-50 text-brand-600">
                {previewItem.target_type === "FIRST_LOGIN" ? (
                  <Sparkles className="size-4" />
                ) : (
                  <BellRing className="size-4" />
                )}
              </span>
              <span className="font-bold tracking-tight text-slate-900">{previewItem.title}</span>
            </div>
          }
          footer={
            <div className="flex w-full items-center justify-between gap-3">
              <div className="text-xs text-slate-400">
                <span>[Chế độ xem trước của SuperAdmin]</span>
              </div>
              <Button
                variant="primary"
                onClick={() => setPreviewItem(null)}
                className="rounded-full px-6 shadow-sm"
              >
                <Check className="size-4" />
                Tôi đã hiểu & Bắt đầu sử dụng
              </Button>
            </div>
          }
        >
          <div className="max-h-[60vh] overflow-y-auto pr-2">
            <div className="prose prose-slate max-w-none text-sm leading-relaxed text-slate-700">
              <ReactMarkdown
                components={{
                  h1: ({ children }) => (
                    <h1 className="mt-2 mb-3 text-lg font-bold tracking-tight text-slate-900 border-b border-slate-100 pb-2">
                      {children}
                    </h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="mt-4 mb-2 text-base font-semibold tracking-tight text-slate-800">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="mt-3 mb-1.5 text-sm font-semibold text-slate-800">
                      {children}
                    </h3>
                  ),
                  ul: ({ children }) => (
                    <ul className="my-2 ml-5 list-disc space-y-1 text-slate-600">{children}</ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="my-2 ml-5 list-decimal space-y-1 text-slate-600">{children}</ol>
                  ),
                  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                  blockquote: ({ children }) => (
                    <blockquote className="my-3 border-l-3 border-brand-500 bg-sky-50/50 px-3.5 py-2 text-xs italic text-slate-700 rounded-r-md">
                      {children}
                    </blockquote>
                  ),
                  strong: ({ children }) => (
                    <strong className="font-semibold text-slate-900">{children}</strong>
                  ),
                  code: ({ children }) => (
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-800">
                      {children}
                    </code>
                  ),
                }}
              >
                {previewItem.content_md}
              </ReactMarkdown>
            </div>
          </div>
        </Modal>
      )}

      {/* Modal Xác Nhận Xóa */}
      <Modal
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        title="Xác nhận xóa thông báo"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setDeleteId(null)}>
              Hủy
            </Button>
            <Button variant="danger" loading={deleting} onClick={handleDelete}>
              Xóa thông báo
            </Button>
          </div>
        }
      >
        <p className="text-sm text-slate-600">
          Bạn có chắc chắn muốn xóa thông báo này không? Sau khi xóa, người dùng sẽ không còn nhận được
          thông báo này khi đăng nhập.
        </p>
      </Modal>
    </div>
  );
}
