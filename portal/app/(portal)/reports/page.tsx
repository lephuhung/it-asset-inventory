"use client";

import { useEffect, useState } from "react";
import { Download, FileSpreadsheet, FileText, ShieldCheck } from "lucide-react";
import { api, downloadFromApi } from "@/lib/api";
import type { Organization } from "@/lib/types";
import { ORG_TYPE_META, flattenOrgTree } from "@/lib/format";
import { useAuth } from "@/components/auth-context";
import {
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Select,
} from "@/components/ui";

const STATUS_OPTIONS = [
  { value: "", label: "Tất cả trạng thái" },
  { value: "online", label: "Online" },
  { value: "offline", label: "Offline" },
  { value: "lost", label: "Máy ma" },
  { value: "pending", label: "Chờ duyệt" },
  { value: "decommissioned", label: "Đã thanh lý" },
];

export default function ReportsPage() {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [orgId, setOrgId] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [includeFull, setIncludeFull] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
  }, []);

  const params = () => ({
    org_id: orgId || undefined,
    status: status || undefined,
    q: q || undefined,
    include_phone_full: includeFull || undefined,
  });

  const exportExcel = async () => {
    setBusy(true);
    setError(null);
    try {
      await downloadFromApi("/reports/export", params(), "POST");
      setDone(`Excel ${new Date().toLocaleTimeString("vi-VN")}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xuất báo cáo thất bại");
    } finally {
      setBusy(false);
    }
  };

  const isAdmin =
    user?.role === "super_admin" || user?.role === "org_admin" || user?.role === "admin_global" || user?.role === "admin_org";

  const exportPdf = async () => {
    setBusy(true);
    setError(null);
    try {
      await downloadFromApi("/reports/export-pdf", params(), "POST");
      setDone(`PDF ${new Date().toLocaleTimeString("vi-VN")}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xuất PDF thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Xuất báo cáo"
        description="Báo cáo Excel danh sách máy theo biểu mẫu quản lý tài sản — mọi lần xuất đều ghi audit log"
      />

      {error && <ErrorBanner message={error} />}
      {done && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          ✅ Đã xuất báo cáo lúc {done}. Kiểm tra file tải về trong trình duyệt.
        </div>
      )}

      <Card title="Bộ lọc báo cáo">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Tìm kiếm (hostname / UUID)">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="VD: PC-042" />
          </Field>
          <Field label="Trạng thái">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          {orgs.length > 0 && (
            <Field label="Tổ chức (UBND cấp xã / Sở ban ngành)">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">Tất cả</option>
                {flattenOrgTree(orgs).map(({ org, depth }) => {
                  const meta = ORG_TYPE_META[org.type];
                  return (
                    <option key={org.id} value={org.id}>
                      {"— ".repeat(depth)}
                      {org.name} ({meta?.label ?? org.type})
                    </option>
                  );
                })}
              </Select>
            </Field>
          )}
          <div />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2.5 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={includeFull}
              disabled={!isAdmin}
              onChange={(e) => setIncludeFull(e.target.checked)}
              className="size-4 cursor-pointer rounded border-slate-300 text-[#635a5a] focus:ring-2 focus:ring-blue-500/40 focus:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-50"
            />
            Kèm số điện thoại đầy đủ
            {!isAdmin && (
              <span className="text-xs text-slate-400">(chỉ admin có quyền — mục 7.3)</span>
            )}
          </label>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="secondary" onClick={() => void exportPdf()} loading={busy}>
              <FileText className="size-4" /> Xuất PDF
            </Button>
            <Button onClick={() => void exportExcel()} loading={busy}>
              <Download className="size-4" /> Xuất file Excel
            </Button>
          </div>
        </div>
      </Card>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Card title="Quyền xem dữ liệu cá nhân">
          <div className="flex items-start gap-3 text-sm text-slate-600">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-[#635a5a]" />
            <p>
              Số điện thoại <b>mặc định bị mask</b> (<code>0983•••123</code>). Chỉ khi tích chọn
              phía trên (và bạn có vai trò admin) dữ liệu mới xuất đầy đủ — phù hợp Nghị định
              13/2023/NĐ-CP.
            </p>
          </div>
        </Card>
        <Card title="Định dạng báo cáo">
          <div className="flex items-start gap-3 text-sm text-slate-600">
            <FileSpreadsheet className="mt-0.5 size-5 shrink-0 text-emerald-600" />
            <p>
              File <code>.xlsx</code> theo biểu mẫu hành chính: thông tin máy, cấu hình, người
              dùng, trạng thái. Báo cáo PDF (WeasyPrint) dự kiến Phase 4.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}