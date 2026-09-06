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
  Spinner,
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
  const [code, setCode] = useState("");
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

  const submit = async () => {
    setError(null);
    if (!name.trim() || !code.trim()) {
      setError("Nhập đầy đủ mã và tên hồ sơ");
      return;
    }
    const payload: SystemProfileCreatePayload = {
      org_id: orgId,
      code: code.trim(),
      name: name.trim(),
      level,
      description: description.trim() || null,
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
      <PageHeader title="Tạo hồ sơ cấp độ" description="Khai báo thông tin hệ thống thông tin và cấp độ đề xuất." />
      {error && <ErrorBanner message={error} />}
      <Card className="space-y-4 p-6">
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
        <div className="grid grid-cols-2 gap-4">
          <Field label="Mã hồ sơ">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="HTTT-2026-01" />
          </Field>
          <Field label="Cấp độ đề xuất">
            <Select value={level} onChange={(e) => setLevel(Number(e.target.value) as 1 | 2 | 3)}>
              <option value={1}>Cấp 1</option>
              <option value={2}>Cấp 2</option>
              <option value={3}>Cấp 3</option>
            </Select>
          </Field>
        </div>
        <Field label="Tên hệ thống thông tin">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Hệ thống thông tin quản lý văn bản" />
        </Field>
        <Field label="Mô tả phạm vi, chức năng">
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
        </Field>
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
