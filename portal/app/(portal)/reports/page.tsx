"use client";

import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  ShieldCheck,
  Stamp,
} from "lucide-react";
import { api, downloadFromApi } from "@/lib/api";
import type { Organization } from "@/lib/types";
import { ORG_TYPE_META } from "@/lib/format";
import { useFlatOrgs } from "@/lib/use-flat-orgs";
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
  { value: "lost", label: "Mất kết nối (máy BMNN > 15 ngày)" },
  { value: "pending", label: "Chờ duyệt" },
  { value: "decommissioned", label: "Đã thanh lý" },
];

export default function ReportsPage() {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const flatOrgs = useFlatOrgs(orgs);
  const [orgId, setOrgId] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [includeFull, setIncludeFull] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [pdfMeta, setPdfMeta] = useState<{ sha256?: string; timestamp?: string } | null>(null);
  const [verifyResult, setVerifyResult] = useState<{
    sha256: string;
    timestamped: boolean;
    timestamps: { gen_time: string | null; tsa_subject: string; intact: boolean; valid: boolean }[];
  } | null>(null);
  const [verifyBusy, setVerifyBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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
    setPdfMeta(null);
    try {
      const meta = await downloadFromApi("/reports/export-pdf", params(), "POST");
      setPdfMeta(meta);
      setDone(`PDF ${new Date().toLocaleTimeString("vi-VN")}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xuất PDF thất bại");
    } finally {
      setBusy(false);
    }
  };

  const verifyPdf = async (file: File) => {
    setVerifyBusy(true);
    setError(null);
    setVerifyResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.postForm<{
        sha256: string;
        timestamped: boolean;
        timestamps: { gen_time: string | null; tsa_subject: string; intact: boolean; valid: boolean }[];
      }>("/reports/verify", fd);
      setVerifyResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kiểm chứng thất bại");
    } finally {
      setVerifyBusy(false);
      if (fileRef.current) fileRef.current.value = "";
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
          <div className="flex items-center gap-2">
            <CheckCircle2 className="size-4" />
            Đã xuất báo cáo lúc {done}. Kiểm tra file tải về trong trình duyệt.
          </div>
          {pdfMeta?.timestamp && (
            <div className="mt-2 space-y-1 border-t border-emerald-200 pt-2 text-xs">
              <div className="flex items-center gap-1.5">
                <Stamp className="size-3.5" />
                Dấu thời gian RFC 3161 (TSA):{" "}
                <b>{new Date(pdfMeta.timestamp).toLocaleString("vi-VN")}</b> — file đã nhúng chứng
                chỉ thời gian, kiểm chứng bằng ô bên dưới.
              </div>
              {pdfMeta.sha256 && (
                <div className="break-all font-mono">SHA-256: {pdfMeta.sha256}</div>
              )}
            </div>
          )}
        </div>
      )}

      <Card title="Bộ lọc báo cáo">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Tìm kiếm (hostname / UUID)">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="VD: PC-042" />
          </Field>
          <Field label="Trạng thái">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {(STATUS_OPTIONS ?? []).map((o) => (
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
                {flatOrgs.map(({ org, depth }) => {
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
              className="size-4 cursor-pointer rounded border-slate-300 text-brand-600 focus:ring-2 focus:ring-brand-600/25 focus:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-50"
            />
            Kèm số điện thoại đầy đủ
            {!isAdmin && (
              <span className="text-xs text-slate-400">(chỉ admin có quyền — mục 7.3)</span>
            )}
          </label>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="secondary" onClick={() => void exportPdf()} loading={busy}>
              <FileText className="size-4" /> Xuất PDF (kèm dấu thời gian)
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
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-brand-600" />
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
              dùng, trạng thái. PDF được nhúng <b>dấu thời gian tin cậy RFC 3161</b> — chứng minh
              báo cáo tồn tại tại thời điểm TSA cấp dấu, không sửa được sau đó.
            </p>
          </div>
        </Card>
      </div>

      <Card title="Kiểm chứng dấu thời gian" className="mt-5">
        <div className="flex items-start gap-3 text-sm text-slate-600">
          <Clock className="mt-0.5 size-5 shrink-0 text-brand-600" />
          <div className="min-w-0 flex-1">
            <p>
              Tải lên file PDF báo cáo để kiểm tra dấu thời gian nhúng — xác nhận file tồn tại
              nguyên vẹn từ thời điểm TSA cấp dấu.
            </p>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              disabled={verifyBusy}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void verifyPdf(f);
              }}
              className="mt-3 block text-sm file:mr-3 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
            />
            {verifyBusy && <p className="mt-2 text-xs text-slate-400">Đang kiểm chứng…</p>}
            {verifyResult && (
              <div className="mt-3 space-y-1.5 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="break-all font-mono">SHA-256: {verifyResult.sha256}</div>
                {verifyResult.timestamped ? (
                  verifyResult.timestamps.map((ts, i) => (
                    <div key={i} className="space-y-0.5">
                      <div>
                        Thời điểm cấp dấu (genTime):{" "}
                        <b>{ts.gen_time ? new Date(ts.gen_time).toLocaleString("vi-VN") : "—"}</b>
                      </div>
                      <div>TSA: {ts.tsa_subject || "—"}</div>
                      <div className={ts.intact ? "text-emerald-600" : "text-red-600"}>
                        {ts.intact
                          ? "✓ Toàn vẹn — file không bị sửa kể từ thời điểm cấp dấu"
                          : "✗ Chữ ký timestamp không khớp — file đã bị thay đổi"}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-amber-600">File không có dấu thời gian nhúng.</div>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}