"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, FileUp, KeyRound, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { OfflineEnrollRequest, OfflineEnrollResponse } from "@/lib/types";
import { Button, Card, ErrorBanner, Field, PageHeader, Textarea } from "@/components/ui";

const SAMPLE_FINGERPRINT = {
  smbios_uuid: "4C4C4544-0042-3710-8048-B7C04F323634",
  machine_guid: "de0aa4a0cb4afdfde97c2ce5d4...",
  mainboard_serial: "abc123def456...",
};

/** Máy cách ly — Bước 1: admin proxy CSR ký ECDSA cho máy không gọi được server.
 *  Sau khi upload `enroll.json` từ USB → nhận `cert.json` (chứa client cert đã ký)
 *  → copy USB ngược về máy cách ly để cài cert qua `--install-cert`. */
export default function OfflineEnrollPage() {
  const [enrollJson, setEnrollJson] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OfflineEnrollResponse | null>(null);

  const fillSample = () => {
    setEnrollJson(
      JSON.stringify(
        {
          schema_version: 1,
          created_at: new Date().toISOString(),
          token: "t_SAMPLE_TOKEN_REPLACE",
          hostname: "PC-OFFLINE-01",
          fingerprint: SAMPLE_FINGERPRINT,
          csr_pem: "-----BEGIN CERTIFICATE REQUEST-----\nMIICiTCCAk....\n-----END CERTIFICATE REQUEST-----\n",
        },
        null,
        2,
      ),
    );
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const parsed = JSON.parse(enrollJson) as Record<string, unknown>;

      // Trích các field cần thiết từ file JSON sinh bởi `--enroll-offline`.
      // Hỗ trợ cả 2 dạng: file phẳng (chỉ có token/hostname/fingerprint/csr_pem)
      // và file có envelope `schema_version`/`created_at`.
      const body: OfflineEnrollRequest = {
        token: String(parsed.token ?? "").trim(),
        hostname: parsed.hostname ? String(parsed.hostname) : undefined,
        fingerprint: (parsed.fingerprint ?? {}) as OfflineEnrollRequest["fingerprint"],
        csr_pem: String(parsed.csr_pem ?? "").trim(),
      };
      if (!body.token || !body.csr_pem) {
        throw new ApiError(400, "File JSON thiếu token hoặc csr_pem");
      }

      const res = await api.post<OfflineEnrollResponse>("/offline/enroll", body);
      setResult(res);
    } catch (err) {
      if (err instanceof SyntaxError) setError("File JSON không hợp lệ");
      else setError(err instanceof ApiError ? err.detail : "Submit thất bại");
    } finally {
      setBusy(false);
    }
  };

  const downloadCertJson = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cert-${result.machine_id.slice(0, 8)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  return (
    <div>
      <PageHeader
        title="Enroll máy cách ly — Ký CSR (Bước 1)"
        description="Upload file enroll.json từ USB (do agent --enroll-offline sinh ra) → nhận cert.json → copy về máy cách ly để cài cert."
      />

      {error && <ErrorBanner message={error} />}
      {result && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          <div className="flex-1">
            <p className="font-semibold">Ký CSR thành công — máy {result.machine_id.slice(0, 8)}</p>
            <p className="mt-1 text-xs">
              is_new={String(result.is_new_machine)} · status={result.status} · CN sẽ là{" "}
              <code className="rounded bg-emerald-100 px-1">CN=machine-{result.machine_id}</code> (do server override).
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={downloadCertJson}>
                <FileUp className="size-4" /> Tải cert.json về USB
              </Button>
              <Link
                href={`/machines/${result.machine_id}`}
                className="inline-flex items-center gap-1 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-50"
              >
                Xem máy trên dashboard →
              </Link>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Upload file enroll.json từ USB">
          <div className="space-y-3">
            <Field
              label="Nội dung file enroll.json"
              required
              hint="File JSON do OrgInventoryAgent.exe --enroll-offline sinh ra trên máy cách ly (chứa token, hostname, fingerprint, csr_pem)"
            >
              <Textarea
                rows={14}
                value={enrollJson}
                onChange={(e) => setEnrollJson(e.target.value)}
                placeholder='{"token":"t_...", "hostname":"PC-ANPHU-01", "fingerprint":{...}, "csr_pem":"-----BEGIN CERTIFICATE REQUEST-----..."}'
                className="font-mono text-xs"
              />
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button variant="secondary" size="sm" onClick={fillSample}>
                Điền JSON mẫu
              </Button>
              <Button onClick={() => void submit()} loading={busy} disabled={!enrollJson}>
                <KeyRound className="size-4" /> Ký CSR & tạo cert.json
              </Button>
            </div>
          </div>
        </Card>

        <Card title="Quy trình 3 bước">
          <div className="space-y-3 text-sm text-slate-600">
            <p className="flex items-start gap-2">
              <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                1
              </span>
              <span>
                <b className="text-slate-800">Trên máy cách ly</b>: agent cài xong → chạy{" "}
                <code className="rounded bg-slate-100 px-1 text-[11px]">--enroll-offline E:\usb\enroll.json</code>
              </span>
            </p>
            <p className="flex items-start gap-2">
              <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                2
              </span>
              <span>
                <b className="text-slate-800">Trên máy admin có mạng</b>: copy file enroll.json từ USB →
                submit vào form bên trái → nhận <code className="rounded bg-slate-100 px-1 text-[11px]">cert.json</code>
              </span>
            </p>
            <p className="flex items-start gap-2">
              <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                3
              </span>
              <span>
                <b className="text-slate-800">Trên máy cách ly</b>: copy cert.json ngược về → chạy{" "}
                <code className="rounded bg-slate-100 px-1 text-[11px]">--install-cert</code>. Sau đó dùng{" "}
                <Link href="/offline-import" className="font-medium text-blue-600 hover:underline">
                  Import inventory
                </Link>{" "}
                cho các đợt tiếp theo.
              </span>
            </p>

            <p className="border-t border-slate-200 pt-3 text-xs text-slate-400">
              <ShieldCheck className="mr-1 inline-block size-3.5" />
              CSR dùng ECDSA P-256. Server override CN thành{" "}
              <code className="rounded bg-slate-100 px-1">machine-&lt;id&gt;</code>; agent không cần biết
              machine_id lúc ký.
            </p>
            <p className="text-xs text-slate-400">
              Hướng dẫn đầy đủ: <code>docs/RUNBOOK.md</code> mục 6 hoặc{" "}
              <code>docs/OFFLINE_AGENT_SPEC.md</code>.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
