"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import { Check, Copy, KeyRound, ShieldCheck, Terminal } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { SelfServiceInfo, TokenCreateResponse } from "@/lib/types";
import { Button, Card, Field, Input, Spinner } from "@/components/ui";
import { LogoMark } from "@/components/logo";
import { OsPicker, type OsId } from "@/components/os-picker";

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Button variant="secondary" size="sm" onClick={() => void copy()}>
      {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
      {copied ? "Đã copy" : label}
    </Button>
  );
}

/**
 * Trang công khai (chế độ B — tự khai báo): người dùng nhập thông tin → nhận
 * lệnh cài đặt 1 dòng. Không cần đăng nhập.
 */
export default function EnrollPage() {
  const params = useParams<{ code: string }>();
  const code = params.code;

  const [info, setInfo] = useState<SelfServiceInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fullName, setFullName] = useState("");
  const [department, setDepartment] = useState("");
  const [position, setPosition] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [result, setResult] = useState<TokenCreateResponse | null>(null);
  const [resultOs, setResultOs] = useState<OsId>("windows");

  const loadInfo = useCallback(async () => {
    try {
      const i = await api.get<SelfServiceInfo>(`/self-service/${code}`);
      setInfo(i);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Link không hợp lệ");
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    void loadInfo();
  }, [loadInfo]);

  const claim = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const res = await api.post<TokenCreateResponse>(`/self-service/${code}/claim`, {
        full_name: fullName,
        department: department || null,
        position: position || null,
        email: email || null,
        phone: phone || null,
        note: note || null,
      });
      setResult(res);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không đăng ký được");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-xl">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-2xl bg-brand-600 shadow-lg shadow-brand-600/25">
            <LogoMark size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Đăng ký máy tính</h1>
          <p className="mt-1 text-sm text-slate-500">
            {loading ? "Đang kiểm tra link…" : info ? `Đơn vị: ${info.org_name}` : "Link tự khai báo"}
          </p>
        </div>

        {loading ? (
          <Card>
            <Spinner label="Đang kiểm tra link…" />
          </Card>
        ) : error ? (
          <Card>
            <p className="text-sm text-rose-600">{error}</p>
            <p className="mt-2 text-xs text-slate-500">
              Liên hệ quản trị viên tổ chức để nhận link đăng ký hợp lệ.
            </p>
          </Card>
        ) : result ? (
          <Card>
            <div className="mb-4 flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <Check className="mt-0.5 size-5 shrink-0 text-emerald-600" />
              <div className="text-sm text-emerald-800">
                <p className="font-semibold">Đăng ký thành công!</p>
                <p className="mt-0.5 text-xs">
                  Chọn hệ điều hành máy đích để lấy đúng lệnh cài đặt:
                </p>
              </div>
            </div>
            <OsPicker value={resultOs} onChange={setResultOs} hideOffline />
            <div className="mt-3">
              {resultOs === "windows" && result.install_command_windows && (
                <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-3">
                  <div className="mb-2 flex items-center gap-1.5">
                    <Terminal className="size-3.5 text-blue-600" />
                    <p className="text-xs font-semibold text-slate-700">
                      PowerShell (Run as Administrator):
                    </p>
                  </div>
                  <code className="block break-all rounded-md border border-emerald-200 bg-emerald-50 p-2 font-mono text-[11px] leading-relaxed text-emerald-900">
                    {result.install_command_windows}
                  </code>
                  <div className="mt-2 flex justify-end">
                    <CopyButton text={result.install_command_windows} label="Copy lệnh Windows" />
                  </div>
                </div>
              )}

              {resultOs === "linux" && result.install_command_linux && (
                <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-3">
                  <div className="mb-2 flex items-center gap-1.5">
                    <Terminal className="size-3.5 text-amber-600" />
                    <p className="text-xs font-semibold text-slate-700">
                      Terminal (sudo) — Ubuntu / Debian / RHEL / Rocky:
                    </p>
                  </div>
                  <code className="block break-all rounded-md border border-emerald-200 bg-emerald-50 p-2 font-mono text-[11px] leading-relaxed text-emerald-900">
                    {result.install_command_linux}
                  </code>
                  <div className="mt-2 flex justify-end">
                    <CopyButton text={result.install_command_linux} label="Copy lệnh Linux" />
                  </div>
                </div>
              )}
            </div>
            <div className="mt-4 rounded-lg bg-slate-50 px-3 py-2.5 text-xs leading-relaxed text-slate-600">
              <p className="flex items-center gap-1.5">
                <KeyRound className="size-3.5 shrink-0" />
                Lệnh có hiệu lực 72 giờ, dùng 1 lần. Agent sau khi cài sẽ tự đăng ký (enroll) và
                gửi heartbeat định kỳ.
              </p>
              <p className="mt-1.5 flex items-start gap-1.5">
                <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
                Dữ liệu thu thập chỉ gồm cấu hình máy, trạng thái bật/tắt, người dùng đăng nhập —
                không giám sát cá nhân (xem Thông báo tuân thủ của đơn vị).
              </p>
            </div>
          </Card>
        ) : (
          <Card>
            <p className="mb-4 text-sm text-slate-600">
              Nhập thông tin người dùng máy — sau khi đăng ký bạn nhận được lệnh cài đặt 1 dòng.
            </p>
            <form onSubmit={claim} className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Họ tên" required>
                  <Input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Nguyễn Văn A" required />
                </Field>
                <Field label="Phòng ban">
                  <Input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Kế toán" />
                </Field>
                <Field label="Chức vụ">
                  <Input value={position} onChange={(e) => setPosition(e.target.value)} placeholder="Chuyên viên" />
                </Field>
                <Field label="Số điện thoại (tùy chọn)" hint="Mã hóa khi lưu, mặc định mask">
                  <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0983…" />
                </Field>
              </div>
              <Field label="Email">
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="a@example.gov.vn" />
              </Field>
              <Field label="Ghi chú">
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Vị trí đặt máy…" />
              </Field>
              {formError && <p className="text-sm text-rose-600">{formError}</p>}
              <Button type="submit" className="w-full" loading={submitting} disabled={!fullName}>
                Nhận lệnh cài đặt
              </Button>
            </form>
          </Card>
        )}

        <p className="mt-6 text-center text-xs text-slate-400">
          Hệ thống quản lý tài sản máy tính — đăng ký này chỉ phục vụ quản lý tài sản của đơn vị.
        </p>
      </div>
    </div>
  );
}