"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Check,
  Clock,
  Download,
  HardDriveDownload,
  Info,
  KeyRound,
  Link2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Ticket,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  BulkTokenItem,
  BulkTokenResponse,
  Organization,
  SelfServiceLink,
  TokenCreateResponse,
  TokenListItem,
} from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import {
  Button,
  Card,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorBanner,
  Field,
  IconButton,
  Input,
  Modal,
  Badge,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";
import { ORG_TYPE_META, TOKEN_STATUS_META, flattenOrgTree, formatDateTime, tokenExpiry } from "@/lib/format";

const TTL_OPTIONS = [
  { value: 24, label: "24 giờ" },
  { value: 72, label: "72 giờ (mặc định)" },
  { value: 168, label: "7 ngày" },
  { value: 720, label: "30 ngày" },
];

const COMMAND_STORAGE = "ai_token_commands"; // token id → install command (hiện 1 lần)

function loadCommands(): Record<string, string> {
  try {
    return JSON.parse(sessionStorage.getItem(COMMAND_STORAGE) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function saveCommand(id: string, command: string) {
  const map = loadCommands();
  map[id] = command;
  sessionStorage.setItem(COMMAND_STORAGE, JSON.stringify(map));
}

export default function TokensPage() {
  const { user } = useAuth();
  const [tokens, setTokens] = useState<TokenListItem[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form tạo token
  const [orgId, setOrgId] = useState("");
  const [fullName, setFullName] = useState("");
  const [department, setDepartment] = useState("");
  const [position, setPosition] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [ttl, setTtl] = useState(72);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  // Modal kết quả
  const [created, setCreated] = useState<TokenCreateResponse | null>(null);
  const [revoking, setRevoking] = useState<TokenListItem | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);

  // Chế độ B — link tự khai báo
  const [links, setLinks] = useState<SelfServiceLink[]>([]);
  const [linkOrgId, setLinkOrgId] = useState("");
  const [newLink, setNewLink] = useState<SelfServiceLink | null>(null);
  const [creatingLink, setCreatingLink] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [removingLink, setRemovingLink] = useState<SelfServiceLink | null>(null);
  const [removeLinkBusy, setRemoveLinkBusy] = useState(false);

  // Bulk import CSV
  const [csvOrgId, setCsvOrgId] = useState("");
  const [csvTtl, setCsvTtl] = useState(72);
  const [csvText, setCsvText] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkTokenResponse | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  useEffect(() => {
    if (user) setOrgId((prev) => prev || user.org_id);
  }, [user]);

  /** Mở modal thêm thiết bị — reset form về trống (trừ org mặc định của user). */
  const openCreate = () => {
    setFullName("");
    setDepartment("");
    setPosition("");
    setEmail("");
    setPhone("");
    setNote("");
    setTtl(72);
    setFormError(null);
    setSubmitted(false);
    setShowCreate(true);
  };

  const loadTokens = useCallback(async (silent = false): Promise<TokenListItem[]> => {
    try {
      const list = await api.get<TokenListItem[]>("/tokens");
      setTokens(list);
      setError(null);
      return list;
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : "Không tải được danh sách token");
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const loadLinks = useCallback(async () => {
    try {
      setLinks(await api.get<SelfServiceLink[]>("/self-service/links"));
    } catch {
      setLinks([]);
    }
  }, []);

  useEffect(() => {
    void loadTokens();
    void loadLinks();
    api
      .get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
  }, [loadTokens, loadLinks]);

  const createLink = async () => {
    setCreatingLink(true);
    setLinkError(null);
    try {
      const l = await api.post<SelfServiceLink>("/self-service/links", {
        org_id: linkOrgId || user?.org_id,
      });
      setNewLink(l);
      await loadLinks();
    } catch (err) {
      setLinkError(err instanceof ApiError ? err.detail : "Không tạo được link");
    } finally {
      setCreatingLink(false);
    }
  };

  const toggleLink = async (l: SelfServiceLink) => {
    try {
      await api.patch(`/self-service/links/${l.id}`, { enabled: !l.enabled });
      await loadLinks();
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : "Cập nhật thất bại");
    }
  };

  const removeLink = async () => {
    if (!removingLink) return;
    setRemoveLinkBusy(true);
    try {
      await api.delete(`/self-service/links/${removingLink.id}`);
      setRemovingLink(null);
      await loadLinks();
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : "Xóa thất bại");
    } finally {
      setRemoveLinkBusy(false);
    }
  };

  const parseCsv = (text: string): BulkTokenItem[] => {
    return text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line): BulkTokenItem | null => {
        const parts = line.split(/[,;\t]/).map((s) => s.trim());
        if (/^họ tên|full.?name/i.test(parts[0] ?? "")) return null; // bỏ dòng header
        const [full_name, department, position, email, phone, note] = parts;
        return {
          full_name: full_name || null,
          department: department || null,
          position: position || null,
          email: email || null,
          phone: phone || null,
          note: note || null,
        };
      })
      .filter((x): x is BulkTokenItem => x !== null);
  };

  const importCsv = async () => {
    const items = parseCsv(csvText);
    if (items.length === 0) {
      setBulkError("Không có dòng dữ liệu hợp lệ (cần ít nhất 1 dòng: Họ tên,Phòng ban,…)");
      return;
    }
    setBulkBusy(true);
    setBulkError(null);
    try {
      const res = await api.post<BulkTokenResponse>("/tokens/bulk", {
        org_id: csvOrgId || user?.org_id,
        items,
        ttl_hours: csvTtl,
      });
      setBulkResult(res);
      setCsvText("");
      await loadTokens(true);
    } catch (err) {
      setBulkError(err instanceof ApiError ? err.detail : "Import thất bại");
    } finally {
      setBulkBusy(false);
    }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setSubmitted(false);
    setSubmitting(true);
    try {
      const res = await api.post<TokenCreateResponse>("/tokens", {
        org_id: orgId || user?.org_id,
        full_name: fullName || null,
        department: department || null,
        position: position || null,
        email: email || null,
        phone: phone || null,
        note: note || null,
        ttl_hours: ttl,
      });
      setCreated(res);
      setSubmitted(true);
      setShowCreate(false);
      // Gắn lệnh cài cho token vừa tạo (server chỉ trả token 1 lần) — khớp qua expires_at
      const list = await loadTokens(true);
      const match = list.find((t) => t.expires_at === res.expires_at);
      if (match) saveCommand(match.id, res.install_command);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không sinh được token");
    } finally {
      setSubmitting(false);
    }
  };

  const revoke = async () => {
    if (!revoking) return;
    setRevokeBusy(true);
    try {
      await api.post("/tokens/revoke", { token_id: revoking.id });
      setRevoking(null);
      await loadTokens(true);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không thu hồi được token");
    } finally {
      setRevokeBusy(false);
    }
  };

  const commands = loadCommands();

  return (
    <div>
      <PageHeader
        title="Thêm máy mới"
        description="Sinh token 1-lần cho từng máy — người dùng chỉ cần paste 1 dòng lệnh vào PowerShell (chế độ A: admin nhập hộ)"
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => void loadTokens()} disabled={loading}>
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus className="size-3.5" /> Thêm thiết bị
            </Button>
          </>
        }
      />

      {/* Timeline triển khai agent — từ sinh token đến máy online */}
      <Card className="mb-6" title="Timeline triển khai agent" subtitle="Vòng đời 1 token: sinh → gửi → cài → enroll → heartbeat (mục 4 kế hoạch)">
        <ol className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            { n: 1, t: "Sinh token", d: "Admin nhập thông tin người dùng → nhận mã + lệnh cài. Token có TTL (mặc định 72h), dùng 1 lần." },
            { n: 2, t: "Gửi lệnh cài", d: "Gửi 1 dòng PowerShell (kèm token nhúng) cho người dùng qua email/Zalo/chat." },
            { n: 3, t: "Chạy lệnh (cài)", d: "install.ps1 ký số → tải MSI → verify SHA256 + chữ ký → cài agent âm thầm." },
            { n: 4, t: "Enroll", d: "Agent gửi token + fingerprint + CSR → fuzzy-match máy cũ/mới → trả machine_id + client cert. Token vô hiệu ngay." },
            { n: 5, t: "Heartbeat", d: "Agent gửi heartbeat mỗi 45–75s (jitter) → máy Online trên dashboard realtime." },
            { n: 6, t: "Inventory", d: "Gửi cấu hình đầy đủ lần đầu → chi tiết máy, timeline bật/tắt, cảnh báo." },
          ].map((s) => (
            <li key={s.n} className="relative rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <span className="mb-2 flex size-7 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                {s.n}
              </span>
              <p className="text-sm font-semibold text-slate-800">{s.t}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{s.d}</p>
            </li>
          ))}
        </ol>
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span className="font-semibold">Lưu ý thời gian sống của token:</span>
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" />
            Nếu người dùng không cài trong TTL, token chuyển sang <b>Hết hạn</b> và phải tạo lại.
          </span>
          <span className="inline-flex items-center gap-1">
            <Check className="size-3" />
            Sau enroll, token mất giá trị ngay cả khi bị lộ (agent dùng mTLS cert).
          </span>
        </p>
      </Card>

      {error && <ErrorBanner message={error} onRetry={() => void loadTokens()} />}

      <div className="space-y-6">
        <Card
          title="Phễu triển khai"
          subtitle="Trạng thái token — dữ liệu sống từ lúc phát lệnh"
          padded={false}
        >
          {loading && tokens.length === 0 ? (
            <Spinner />
          ) : tokens.length === 0 ? (
            <EmptyState
              icon={<Ticket className="size-10" />}
              title="Chưa có token nào"
              description="Bấm nút 'Thêm thiết bị' phía trên để sinh token đầu tiên và bắt đầu phễu triển khai."
            />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr>
                    <th scope="col" className={TH}>Người dùng</th>
                    <th scope="col" className={TH}>Phòng / chức vụ</th>
                    <th scope="col" className={TH}>Trạng thái</th>
                    <th scope="col" className={TH}>Hết hạn</th>
                    <th scope="col" className={`${TH} text-right`}>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.map((t) => {
                    const meta = TOKEN_STATUS_META[t.status];
                    const expiry = tokenExpiry(t.expires_at);
                    const command = commands[t.id];
                    return (
                      <tr key={t.id} className={TR_HOVER}>
                        <td className={TD}>
                          <p className="font-medium text-slate-800">{t.full_name ?? "(chưa nhập)"}</p>
                          {t.email && <p className="text-xs text-slate-400">{t.email}</p>}
                          {t.phone_masked && <p className="text-xs text-slate-400">ĐT: {t.phone_masked}</p>}
                        </td>
                        <td className={`${TD} text-xs whitespace-nowrap text-slate-500`}>
                          {t.department || "—"}
                        </td>
                        <td className={TD}>
                          <StatusBadge badge={meta.badge} dot={meta.dot}>
                            {meta.label}
                          </StatusBadge>
                          {t.status === "pending" && expiry && !expiry.expired && expiry.hoursLeft <= 24 && (
                            <p className="mt-1 text-[11px] font-medium text-amber-600">
                              <Clock className="mr-0.5 inline size-3" />
                              {expiry.label}
                            </p>
                          )}
                          {expiry?.expired && t.status !== "used" && t.status !== "revoked" && (
                            <p className="mt-1 text-[11px] font-semibold text-rose-600">
                              <XCircle className="mr-0.5 inline size-3" />
                              {expiry.label} — cần tạo lại
                            </p>
                          )}
                        </td>
                        <td className={`${TD} text-xs whitespace-nowrap`}>
                          {formatDateTime(t.expires_at)}
                          {t.status === "pending" && expiry?.expired && (
                            <p className="text-[11px] font-medium text-rose-500">Đã quá hạn</p>
                          )}
                        </td>
                        <td className={`${TD} text-right`}>
                          <div className="flex items-center justify-end gap-1.5">
                            {command ? (
                              <CopyButton text={command} label="Copy lệnh" />
                            ) : t.status === "pending" ? (
                              <span className="text-[11px] text-slate-300">Lệnh hiện 1 lần lúc sinh</span>
                            ) : null}
                            {t.status === "pending" && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setRevoking(t)}
                                title="Thu hồi token chưa dùng"
                              >
                                Thu hồi
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="border-t border-slate-100 bg-slate-50/50 px-4 py-2.5 text-xs text-slate-400">
                Token có giá trị 1 lần, tự hủy sau khi enroll (agent chuyển sang mTLS client cert).
              </p>
            </div>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        {/* Chế độ B — link tự khai báo */}
        <Card
          title="Chế độ B — Link tự khai báo"
          subtitle="Tạo link chung của tổ chức; người dùng tự nhập thông tin và nhận lệnh cài (mục 4.4)"
        >
          <div className="flex flex-wrap items-end gap-3">
            {orgs.length > 0 && (
              <Field label="Tổ chức" className="min-w-48 flex-1">
                <Select value={linkOrgId} onChange={(e) => setLinkOrgId(e.target.value)}>
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
            <Button onClick={() => void createLink()} loading={creatingLink}>
              <Link2 className="size-4" /> Tạo link
            </Button>
          </div>
          {linkError && <p className="mt-2 text-sm text-rose-600">{linkError}</p>}

          {links.length > 0 && (
            <ul className="mt-4 divide-y divide-slate-100">
              {links.map((l) => (
                <li key={l.id} className="flex flex-wrap items-center gap-2 py-2.5">
                  <span className={`size-2 rounded-full ${l.enabled ? "bg-emerald-500" : "bg-slate-300"}`} />
                  <span className="text-sm text-slate-700">{l.org_name ?? "—"}</span>
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">
                    /enroll/{l.code}
                  </code>
                  <div className="ml-auto flex items-center gap-1.5">
                    <CopyButton text={l.url} label="Copy link" />
                    <button
                      onClick={() => void toggleLink(l)}
                      aria-pressed={l.enabled}
                      className={`cursor-pointer rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                        l.enabled
                          ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                          : "bg-slate-100 text-slate-500 ring-slate-500/20"
                      }`}
                    >
                      {l.enabled ? "Đang mở" : "Đã khóa"}
                    </button>
                    <button
                      onClick={() => setRemovingLink(l)}
                      className="cursor-pointer rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                      title="Xóa link"
                      aria-label={`Xóa link ${l.code}`}
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {newLink && (
            <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
              <p className="mb-1 text-sm font-medium text-emerald-900">Link mới tạo:</p>
              <div className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
                <code className="break-all font-mono text-xs text-emerald-800">{newLink.url}</code>
                <CopyButton text={newLink.url} label="Copy" />
              </div>
            </div>
          )}
        </Card>

        {/* Bulk import CSV */}
        <Card
          title="Bulk import CSV"
          subtitle="Triển khai đợt lớn: 1 dòng = 1 người = 1 token (tối đa 500 dòng/lần)"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {orgs.length > 0 && (
              <Field label="Tổ chức">
                <Select value={csvOrgId} onChange={(e) => setCsvOrgId(e.target.value)}>
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
            <Field label="Thời hạn token">
              <Select value={csvTtl} onChange={(e) => setCsvTtl(Number(e.target.value))}>
                {TTL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Dữ liệu (mỗi dòng: Họ tên, Phòng ban, Chức vụ, Email, Điện thoại, Ghi chú)" className="mt-3">
            <textarea
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              rows={6}
              placeholder={"Nguyễn Văn A, Kế toán, Chuyên viên, a@example.gov.vn, 0983…\nTrần Thị B, Nhân sự, Trưởng phòng, b@example.gov.vn"}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/15"
            />
          </Field>
          {bulkError && <p className="mt-2 text-sm text-rose-600">{bulkError}</p>}
          <div className="mt-3 flex items-center justify-between">
            <p className="text-xs text-slate-400">
              {parseCsv(csvText).length} dòng hợp lệ sẽ tạo token
            </p>
            <Button onClick={() => void importCsv()} loading={bulkBusy} disabled={!csvText.trim()}>
              <Upload className="size-4" /> Tạo hàng loạt
            </Button>
          </div>
        </Card>
      </div>

      {/* Modal: token vừa sinh */}
      <Modal
        open={created !== null}
        onClose={() => setCreated(null)}
        title={
          <span className="inline-flex items-center gap-2">
            <KeyRound className="size-4 text-emerald-600" /> Token đã sinh
          </span>
        }
        wide
      >
        {created && (
          <div className="space-y-4">
            <div>
              <p className="mb-1 text-sm font-medium text-slate-700">Token (dạng base62, dùng 1 lần)</p>
              <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <code className="break-all font-mono text-xs text-slate-700">{created.token}</code>
                <CopyButton text={created.token} label="Copy" />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Gửi token này cho người cài — KHÔNG gửi qua email/kênh không mã hóa. Token tương đương quyền
                enroll máy mới vào tổ chức.
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p className="mb-3 text-sm font-medium text-slate-700">Chọn phương pháp cài đặt</p>
              <div className="grid gap-3 md:grid-cols-2">
                {/* Phương pháp A: cài bằng lệnh */}
                <div className="rounded-lg border border-blue-200 bg-white p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Terminal className="size-4 text-blue-600" />
                    <span className="text-sm font-semibold text-slate-800">Phương pháp A — Cài bằng lệnh</span>
                    <Badge className="border-blue-200 bg-blue-50 text-blue-700">Online</Badge>
                  </div>
                  <p className="mb-2 text-xs text-slate-500">
                    Dùng cho máy có mạng ra server. Một dòng PowerShell.
                  </p>
                  <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2">
                    <code className="block break-all font-mono text-[11px] leading-relaxed text-emerald-900">
                      {created.install_command}
                    </code>
                  </div>
                  <div className="mt-2 flex justify-end">
                    <CopyButton text={created.install_command} label="Copy lệnh" />
                  </div>
                </div>

                {/* Phương pháp B: Gói cài 1-Click cho USB */}
                <div className="rounded-lg border border-amber-200 bg-white p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <HardDriveDownload className="size-4 text-amber-600" />
                    <span className="text-sm font-semibold text-slate-800">Phương pháp B — Gói Offline USB (1-Click)</span>
                    <Badge className="border-amber-200 bg-amber-50 text-amber-700">Máy BMNN</Badge>
                  </div>
                  <p className="mb-2.5 text-xs text-slate-500">
                    Tải về <b>1 file ZIP duy nhất (không mật khẩu)</b> → giải nén vào USB. Mang sang máy BMNN chỉ cần <b>nháy đúp chuột</b> vào file <code>install-offline.cmd</code>.
                  </p>
                  <a
                    href="/api/downloads/offline-package.zip"
                    download="offline-package.zip"
                    className="flex w-full items-center justify-center gap-1.5 rounded-md border border-amber-400 bg-amber-500 px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-amber-600 transition"
                  >
                    <Download className="size-3.5" /> Tải trọn bộ Gói USB (.zip không mật khẩu)
                  </a>
                  <div className="mt-2 rounded border border-blue-200 bg-blue-50 px-2 py-1.5 text-[11px] text-blue-800 flex items-start gap-1.5">
                    <Info className="size-3 mt-0.5 shrink-0" />
                    <span>
                      Sau khi USB có kết quả, mở trang{" "}
                      <Link href="/offline-import" className="font-semibold underline hover:text-blue-900">
                        Import máy BMNN
                      </Link>{" "}
                      — có <b>timeline 3 pha</b> + checklist + xử lý sự cố.
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-slate-400">
                    <a href="/api/downloads/agent.msi" className="hover:underline flex items-center gap-1">
                      <HardDriveDownload className="size-2.5" /> Tải lẻ MSI
                    </a>
                    <a href="/api/downloads/server_public_key.pem" className="hover:underline flex items-center gap-1">
                      <ShieldCheck className="size-2.5" /> Tải lẻ Server Key
                    </a>
                  </div>
                </div>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                <b>Trải nghiệm 1-Click cho máy BMNN:</b> Giải nén file zip vào USB → cắm vào máy BMNN và nháy đúp <code>install-offline.cmd</code>. Kết quả thu thập sẽ tự động xuất ra file <code>INVENTORY_...zip</code> đã ký số và mã hóa trên USB để nạp vào trang{" "}
                <Link href="/offline-import" className="font-semibold text-blue-600 hover:underline">
                  Import máy BMNN
                </Link>.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
              <span className="inline-flex items-center gap-1.5">
                <Clock className="size-3.5" />
                Hết hạn lúc <b>{formatDateTime(created.expires_at)}</b> — sau đó token vô giá trị và cần sinh lại.
              </span>
              <Button size="sm" variant="secondary" onClick={() => setCreated(null)}>
                Xong
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modal: thêm thiết bị (sinh token) */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title={
          <span className="inline-flex items-center gap-2">
            <Plus className="size-4 text-brand-600" /> Thêm máy mới
          </span>
        }
        footer={
          <div className="flex w-full items-center justify-between gap-3">
            <div className="flex-1">
              {formError && <p className="text-sm text-rose-600">{formError}</p>}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={() => setShowCreate(false)} disabled={submitting}>
                Hủy
              </Button>
              <Button form="token-create-form" type="submit" loading={submitting}>
                <Plus className="size-4" /> Sinh mã + lệnh cài đặt
              </Button>
            </div>
          </div>
        }
      >
        <form id="token-create-form" onSubmit={create} className="space-y-4">
          {orgs.length > 0 && (
            <Field label="Tổ chức (UBND cấp xã / Sở ban ngành)" required hint="Token kế thừa tổ chức — máy enroll sẽ thuộc tổ chức này">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
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
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Họ tên" required>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Nguyễn Văn A" required />
            </Field>
            <Field label="Phòng ban">
              <Input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Kế toán" />
            </Field>
            <Field label="Chức vụ">
              <Input value={position} onChange={(e) => setPosition(e.target.value)} placeholder="Chuyên viên" />
            </Field>
            <Field label="Số điện thoại (tùy chọn)" hint="Mã hóa AES-256-GCM khi lưu; UI mặc định mask">
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0983…" />
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Email">
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="a@example.gov.vn" />
            </Field>
            <Field label="Thời hạn token">
              <Select value={ttl} onChange={(e) => setTtl(Number(e.target.value))}>
                {TTL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Ghi chú">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ký hiệu hợp đồng / đơn vị…" />
          </Field>
          {submitted && (
            <p className="text-sm text-emerald-600">Đã sinh token — copy lệnh để gửi cho người dùng.</p>
          )}
        </form>
      </Modal>

      {/* Modal: xác nhận xóa link tự khai báo */}
      <ConfirmDialog
        open={removingLink !== null}
        onClose={() => setRemovingLink(null)}
        title="Xóa link tự khai báo"
        danger
        loading={removeLinkBusy}
        confirmLabel="Xóa link"
        onConfirm={() => void removeLink()}
        message={
          <>
            Link <code className="rounded bg-slate-100 px-1 font-mono text-xs">/enroll/{removingLink?.code}</code>{" "}
            sẽ ngừng hoạt động ngay. Người dùng đang giữ link sẽ không đăng ký được nữa.
          </>
        }
      />

      {/* Modal: xác nhận thu hồi */}
      <Modal
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title="Thu hồi token"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRevoking(null)}>
              Hủy
            </Button>
            <Button variant="danger" loading={revokeBusy} onClick={() => void revoke()}>
              Xác nhận thu hồi
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-600">
          Token của <b>{revoking?.full_name ?? "người dùng"}</b> sẽ bị vô hiệu hóa ngay lập tức.
          Hành động này được ghi vào audit log.
        </p>
      </Modal>

      {/* Modal: kết quả bulk import */}
      <Modal
        open={bulkResult !== null}
        onClose={() => setBulkResult(null)}
        title={
          <span className="inline-flex items-center gap-2">
            <KeyRound className="size-4 text-emerald-600" /> Đã tạo {bulkResult?.created ?? 0} token
          </span>
        }
        wide
      >
        {bulkResult && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              Mỗi token dùng 1 lần, hết hạn lúc{" "}
              <b>{formatDateTime(bulkResult.tokens[0]?.expires_at)}</b>. Lệnh cài đặt chỉ hiển thị
              1 lần tại đây — hãy gửi cho từng người dùng.
            </p>
            <div className="max-h-96 overflow-y-auto rounded-xl border border-slate-200">
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr>
                    <th scope="col" className={TH}>Người dùng</th>
                    <th scope="col" className={TH}>Lệnh cài đặt</th>
                    <th scope="col" className={TH}></th>
                  </tr>
                </thead>
                <tbody>
                  {bulkResult.tokens.map((t, i) => (
                    <tr key={i} className={TR_HOVER}>
                      <td className={`${TD} whitespace-nowrap text-xs text-slate-600`}>
                        {t.token}
                      </td>
                      <td className={`${TD} max-w-md`}>
                        <code className="block truncate font-mono text-[11px] text-slate-700" title={t.install_command}>
                          {t.install_command}
                        </code>
                      </td>
                      <td className={`${TD} text-right`}>
                        <CopyButton text={t.install_command} label="Copy lệnh" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}