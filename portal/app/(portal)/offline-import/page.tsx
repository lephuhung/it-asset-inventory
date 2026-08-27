"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, FileUp, HardDriveDownload, Info } from "lucide-react";
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

/** Chế độ máy cách ly (#12, Phase 3) — import file ký số từ USB. */
export default function OfflineImportPage() {
  const [payload, setPayload] = useState("");
  const [signature, setSignature] = useState("");
  const [pubkey, setPubkey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OfflineImportResponse | null>(null);

  const fillSample = () => {
    setPayload(JSON.stringify(SAMPLE_PAYLOAD, null, 2));
    setSignature("(dán chữ ký ECDSA base64 — sinh bởi agent khi xuất file)");
    setPubkey("(dán public key PEM — thường là client cert public key)");
  };

  const submit = async () => {
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
        description="Mạng nội bộ không ra internet → agent ghi inventory ra file ký số, cán bộ copy USB import vào đây (#12)"
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
        <Info className="mt-0.5 size-4 shrink-0" />
        <div>
          <strong>Lưu ý:</strong> trước khi import inventory, máy cách ly phải được <b>enroll</b> (ký
          CSR) trước — xem{" "}
          <Link href="/offline-enroll" className="font-semibold underline">
            Máy cách ly — Ký CSR (Bước 1)
          </Link>
          . Trang này dùng cho <b>bước 3</b> trong quy trình (nhập các đợt inventory định kỳ).
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {result && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          <span>
            Import thành công — máy{" "}
            <Link href={`/machines/${result.machine_id}`} className="font-semibold underline">
              {result.hostname ?? result.machine_id.slice(0, 8)}
            </Link>{" "}
            ({result.is_new ? "máy mới" : "cập nhật máy có sẵn"}, chữ ký hợp lệ).
          </span>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="File import (JSON đã ký)">
          <div className="space-y-3">
            <Field label="Payload (JSON)" required hint="Cấu trúc: machine_uuid, hostname, fingerprint, spec, exported_at">
              <Textarea
                rows={10}
                value={payload}
                onChange={(e) => setPayload(e.target.value)}
                placeholder='{"machine_uuid": "...", "hostname": "...", "fingerprint": {...}, "spec": {...}}'
                className="font-mono text-xs"
              />
            </Field>
            <Field label="Chữ ký (signature_b64)" required hint="ECDSA-SHA256 trên JSON canonical của payload — do agent ký bằng private key client cert">
              <Textarea rows={2} value={signature} onChange={(e) => setSignature(e.target.value)} className="font-mono text-xs" />
            </Field>
            <Field label="Khóa công khai (public_key_pem)" required hint="Public key tương ứng (từ client cert của máy)">
              <Textarea rows={4} value={pubkey} onChange={(e) => setPubkey(e.target.value)} className="font-mono text-xs" />
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button variant="secondary" size="sm" onClick={fillSample}>
                Điền payload mẫu
              </Button>
              <Button onClick={() => void submit()} loading={busy} disabled={!payload || !signature || !pubkey}>
                <HardDriveDownload className="size-4" /> Kiểm tra chữ ký & import
              </Button>
            </div>
          </div>
        </Card>

        <Card title="Cách hoạt động">
          <div className="space-y-3 text-sm text-slate-600">
            <p className="flex items-start gap-2">
              <FileUp className="mt-0.5 size-4 shrink-0 text-blue-600" />
              <span>
                Agent ở mạng cách ly xuất file inventory <b>ký ECDSA</b> bằng private key của
                client cert — server <b>verify chữ ký trước khi ghi</b>; file bị sửa sẽ bị từ chối.
              </span>
            </p>
            <p className="text-xs text-slate-400">
              Trong triển khai thực tế, format chuẩn là <b>CMS/PKCS#7</b> (xem PLAN_THUC_HIEN Phase
              3 tuần 15–16). Bản này nhận chữ ký ECDSA trực tiếp để dễ tích hợp.
            </p>
            <p className="text-xs text-slate-400">
              Máy import có trạng thái <b>offline</b> (không kết nối mạng được) — khi máy ra mạng
              và gửi heartbeat, trạng thái tự cập nhật online.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}