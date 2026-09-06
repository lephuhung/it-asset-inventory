"use client";

/**
 * Danh bạ chuyên trách CNTT / tổ chức vận hành theo đơn vị.
 *
 * Mỗi đơn vị có n contact: cá nhân chuyên trách (kind=person) hoặc tổ chức
 * được giao vận hành (kind=org, có đầu mối liên hệ). Contact được gắn vào
 * hồ sơ cấp độ ở trang chi tiết hồ sơ (`profile_count` hiển thị số hồ sơ
 * đang gắn).
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Building2, Plus, User } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ItContact, ItContactKind, ItContactPayload, Organization } from "@/lib/types";
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
  Select,
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
import { useFlatOrgs } from "@/lib/use-flat-orgs";

export default function ItContactsPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";
  const isAdmin = isSuperAdmin || user?.role === "org_admin" || user?.role === "admin_org";

  const [items, setItems] = useState<ItContact[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const flatOrgs = useFlatOrgs(orgs);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [orgId, setOrgId] = useState(isSuperAdmin ? "" : (user?.org_id ?? ""));
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");

  // Modal thêm/sửa
  const [modal, setModal] = useState<ItContact | "new" | null>(null);
  const [cOrgId, setCOrgId] = useState("");
  const [cKind, setCKind] = useState<ItContactKind>("person");
  const [cName, setCName] = useState("");
  const [cPosition, setCPosition] = useState("");
  const [cContactPerson, setCContactPerson] = useState("");
  const [cPhone, setCPhone] = useState("");
  const [cEmail, setCEmail] = useState("");
  const [cAddress, setCAddress] = useState("");
  const [cNote, setCNote] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<ItContact | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<ItContact[]>("/it-contacts", { org_id: orgId, kind, q });
      setItems(rows);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Không tải được danh bạ");
    } finally {
      setLoading(false);
    }
  }, [orgId, kind, q]);

  useEffect(() => {
    if (isSuperAdmin) void api.get<Organization[]>("/orgs").then(setOrgs).catch(() => setOrgs([]));
  }, [isSuperAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  const openModal = (c: ItContact | "new") => {
    if (c === "new") {
      setCOrgId(orgId || user?.org_id || "");
      setCKind("person");
      setCName(""); setCPosition(""); setCContactPerson(""); setCPhone(""); setCEmail(""); setCAddress(""); setCNote("");
    } else {
      setCOrgId(c.org_id);
      setCKind(c.kind);
      setCName(c.name); setCPosition(c.position ?? ""); setCContactPerson(c.contact_person ?? "");
      setCPhone(c.phone ?? ""); setCEmail(c.email ?? ""); setCAddress(c.address ?? ""); setCNote(c.note ?? "");
    }
    setModal(c);
  };

  const save = async () => {
    if (!modal || !cName.trim()) return;
    const org = cOrgId || user?.org_id;
    if (!org) {
      setError("Chọn đơn vị trước khi thêm contact");
      return;
    }
    const payload: ItContactPayload = {
      org_id: org,
      kind: cKind,
      name: cName.trim(),
      position: cPosition.trim() || null,
      contact_person: cKind === "org" ? cContactPerson.trim() || null : null,
      phone: cPhone.trim() || null,
      email: cEmail.trim() || null,
      address: cAddress.trim() || null,
      note: cNote.trim() || null,
    };
    setBusy(true);
    setError(null);
    try {
      if (modal === "new") {
        await api.post("/it-contacts", payload);
      } else {
        const { org_id: _o, kind: _k, ...update } = payload;
        await api.patch(`/it-contacts/${modal.id}`, update);
      }
      setModal(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Không lưu được contact");
    } finally {
      setBusy(false);
    }
  };

  if (!isAdmin) {
    return <ErrorBanner message="Chỉ quản trị đơn vị mới quản lý được danh bạ chuyên trách." />;
  }

  return (
    <div>
      <PageHeader
        title="Chuyên trách CNTT & tổ chức vận hành"
        description="Danh bạ liên hệ của đơn vị: người chuyên trách CNTT và tổ chức được giao vận hành. Gắn vào hồ sơ cấp độ ở trang chi tiết hồ sơ."
        actions={
          <Button onClick={() => openModal("new")}>
            <Plus className="size-4" /> Thêm contact
          </Button>
        }
      />

      {error && <ErrorBanner message={error} />}

      <Card className="mb-4" title="Bộ lọc" padded={false}>
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          {isSuperAdmin && (
            <Field label="Đơn vị">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">Tất cả đơn vị</option>
                {flatOrgs.map(({ org, depth }) => (
                  <option key={org.id} value={org.id}>{`${"— ".repeat(depth)}${org.name}`}</option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Loại">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">Tất cả</option>
              <option value="person">Chuyên trách CNTT</option>
              <option value="org">Tổ chức vận hành</option>
            </Select>
          </Field>
          <Field label="Tìm theo tên">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tên người / tổ chức, đầu mối…" />
          </Field>
        </div>
      </Card>

      {loading && items.length === 0 ? (
        <Spinner label="Đang tải danh bạ…" />
      ) : items.length === 0 && !error ? (
        <EmptyState
          icon={<User className="size-8 text-slate-400" />}
          title="Chưa có contact nào"
          description="Thêm người chuyên trách CNTT hoặc tổ chức vận hành để gắn vào hồ sơ cấp độ."
        />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th className={TH}>Tên</th>
                <th className={TH}>Đơn vị</th>
                <th className={TH}>Chức vụ / Đầu mối</th>
                <th className={TH}>Điện thoại</th>
                <th className={TH}>Email</th>
                <th className={TH}>Hồ sơ gắn</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} className={TR_HOVER}>
                  <td className={TD}>
                    <div className="flex items-center gap-2 font-medium">
                      {c.kind === "org" ? (
                        <Building2 className="size-4 text-sky-600" />
                      ) : (
                        <User className="size-4 text-indigo-600" />
                      )}
                      {c.name}
                    </div>
                    {c.note && <div className="text-xs text-slate-500">{c.note}</div>}
                  </td>
                  <td className={`${TD} text-sm`}>{c.org_name ?? c.org_id}</td>
                  <td className={`${TD} text-sm`}>
                    {c.kind === "org"
                      ? [c.position, c.contact_person ? `Đầu mối: ${c.contact_person}` : null].filter(Boolean).join(" · ") || "—"
                      : c.position || "—"}
                  </td>
                  <td className={`${TD} text-sm`}>{c.phone ?? "—"}</td>
                  <td className={`${TD} text-sm`}>{c.email ?? "—"}</td>
                  <td className={TD}>
                    {c.profile_count > 0 ? (
                      <Badge className="bg-brand-50 text-brand-700 ring-brand-600/20">{c.profile_count} hồ sơ</Badge>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className={TD}>
                    <div className="flex gap-1">
                      <Button size="sm" variant="secondary" onClick={() => openModal(c)}>Sửa</Button>
                      <Button size="sm" variant="danger" onClick={() => setConfirmDelete(c)}>Xóa</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal thêm/sửa contact */}
      <Modal
        open={modal !== null}
        onClose={() => setModal(null)}
        title={modal === "new" ? "Thêm contact" : "Sửa contact"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(null)} disabled={busy}>Hủy</Button>
            <Button onClick={() => void save()} loading={busy}>Lưu</Button>
          </>
        }
      >
        <div className="space-y-3">
          {modal === "new" && isSuperAdmin && (
            <Field label="Đơn vị" required>
              <Select value={cOrgId} onChange={(e) => setCOrgId(e.target.value)}>
                <option value="">— chọn đơn vị —</option>
                {flatOrgs.map(({ org, depth }) => (
                  <option key={org.id} value={org.id}>{`${"— ".repeat(depth)}${org.name}`}</option>
                ))}
              </Select>
            </Field>
          )}
          {modal === "new" && (
            <Field label="Loại contact" required>
              <Select value={cKind} onChange={(e) => setCKind(e.target.value as ItContactKind)}>
                <option value="person">Cá nhân — chuyên trách CNTT</option>
                <option value="org">Tổ chức — được giao vận hành</option>
              </Select>
            </Field>
          )}
          <Field label={cKind === "org" ? "Tên tổ chức" : "Họ tên"} required>
            <Input value={cName} onChange={(e) => setCName(e.target.value)} placeholder={cKind === "org" ? "Trung tâm Công nghệ thông tin" : "Nguyễn Văn A"} />
          </Field>
          <Field label={cKind === "org" ? "Vai trò vận hành" : "Chức vụ"} hint={cKind === "org" ? "VD: Vận hành hạ tầng mạng, quản trị website" : "VD: Chuyên viên CNTT, Trưởng phòng"}>
            <Input value={cPosition} onChange={(e) => setCPosition(e.target.value)} />
          </Field>
          {cKind === "org" && (
            <Field label="Đầu mối liên hệ" hint="Người đại diện tiếp nhận của tổ chức vận hành">
              <Input value={cContactPerson} onChange={(e) => setCContactPerson(e.target.value)} placeholder="Trần Văn B — 0901234567" />
            </Field>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Điện thoại"><Input value={cPhone} onChange={(e) => setCPhone(e.target.value)} placeholder="0912345678" /></Field>
            <Field label="Email"><Input value={cEmail} onChange={(e) => setCEmail(e.target.value)} placeholder="cntt@donvi.gov.vn" /></Field>
          </div>
          <Field label="Địa chỉ"><Textarea value={cAddress} onChange={(e) => setCAddress(e.target.value)} rows={2} /></Field>
          <Field label="Ghi chú"><Textarea value={cNote} onChange={(e) => setCNote(e.target.value)} rows={2} /></Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Xóa contact?"
        message={
          confirmDelete
            ? `Xóa "${confirmDelete.name}" khỏi danh bạ${confirmDelete.profile_count > 0 ? ` và gỡ khỏi ${confirmDelete.profile_count} hồ sơ đang gắn` : ""}. Thao tác không thể hoàn tác.`
            : ""
        }
        danger
        loading={busy}
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => {
          const c = confirmDelete;
          setConfirmDelete(null);
          if (!c) return;
          setBusy(true);
          void api
            .delete(`/it-contacts/${c.id}`)
            .then(load)
            .catch((e) => setError(e instanceof ApiError ? e.detail : "Không xóa được contact"))
            .finally(() => setBusy(false));
        }}
      />
    </div>
  );
}
