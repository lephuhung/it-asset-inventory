"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, Download, FileArchive, FileUp, HardDriveDownload, Info, Lock, ShieldCheck, UploadCloud } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { OfflineImportResponse } from "@/lib/types";
import { Button, Card, ErrorBanner, Field, PageHeader, Textarea } from "@/components/ui";

const SAMPLE_PAYLOAD = {
  machine_uuid: "offline-demo-1",
  hostname: "PC-ISOLATED-01",
  fingerprint: { smbios_uuid: "DEMO-OFF-1", machine_guid: "DEMO-OFF-G-1" },
  spec: {
    os_name: "Windows 10",
    os_build: "19045",
    cpu: { model: "Intel Core i5-10400" },
    ram_gb: 8,
    disks: [{ model: "Samsung 870 EVO", size_bytes: 512110190592 }],
  },
  exported_at: new Date().toISOString(),
};

/** Chế độ máy cách ly (#12, Phase 3) — import file ký số hoặc gói ZIP mã hóa từ USB. */
export default function OfflineImportPage() {
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [payload, setPayload] = useState("");
  const [signature, setSignature] = useState("");
  const [pubkey, setPubkey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OfflineImportResponse | null>(null);
  const [showManual, setShowManual] = useState(false);

  const fillSample = () => {
    setPayload(JSON.stringify(SAMPLE_PAYLOAD, null, 2));
    setSignature("(dán chữ ký ECDSA base64 — sinh bởi agent khi xuất file)");
    setPubkey("(dán public key PEM — thường là client cert public key)");
  };

  const submitZip = async () => {
    if (!zipFile) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", zipFile);
      const res = await api.postForm<OfflineImportResponse>("/offline/import", fd);
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Giải mã hoặc xác thực gói ZIP thất bại");
    } finally {
      setBusy(false);
    }
  };

  const submitManual = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const parsed = JSON.parse(payload) as Record<string, unknown>;
      const res = await api.post<OfflineImportResponse>("/offline/import", {
        payload: parsed,
        signature_b64: signature.trim(),
        public_key_pem: pubkey.trim(),
      });
      setResult(res);
    } catch (err) {
      if (err instanceof SyntaxError) setError("Payload không phải JSON hợp lệ");
      else setError(err instanceof ApiError ? err.detail : "Import thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Import máy cách ly (Offline USB)"
        description="Nhập dữ liệu tài sản máy tính cách ly từ file ZIP mã hóa và ký số trên ổ USB"
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
        <Info className="mt-0.5 size-4 shrink-0" />
        <div className="space-y-1">
          <div>
            <strong>Quy trình 1-Click:</strong> Cắm USB vào máy cách ly → nháy đúp chuột vào <code>install-offline.cmd</code>.
          </div>
          <div className="text-xs text-blue-600">
            Kết quả trên USB sẽ là 1 file <code>INVENTORY_&lt;HOSTNAME&gt;_&lt;TIMESTAMP&gt;.zip</code> đã được mã hóa an toàn. Chọn file đó bên dưới để hệ thống tự động giải mã và cập nhật.
          </div>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {result && (
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600" />
          <div className="space-y-1">
            <div className="font-semibold text-emerald-900">
              Nhập dữ liệu máy tính thành công:{" "}
              <Link href={`/machines/${result.machine_id}`} className="underline hover:text-emerald-700">
                {result.hostname ?? result.machine_id.slice(0, 8)}
              </Link>
            </div>
            <div className="flex flex-wrap gap-2 text-xs text-emerald-700">
              <span className="rounded bg-emerald-100 px-2 py-0.5 font-medium">
                {result.is_new ? "Máy mới" : "Cập nhật cấu hình hiện có"}
              </span>
              <span className="rounded bg-emerald-100 px-2 py-0.5 font-medium flex items-center gap-1">
                <ShieldCheck className="size-3" /> Chữ ký ECDSA P-256: Hợp lệ
              </span>
              {result.decrypted && (
                <span className="rounded bg-emerald-100 px-2 py-0.5 font-medium flex items-center gap-1">
                  <Lock className="size-3" /> Đã giải mã bảo mật AES-GCM + RSA
                </span>
              )}
              {result.apps_count !== undefined && result.apps_count !== null && (
                <span className="rounded bg-emerald-100 px-2 py-0.5 font-medium">
                  {result.apps_count} phần mềm đã ghi nhận
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* Card chính: Upload 1-Click ZIP */}
          <Card title="1. Tải lên gói ZIP từ USB (Khuyến nghị)">
            <div className="space-y-4">
              <div className="rounded-lg border-2 border-dashed border-slate-300 p-6 text-center hover:border-blue-400 transition bg-slate-50/50">
                <FileArchive className="mx-auto size-10 text-slate-400 mb-2" />
                <label className="cursor-pointer">
                  <span className="block text-sm font-semibold text-slate-700 mb-1">
                    {zipFile ? zipFile.name : "Chọn file ZIP kết quả từ ổ USB"}
                  </span>
                  <span className="block text-xs text-slate-500 mb-3">
                    Định dạng: INVENTORY_&lt;TÊN_MÁY&gt;_&lt;NGÀY_GIỜ&gt;.zip
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-md bg-white border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
                    <UploadCloud className="size-3.5 text-blue-600" /> Chọn file từ USB
                  </span>
                  <input
                    type="file"
                    accept=".zip"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        setZipFile(e.target.files[0]);
                      }
                    }}
                  />
                </label>
              </div>

              {zipFile && (
                <div className="flex items-center justify-between rounded-lg bg-blue-50/80 px-3 py-2 text-xs text-blue-800 border border-blue-200">
                  <div className="flex items-center gap-2">
                    <FileArchive className="size-4 text-blue-600" />
                    <span><b>{zipFile.name}</b> ({(zipFile.size / 1024).toFixed(1)} KB)</span>
                  </div>
                  <Button onClick={() => void submitZip()} loading={busy} size="sm">
                    <Lock className="size-3.5" /> Giải mã & Nhập dữ liệu
                  </Button>
                </div>
              )}
            </div>
          </Card>

          {/* Card phụ: Nhập thủ công */}
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowManual(!showManual)}
              className="text-xs font-medium text-slate-500 hover:text-slate-800 underline"
            >
              {showManual ? "Ẩn tùy chọn nhập JSON thủ công" : "▸ Hiển thị tùy chọn nhập JSON thủ công (dành cho kiểm thử)"}
            </button>

            {showManual && (
              <div className="mt-3">
                <Card title="Nhập chuỗi JSON thủ công">
                  <div className="space-y-3">
                    <Field label="Payload (JSON)" required hint="Cấu trúc: machine_uuid, hostname, fingerprint, spec, exported_at">
                      <Textarea
                        rows={6}
                        value={payload}
                        onChange={(e) => setPayload(e.target.value)}
                        placeholder='{"machine_uuid": "...", "hostname": "...", "fingerprint": {...}, "spec": {...}}'
                        className="font-mono text-xs"
                      />
                    </Field>
                    <Field label="Chữ ký (signature_b64)" required hint="ECDSA-SHA256 trên JSON canonical">
                      <Textarea rows={2} value={signature} onChange={(e) => setSignature(e.target.value)} className="font-mono text-xs" />
                    </Field>
                    <Field label="Khóa công khai (public_key_pem)" required hint="ECDSA Public Key PEM">
                      <Textarea rows={3} value={pubkey} onChange={(e) => setPubkey(e.target.value)} className="font-mono text-xs" />
                    </Field>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Button variant="secondary" size="sm" onClick={fillSample}>
                        Điền payload mẫu
                      </Button>
                      <Button onClick={() => void submitManual()} loading={busy} disabled={!payload || !signature || !pubkey}>
                        <HardDriveDownload className="size-4" /> Kiểm tra & Import
                      </Button>
                    </div>
                  </div>
                </Card>
              </div>
            )}
          </div>
        </div>

        {/* Cột thông tin hỗ trợ */}
        <Card title="Gói USB & Bảo mật">
          <div className="space-y-4 text-xs text-slate-600">
            <div>
              <h4 className="font-semibold text-slate-800 mb-1 flex items-center gap-1.5">
                <Download className="size-3.5 text-amber-600" /> Tải gói cài đặt USB
              </h4>
              <p className="mb-2 text-slate-500">
                Chưa có gói cài đặt? Tải <b>file ZIP không mật khẩu</b> để giải nén vào USB:
              </p>
              <a
                href="/api/downloads/offline-package.zip"
                download="offline-package.zip"
                className="flex items-center justify-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1.5 font-semibold text-amber-800 hover:bg-amber-100 transition"
              >
                <Download className="size-3" /> Tải Gói USB (.zip không password)
              </a>
            </div>

            <hr className="border-slate-200" />

            <div>
              <h4 className="font-semibold text-slate-800 mb-1 flex items-center gap-1.5">
                <ShieldCheck className="size-3.5 text-emerald-600" /> Bảo mật 2 Lớp
              </h4>
              <ul className="list-disc pl-4 space-y-1 text-slate-500">
                <li><b>Toàn vẹn:</b> Dữ liệu ký số ECDSA P-256 (bị sửa đổi sẽ bị từ chối).</li>
                <li><b>Bảo mật:</b> Mã hóa lai AES-256-GCM với khóa RSA của Server (chỉ Server mới giải mã được, an toàn trên USB).</li>
              </ul>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}