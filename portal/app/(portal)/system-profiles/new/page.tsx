"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Organization, SystemProfileCreatePayload, SystemProfileDetail } from "@/lib/types";
import {
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Select,
  Textarea,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import { useFlatOrgs } from "@/lib/use-flat-orgs";

export default function NewSystemProfilePage() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [orgs, setOrgs] = useState<Organization[]>([]);
  const flatOrgs = useFlatOrgs(orgs);
  const [orgId, setOrgId] = useState(user?.org_id ?? "");
  // Mã hồ sơ tự sinh ở backend (HS-{năm}-{stt}); tên chủ quản gợi ý theo tổ chức của tài khoản
  const [managedBy, setManagedBy] = useState("");
  const [documentNumber, setDocumentNumber] = useState("");
  const [documentDate, setDocumentDate] = useState("");
  const [name, setName] = useState("");
  const [level, setLevel] = useState<1 | 2 | 3>(1);
  const [description, setDescription] = useState("");
  const [decisionNumber, setDecisionNumber] = useState("");
  const [decisionAgency, setDecisionAgency] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isSuperAdmin) {
      void api
        .get<Organization[]>("/orgs")
        .then(setOrgs)
        .catch(() => setOrgs([]));
    }
  }, [isSuperAdmin]);

  // Gợi ý tên chủ quản = tên tổ chức của tài khoản (đơn vị chọn/org của user); cho phép sửa
  useEffect(() => {
    const oid = isSuperAdmin ? orgId : user?.org_id;
    const fromList = flatOrgs.find(({ org }) => org.id === oid)?.org.name;
    setManagedBy((prev) => (fromList ?? prev) || prev);
  }, [isSuperAdmin, orgId, user?.org_id, flatOrgs]);

  const submit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Nhập tên hồ sơ");
      return;
    }
    const payload: SystemProfileCreatePayload = {
      org_id: orgId,
      name: name.trim(),
      level,
      description: description.trim() || null,
      managed_by: managedBy.trim() || null,
      document_number: documentNumber.trim() || null,
      document_date: documentDate || null,
    };
    // Super Admin tạo kèm số quyết định → hồ sơ được duyệt ngay
    if (isSuperAdmin && decisionNumber.trim()) {
      payload.decision_number = decisionNumber.trim();
      payload.decision_agency = decisionAgency.trim() || null;
    }
    setSaving(true);
    try {
      const created = await api.post<SystemProfileDetail>("/system-profiles", payload);
      router.push(`/system-profiles/${created.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Không tạo được hồ sơ");
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Tạo hồ sơ cấp độ" description="Khai báo thông tin hệ thống thông tin và cấp độ đề xuất. Mã hồ sơ được sinh tự động." />
      {error && <ErrorBanner message={error} />}
      <Card bodyClass="space-y-4">
        {isSuperAdmin && (
          <Field label="Đơn vị">
            <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              <option value="">— chọn đơn vị —</option>
              {flatOrgs.map(({ org, depth }) => (
                <option key={org.id} value={org.id}>{`${"— ".repeat(depth)}${org.name}`}</option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Tên chủ quản hệ thống thông tin" hint="Gợi ý theo tổ chức của tài khoản — có thể sửa nếu khác.">
          <Input value={managedBy} onChange={(e) => setManagedBy(e.target.value)} placeholder="Tên đơn vị chủ quản" />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Cấp độ đề xuất">
            <Select value={level} onChange={(e) => setLevel(Number(e.target.value) as 1 | 2 | 3)}>
              <option value={1}>Cấp 1</option>
              <option value={2}>Cấp 2</option>
              <option value={3}>Cấp 3</option>
            </Select>
          </Field>
          <Field label="Tên hệ thống thông tin">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Hệ thống thông tin quản lý văn bản" />
          </Field>
        </div>
        <Field label="Mô tả phạm vi, chức năng">
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
        </Field>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="mb-3 text-xs text-slate-500">
            Số văn bản đề nghị thẩm định (văn bản đơn vị gửi hồ sơ) — có thể bỏ trống và bổ sung sau.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Số văn bản đề nghị">
              <Input value={documentNumber} onChange={(e) => setDocumentNumber(e.target.value)} placeholder="VD: 125/BC-XX" />
            </Field>
            <Field label="Ngày văn bản">
              <Input type="date" value={documentDate} onChange={(e) => setDocumentDate(e.target.value)} />
            </Field>
          </div>
        </div>
        {isSuperAdmin && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p className="mb-3 text-xs text-amber-700">
              Điền số quyết định để tạo hồ sơ ở trạng thái <strong>đã phê duyệt</strong> (bỏ trống nếu muốn để quy trình trình — duyệt bình thường).
            </p>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Số quyết định">
                <Input value={decisionNumber} onChange={(e) => setDecisionNumber(e.target.value)} placeholder="15/QĐ-ATTT" />
              </Field>
              <Field label="Cơ quan ban hành">
                <Input value={decisionAgency} onChange={(e) => setDecisionAgency(e.target.value)} placeholder="Công an tỉnh" />
              </Field>
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <Button onClick={() => void submit()} loading={saving}>Tạo hồ sơ</Button>
          <Button variant="secondary" onClick={() => router.back()} disabled={saving}>Hủy</Button>
        </div>
      </Card>
    </div>
  );
}
