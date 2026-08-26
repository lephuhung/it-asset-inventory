"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ApiKey, ApiKeyCreated, Organization } from "@/lib/types";
import { ORG_TYPE_META, flattenOrgTree, formatDateTime, timeAgo } from "@/lib/format";
import {
  Badge,
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
  PageHeader,
  Select,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";

/** API mở (#22, Phase 4) — quản lý API key (chỉ Super Admin). */
export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [orgId, setOrgId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [removing, setRemoving] = useState<ApiKey | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);

  const load = useCallback(async (silent = false) => {
    try {
      setKeys(await api.get<ApiKey[]>("/keys"));
      setError(null);
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : "Không tải được danh sách key");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    api
      .get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
  }, [load]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const k = await api.post<ApiKeyCreated>("/keys", {
        name,
        scope: "read:machines",
        org_id: orgId || null,
      });
      setCreated(k);
      setName("");
      await load(true);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không tạo được key");
    } finally {
      setSubmitting(false);
    }
  };

  const toggle = async (k: ApiKey) => {
    try {
      await api.patch(`/keys/${k.id}`, { enabled: !k.enabled });
      await load(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cập nhật thất bại");
    }
  };

  const remove = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.delete(`/keys/${removing.id}`);
      setRemoving(null);
      await load(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xóa thất bại");
    } finally {
      setRemoveBusy(false);
    }
  };

  const orgName = (id: string | null) => {
    if (!id) return "Toàn hệ thống";
    const f = flattenOrgTree(orgs).find((x) => x.org.id === id);
    return f ? f.org.name : id.slice(0, 8);
  };

  return (
    <div>
      <PageHeader
        title="API mở — API keys"
        description="Cho hệ thống khác đọc dữ liệu (scope read:machines) qua X-API-Key — key chỉ hiển thị 1 lần (#22)"
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Danh sách key" padded={false}>
          {loading && keys.length === 0 ? (
            <Spinner />
          ) : keys.length === 0 ? (
            <EmptyState
              icon={<KeyRound className="size-10" />}
              title="Chưa có API key nào"
              description="Tạo key đầu tiên ở form bên phải."
            />
          ) : (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr>
                    <th scope="col" className={TH}>Tên</th>
                    <th scope="col" className={TH}>Scope</th>
                    <th scope="col" className={TH}>Phạm vi</th>
                    <th scope="col" className={TH}>Lần dùng cuối</th>
                    <th scope="col" className={TH}>Trạng thái</th>
                    <th scope="col" className={`${TH} text-right`}>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {keys.map((k) => (
                    <tr key={k.id} className={TR_HOVER}>
                      <td className={`${TD} font-medium text-slate-800`}>{k.name}</td>
                      <td className={`${TD} font-mono text-xs text-slate-500`}>{k.scope}</td>
                      <td className={`${TD} text-xs text-slate-600`}>{orgName(k.org_id)}</td>
                      <td className={`${TD} text-xs`} title={k.last_used_at ? formatDateTime(k.last_used_at) : ""}>
                        {k.last_used_at ? timeAgo(k.last_used_at) : "Chưa dùng"}
                      </td>
                      <td className={TD}>
                        <Badge className={k.enabled ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-500 ring-slate-500/20"}>
                          {k.enabled ? "Đang mở" : "Đã vô hiệu"}
                        </Badge>
                      </td>
                      <td className={`${TD} text-right`}>
                        <div className="flex items-center justify-end gap-1.5">
                          <Button variant="secondary" size="sm" onClick={() => void toggle(k)}>
                            {k.enabled ? "Vô hiệu" : "Bật"}
                          </Button>
                          <button
                            onClick={() => setRemoving(k)}
                            className="cursor-pointer rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                            title="Xóa key"
                            aria-label={`Xóa API key ${k.name}`}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Tạo API key">
          <form onSubmit={create} className="space-y-3">
            <Field label="Tên hệ thống tích hợp" required>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Hệ thống báo cáo tổng hợp" required />
            </Field>
            {orgs.length > 0 && (
              <Field label="Phạm vi" hint="Bỏ trống = toàn hệ thống (chỉ Super Admin)">
                <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  <option value="">— Toàn hệ thống —</option>
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
            <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
              Scope hiện hỗ trợ: <code>read:machines</code> — gọi{" "}
              <code className="rounded bg-slate-100 px-1">GET /api/public/machines</code> với header{" "}
              <code className="rounded bg-slate-100 px-1">X-API-Key</code>.
            </p>
            {formError && <p className="text-sm text-rose-600">{formError}</p>}
            <Button type="submit" loading={submitting} className="w-full" disabled={!name}>
              <Plus className="size-4" /> Tạo key
            </Button>
          </form>
        </Card>
      </div>

      <Modal
        open={created !== null}
        onClose={() => setCreated(null)}
        title={
          <span className="inline-flex items-center gap-2">
            <KeyRound className="size-4 text-emerald-600" /> API key đã tạo
          </span>
        }
      >
        {created && (
          <div className="space-y-3">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
              <code className="block break-all font-mono text-sm text-emerald-900">{created.key}</code>
            </div>
            <div className="flex justify-end">
              <CopyButton text={created.key} />
            </div>
            <p className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>
                Key chỉ hiển thị <b>1 lần này</b>. Sao chép và lưu an toàn — server chỉ lưu hash
                (SHA-256). Hết hạn bằng cách xóa key.
              </span>
            </p>
          </div>
        )}
      </Modal>

      {/* Modal: xác nhận xóa key */}
      <ConfirmDialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title="Xóa API key"
        danger
        loading={removeBusy}
        confirmLabel="Xóa key"
        onConfirm={() => void remove()}
        message={
          <>
            Key <b>{removing?.name}</b> sẽ bị vô hiệu hóa ngay lập tức — hệ thống đang dùng key này
            sẽ mất quyền truy cập.
          </>
        }
      />
    </div>
  );
}