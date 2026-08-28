"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  Download,
  FileArchive,
  HardDriveDownload,
  HardDriveUpload,
  Info,
  Lock,
  Mail,
  Monitor,
  Phone,
  Plug,
  ShieldCheck,
  UploadCloud,
  Usb,
  User,
  UserCheck,
  UserPlus,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  AssignUserMode,
  AssignUserRequest,
  AssignUserResponse,
  ManagedUser,
  OfflineImportResponse,
} from "@/lib/types";
import { Button, Card, ErrorBanner, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";

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

/** Trang Import máy BMNN — có Timeline 3 pha rõ ràng cho người vận hành. */
export default function OfflineImportPage() {
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [payload, setPayload] = useState("");
  const [signature, setSignature] = useState("");
  const [pubkey, setPubkey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OfflineImportResponse | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [showGuide, setShowGuide] = useState(true); // timeline mặc định mở

  // Assign-user form state (chỉ active khi có `result`)
  const [assignMode, setAssignMode] = useState<AssignUserMode>("existing");
  const [existingUsers, setExistingUsers] = useState<ManagedUser[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [newFullName, setNewFullName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newDepartment, setNewDepartment] = useState("");
  const [assignNote, setAssignNote] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [assignResult, setAssignResult] = useState<AssignUserResponse | null>(null);

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

  // Khi upload thành công → load danh sách user cùng org để admin gán.
  // Reset state assign khi reset result.
  useEffect(() => {
    if (!result || !result.org_id) {
      setExistingUsers([]);
      setSelectedUserId("");
      setAssignResult(null);
      setAssignError(null);
      setNewFullName("");
      setNewEmail("");
      setNewPhone("");
      setNewDepartment("");
      setAssignNote("");
      return;
    }
    // Nếu đã có user gán sẵn → set mặc định selectedUserId
    if (result.assigned_user_id) {
      setSelectedUserId(result.assigned_user_id);
      setAssignResult({
        machine_id: result.machine_id,
        assigned_user_id: result.assigned_user_id,
        assigned_user_name: result.assigned_user_name ?? "",
        assigned_user_email: result.assigned_user_email ?? "",
        phone_masked: null,
        was_created: false,
      });
    }
    // Load danh sách user cùng org
    (async () => {
      try {
        const users = await api.get<ManagedUser[]>(`/users?org_id=${result.org_id}`);
        setExistingUsers(users);
        if (!result.assigned_user_id && (users?.length ?? 0) > 0) {
          setSelectedUserId(users[0].id);
        }
      } catch (err) {
        // Không block flow chính nếu load users fail
        console.error("Load users failed:", err);
      }
    })();
  }, [result?.machine_id]);

  const submitAssignUser = async () => {
    if (!result) return;
    setAssignBusy(true);
    setAssignError(null);
    setAssignResult(null);
    try {
      let body: AssignUserRequest;
      if (assignMode === "existing") {
        if (!selectedUserId) throw new ApiError(400, "Chọn user trong danh sách");
        body = { mode: "existing", user_id: selectedUserId, note: assignNote || undefined };
      } else {
        if (!newFullName.trim() || !newEmail.trim()) {
          throw new ApiError(400, "Nhập họ tên và email");
        }
        body = {
          mode: "new",
          full_name: newFullName.trim(),
          email: newEmail.trim(),
          phone: newPhone.trim() || undefined,
          department: newDepartment.trim() || undefined,
          note: assignNote || undefined,
        };
      }
      const res = await api.post<AssignUserResponse>(
        `/machines/${result.machine_id}/assign-user`,
        body,
      );
      setAssignResult(res);
    } catch (err) {
      setAssignError(err instanceof ApiError ? err.detail : "Gán người dùng thất bại");
    } finally {
      setAssignBusy(false);
    }
  };

  const unassignUser = async () => {
    if (!result) return;
    if (!confirm("Gỡ người dùng khỏi máy này?")) return;
    setAssignBusy(true);
    setAssignError(null);
    try {
      await api.delete(`/machines/${result.machine_id}/assign-user`);
      setAssignResult(null);
      setSelectedUserId("");
      // Refresh kết quả để cập nhật assigned_user_id
      // (đơn giản: set lại result không có assigned_user_*)
      setResult({ ...result, assigned_user_id: null, assigned_user_name: null, assigned_user_email: null });
    } catch (err) {
      setAssignError(err instanceof ApiError ? err.detail : "Gỡ thất bại");
    } finally {
      setAssignBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Import máy BMNN (Offline USB)"
        description="Nhập dữ liệu tài sản máy tính cách ly từ file ZIP mã hóa và ký số trên ổ USB"
      />

      {/* ── TIMELINE 4 PHA — HƯỚNG DẪN CHO NGƯỜI VẬN HÀNH ─────────────── */}
      <Card
        title={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="size-4 text-blue-600" />
              <span>Quy trình 4 pha cho máy BMNN</span>
              <span className="text-xs font-normal text-slate-500">
                (tổng thời gian ~5-7 phút, ZIP file cố định — chỉ nhập user info khi upload)
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowGuide(!showGuide)}
              className="text-xs font-medium text-slate-500 hover:text-slate-800 flex items-center gap-1"
            >
              {showGuide ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
              {showGuide ? "Thu gọn" : "Mở rộng"}
            </button>
          </div>
        }
      >
        {showGuide && (
          <ol className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <PhaseCard
              phase={1}
              icon={<HardDriveDownload className="size-5 text-amber-600" />}
              title="Admin chuẩn bị USB"
              location="Máy Admin (có mạng)"
              color="amber"
              steps={[
                "Tạo token enroll cho org của máy BMNN (trang Tokens).",
                <>Tải gói ZIP <b>không mật khẩu</b>: <DownloadLink href="/api/downloads/offline-package.zip" label="offline-package.zip" /></>,
                "Giải nén vào thư mục gốc USB (vd E:\\).",
                "(Tuỳ chọn) Điền token vào file offline_config.json.",
              ]}
            />
            <PhaseCard
              phase={2}
              icon={<Monitor className="size-5 text-blue-600" />}
              title="User thu thập trên máy BMNN"
              location="Máy BMNN (air-gapped)"
              color="blue"
              steps={[
                "Cắm USB vào máy BMNN.",
                <>Nháy đúp chuột vào <Code>install-offline.cmd</Code>.</>,
                "Chờ 15-30 giây (UAC → verify MSI → cài agent → ký số + mã hoá).",
                "Rút USB khi thấy thông báo xanh 'Đã hoàn tất'.",
              ]}
            />
            <PhaseCard
              phase={3}
              icon={<HardDriveUpload className="size-5 text-emerald-600" />}
              title="Admin upload ZIP lên Portal"
              location="Máy Admin (có mạng)"
              color="emerald"
              steps={[
                "Cắm USB vào máy Admin.",
                "Mở trang này (đang ở đây).",
                "Chọn file INVENTORY_*.zip từ USB → bấm Giải mã.",
                "Server xác thực chữ ký + parse vào DB.",
              ]}
            />
            <PhaseCard
              phase={4}
              icon={<UserCheck className="size-5 text-violet-600" />}
              title="Gán người sử dụng"
              location="Trên trang này (sau upload)"
              color="violet"
              steps={[
                <>Sau khi upload thành công, form <b>“Gán người dùng”</b> xuất hiện ngay bên dưới.</>,
                <>Chọn <b>user có sẵn</b> trong cùng tổ chức — hoặc <b>tạo mới</b> (chỉ cần họ tên + email).</>,
                <>Phone mã hoá AES-256-GCM. User mới tạo với role <b>viewer</b>, chưa có mật khẩu.</>,
                "Sau gán, máy xuất hiện trong danh sách với tên người dùng.",
              ]}
            />
          </ol>
        )}

        {/* Băng chuyền flow trực quan */}
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-slate-600">
            <Badge color="amber">Pha 1: Admin + USB</Badge>
            <ArrowRight className="size-3 text-slate-400" />
            <Badge color="blue">Pha 2: Cách ly</Badge>
            <ArrowRight className="size-3 text-slate-400 rotate-180" />
            <Badge color="slate">USB</Badge>
            <ArrowRight className="size-3 text-slate-400" />
            <Badge color="emerald">Pha 3: Upload</Badge>
            <ArrowRight className="size-3 text-slate-400" />
            <Badge color="violet">Pha 4: Gán user</Badge>
            <span className="ml-2 text-slate-400">|</span>
            <span>Tổng: <b>~5-7 phút</b></span>
            <span className="ml-2 text-slate-400">|</span>
            <span>Không cần mạng từ máy BMNN ra server</span>
          </div>
        </div>
      </Card>

      {/* ── BANNER HƯỚNG DẪN NHANH ────────────────────────────────────────── */}
      <div className="mt-4 mb-4 flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
        <Info className="mt-0.5 size-4 shrink-0" />
        <div className="space-y-1">
          <div>
            <strong>ZIP cố định, không cần tạo lại.</strong> Cắm USB vào máy BMNN → nháy đúp chuột vào <Code>install-offline.cmd</Code> → xuất hiện file <Code>INVENTORY_*.zip</Code>. Mang file đó về máy admin có mạng, upload lên trang này.
          </div>
          <div className="text-xs text-blue-600">
            <b>Sau khi upload thành công</b>, form <b>“Gán người dùng”</b> xuất hiện ngay — nhập họ tên + email người sẽ dùng máy này để hoàn tất.
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

          {/* ── Bước 2: Gán người sử dụng cho máy ─────────────────────── */}
          <Card title="2. Gán người sử dụng cho máy (Khuyến nghị làm ngay)">
            <div className="space-y-4">
              {assignResult ? (
                <div className="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  <UserCheck className="mt-0.5 size-5 shrink-0 text-emerald-600" />
                  <div className="flex-1 space-y-1">
                    <div className="font-semibold text-emerald-900">
                      Đã gán người dùng: {assignResult.assigned_user_name}
                      {assignResult.was_created && (
                        <span className="ml-2 rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-medium text-blue-700">
                          user mới tạo
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-emerald-700">
                      Email: {assignResult.assigned_user_email}
                      {assignResult.phone_masked && (
                        <span className="ml-3">SĐT: {assignResult.phone_masked}</span>
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <Link
                        href={`/machines/${assignResult.machine_id}`}
                        className="rounded border border-emerald-300 bg-white px-2 py-1 font-semibold text-emerald-700 hover:bg-emerald-50"
                      >
                        Xem máy trên dashboard →
                      </Link>
                      <button
                        type="button"
                        onClick={() => void unassignUser()}
                        disabled={assignBusy}
                        className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-600 hover:bg-slate-50"
                      >
                        Gỡ người dùng
                      </button>
                      <button
                        type="button"
                        onClick={() => setAssignResult(null)}
                        className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-600 hover:bg-slate-50"
                      >
                        Đổi người dùng khác
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1 text-xs">
                    <button
                      type="button"
                      onClick={() => setAssignMode("existing")}
                      className={`flex flex-1 items-center justify-center gap-1.5 rounded px-3 py-1.5 font-medium transition ${
                        assignMode === "existing"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-500 hover:text-slate-800"
                      }`}
                    >
                      <User className="size-3.5" /> Chọn user có sẵn
                    </button>
                    <button
                      type="button"
                      onClick={() => setAssignMode("new")}
                      className={`flex flex-1 items-center justify-center gap-1.5 rounded px-3 py-1.5 font-medium transition ${
                        assignMode === "new"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-500 hover:text-slate-800"
                      }`}
                    >
                      <UserPlus className="size-3.5" /> Tạo user mới
                    </button>
                  </div>

                  {assignError && <ErrorBanner message={assignError} />}

                  {assignMode === "existing" ? (
                    <div className="space-y-3">
                      {(existingUsers?.length ?? 0) === 0 ? (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 flex items-start gap-2">
                          <Info className="mt-0.5 size-3.5 shrink-0" />
                          <span>
                            Chưa có user nào trong tổ chức <code>{result?.org_id?.slice(0, 8) ?? "?"}</code>.
                            Chuyển sang tab <b>Tạo user mới</b>.
                          </span>
                        </div>
                      ) : (
                        <Field label="Người dùng" required>
                          <Select
                            value={selectedUserId}
                            onChange={(e) => setSelectedUserId(e.target.value)}
                          >
                            <option value="">— Chọn user —</option>
                            {existingUsers.map((u) => (
                              <option key={u.id} value={u.id}>
                                {u.full_name} ({u.email})
                              </option>
                            ))}
                          </Select>
                        </Field>
                      )}
                      <Field label="Ghi chú (tùy chọn)" hint="VD: gán thay cho máy cũ bị thu hồi">
                        <Input
                          value={assignNote}
                          onChange={(e) => setAssignNote(e.target.value)}
                          placeholder="Lý do gán / thông tin bàn giao..."
                        />
                      </Field>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="Họ và tên" required>
                          <Input
                            value={newFullName}
                            onChange={(e) => setNewFullName(e.target.value)}
                            placeholder="Nguyễn Văn A"
                          />
                        </Field>
                        <Field label="Email" required hint="Dùng email cơ quan — không trùng user khác">
                          <Input
                            type="email"
                            value={newEmail}
                            onChange={(e) => setNewEmail(e.target.value)}
                            placeholder="a@coquan.gov.vn"
                          />
                        </Field>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="Số điện thoại" hint="Mã hóa AES-256-GCM khi lưu">
                          <Input
                            value={newPhone}
                            onChange={(e) => setNewPhone(e.target.value)}
                            placeholder="0987654321"
                          />
                        </Field>
                        <Field label="Phòng/Ban" hint="Lưu trên token enroll (tham khảo)">
                          <Input
                            value={newDepartment}
                            onChange={(e) => setNewDepartment(e.target.value)}
                            placeholder="Phòng Kế toán"
                          />
                        </Field>
                      </div>
                      <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 flex items-start gap-2">
                        <Info className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                          Tạo với role <b>viewer</b>, chưa có mật khẩu — user sẽ tự reset qua
                          email (admin dùng <code>POST /api/users/&#123;id&#125;/reset-password</code>).
                        </span>
                      </div>
                    </div>
                  )}

                  <Button
                    onClick={() => void submitAssignUser()}
                    loading={assignBusy}
                    disabled={
                      (assignMode === "existing" && !selectedUserId) ||
                      (assignMode === "new" && (!newFullName.trim() || !newEmail.trim()))
                    }
                  >
                    <UserCheck className="size-4" /> Gán người dùng
                  </Button>
                </>
              )}
            </div>
          </Card>
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
                    Định dạng: <Code>INVENTORY_&lt;TÊN_MÁY&gt;_&lt;NGÀY_GIỜ&gt;.zip</Code>
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
                    <Lock className="size-3.5" /> Giải mã &amp; Nhập dữ liệu
                  </Button>
                </div>
              )}
            </div>
          </Card>

          {/* Card phụ: Checklist trước khi upload */}
          <Card title="✓ Checklist trước khi upload">
            <ul className="space-y-2 text-xs text-slate-700">
              <CheckItem ok={!!zipFile}>
                Đã chọn file <Code>INVENTORY_*.zip</Code> từ USB
              </CheckItem>
              <CheckItem>
                File ZIP <b>không bị sửa</b> trên USB (copy từ USB gốc, không giải nén)
              </CheckItem>
              <CheckItem>
                Token enroll (nếu có) đã dùng cho đúng org của đơn vị (xem cột bên phải)
              </CheckItem>
              <CheckItem>
                Đã có quyền admin trên Portal (xem tên user ở góc phải)
              </CheckItem>
            </ul>
          </Card>

          {/* Card phụ: Troubleshooting */}
          <Card title="⚠ Xử lý sự cố thường gặp">
            <div className="space-y-3 text-xs text-slate-700">
              <TroubleItem
                symptom="Báo lỗi 'Chữ ký không hợp lệ'"
                cause="File ZIP bị sửa giữa máy BMNN ↔ Admin (USB lỗi sector)"
                fix="Cắm USB lại máy BMNN → nháy đúp install-offline.cmd lần nữa → upload lại."
              />
              <TroubleItem
                symptom="Upload OK nhưng máy không xuất hiện"
                cause="Token thuộc org khác với org của admin"
                fix="Kiểm tra org của token (trang Tokens) trùng với org của đơn vị đang xem."
              />
              <TroubleItem
                symptom="Lỗi 'Không tìm thấy encrypted_payload.bin'"
                cause="File ZIP không phải do install-offline.cmd sinh ra"
                fix="Đảm bảo dùng đúng script từ gói offline-package.zip tải từ Portal."
              />
              <TroubleItem
                symptom="Script dừng với 'Mã băm SHA256 KHÔNG khớp'"
                cause="MSI bị hỏng trên USB"
                fix={<>
                  Copy lại MSI từ share nội bộ (<Code>\\fileserver\Releases\OrgInventory\</Code>).
                </>}
              />
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
                        <HardDriveDownload className="size-4" /> Kiểm tra &amp; Import
                      </Button>
                    </div>
                  </div>
                </Card>
              </div>
            )}
          </div>
        </div>

        {/* Cột thông tin hỗ trợ */}
        <div className="space-y-4">
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

          <Card title="Cấu trúc file ZIP trên USB">
            <ol className="space-y-2 text-xs text-slate-700 list-decimal pl-4">
              <li><Usb className="inline size-3 mr-1 text-amber-600" /><Code>install-offline.cmd</Code> — Launcher</li>
              <li><Code>install-offline.ps1</Code> — Script chính</li>
              <li><Lock className="inline size-3 mr-1 text-emerald-600" /><Code>server_public_key.pem</Code> — Khoá công khai Server</li>
              <li><Code>offline_config.json</Code> — Cấu hình mẫu</li>
              <li><Code>OrgInventoryAgent.msi</Code> — Installer (nếu có)</li>
              <li><Code>OrgInventoryAgent.msi.sha256</Code> — SHA-256 verify</li>
            </ol>
            <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800 flex gap-1">
              <AlertTriangle className="size-3 mt-0.5 shrink-0" />
              <span>USB KHÔNG cần mang <code>OrgInventoryAgent.msi</code> nếu máy BMNN đã cài agent trước đó. Script tự phát hiện và bỏ qua.</span>
            </div>
          </Card>

          <Card title="File ZIP do agent xuất ra">
            <ol className="space-y-2 text-xs text-slate-700 list-decimal pl-4">
              <li><Code>manifest.json</Code> — Metadata (machine_uuid, hostname)</li>
              <li><Lock className="inline size-3 mr-1 text-emerald-600" /><Code>encrypted_payload.bin</Code> — Inventory mã hoá AES-GCM</li>
              <li><Lock className="inline size-3 mr-1 text-emerald-600" /><Code>encrypted_key.bin</Code> — Khoá AES mã hoá bằng RSA</li>
              <li><Code>iv.bin</Code> + <Code>tag.bin</Code> — Tham số AES-GCM</li>
              <li><ShieldCheck className="inline size-3 mr-1 text-blue-600" /><Code>signature.sig</Code> — ECDSA P-256 DER</li>
              <li><Code>public_key.pem</Code> — Khoá ECDSA của máy BMNN</li>
            </ol>
            <div className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-[11px] text-emerald-800">
              <Lock className="inline size-3 mr-1" />
              ZIP <b>không có password</b> — chỉ là vật chứa; nội dung đã mã hoá bên trong.
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────

function PhaseCard({
  phase,
  icon,
  title,
  location,
  color,
  steps,
}: {
  phase: number;
  icon: React.ReactNode;
  title: string;
  location: string;
  color: "amber" | "blue" | "emerald" | "violet";
  steps: React.ReactNode[];
}) {
  const colors = {
    amber: { border: "border-amber-300", bg: "bg-amber-50", dot: "bg-amber-500", text: "text-amber-700" },
    blue: { border: "border-blue-300", bg: "bg-blue-50", dot: "bg-blue-500", text: "text-blue-700" },
    emerald: { border: "border-emerald-300", bg: "bg-emerald-50", dot: "bg-emerald-500", text: "text-emerald-700" },
    violet: { border: "border-violet-300", bg: "bg-violet-50", dot: "bg-violet-500", text: "text-violet-700" },
  }[color];

  return (
    <li className={`rounded-lg border ${colors.border} ${colors.bg} p-4 space-y-2`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`flex size-7 items-center justify-center rounded-full ${colors.dot} text-white text-xs font-bold`}>
            {phase}
          </div>
          {icon}
          <span className="text-sm font-semibold text-slate-800">{title}</span>
        </div>
      </div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500 flex items-center gap-1">
        <Plug className="size-3" />
        {location}
      </div>
      <ol className="space-y-1.5 text-xs text-slate-700 list-decimal pl-5 marker:text-slate-400">
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    </li>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-800">
      {children}
    </code>
  );
}

function Badge({
  children,
  color = "slate",
}: {
  children: React.ReactNode;
  color?: "amber" | "blue" | "emerald" | "slate" | "violet";
}) {
  const cls = {
    amber: "border-amber-200 bg-amber-100 text-amber-800",
    blue: "border-blue-200 bg-blue-100 text-blue-800",
    emerald: "border-emerald-200 bg-emerald-100 text-emerald-800",
    slate: "border-slate-200 bg-slate-100 text-slate-700",
    violet: "border-violet-200 bg-violet-100 text-violet-800",
  }[color];
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {children}
    </span>
  );
}

function DownloadLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      download={label}
      className="inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-100 px-1.5 py-0.5 font-mono text-[11px] text-amber-800 hover:bg-amber-200"
    >
      <Download className="size-3" />
      {label}
    </a>
  );
}

function CheckItem({ ok, children }: { ok?: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <CheckCircle2 className={`mt-0.5 size-3.5 shrink-0 ${ok ? "text-emerald-500" : "text-slate-300"}`} />
      <span className={ok ? "text-slate-900" : "text-slate-500"}>{children}</span>
    </li>
  );
}

function TroubleItem({
  symptom,
  cause,
  fix,
}: {
  symptom: string;
  cause: string;
  fix: React.ReactNode;
}) {
  return (
    <div className="rounded border border-slate-200 bg-white p-2.5 space-y-1">
      <div className="flex items-start gap-1.5">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
        <span className="font-semibold text-slate-800">{symptom}</span>
      </div>
      <div className="pl-5 text-slate-600">
        <span className="font-medium">Nguyên nhân:</span> {cause}
      </div>
      <div className="pl-5 text-slate-600">
        <span className="font-medium">Cách xử lý:</span> {fix}
      </div>
    </div>
  );
}