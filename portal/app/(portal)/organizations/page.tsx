"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Building2, Check, Landmark, Network, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Organization, OrganizationCreate, OrgAssignRule } from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
} from "@/components/ui";
import { ORG_TYPE_META, flattenOrgTree, orgTypeLabel } from "@/lib/format";

const CREATE_TYPES: Array<{ value: OrganizationCreate["type"]; label: string }> = [
  { value: "ubnd_xa", label: "UBND cấp xã" },
  { value: "so_ban_nganh", label: "Sở ban ngành" },
  { value: "phong", label: "Phòng ban (cấp dưới sở)" },
  { value: "don_vi", label: "Đơn vị trực thuộc" },
];

function OrgNode({ org, depth = 0 }: { org: Organization; depth?: number }) {
  const meta = ORG_TYPE_META[org.type] ?? { label: org.type, badge: "bg-slate-100 text-slate-600 ring-slate-500/20" };
  return (
    <li className={depth > 0 ? "mt-1" : ""}>
      <div
        className={`flex flex-wrap items-center gap-2 rounded-lg px-2.5 py-2 hover:bg-slate-50 ${
          depth > 0 ? "ml-6 border-l-2 border-slate-200 pl-4" : ""
        }`}
      >
        <Building2 className="size-4 shrink-0 text-slate-400" />
        <span className="text-sm font-medium text-slate-800">{org.name}</span>
        <Badge className={meta.badge}>{meta.label}</Badge>
      </div>
      {org.children?.length > 0 && (
        <ul>
          {org.children.map((c) => (
            <OrgNode key={c.id} org={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function OrganizationsPage() {
  const { user } = useAuth();
  const [tree, setTree] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form tạo tổ chức
  const [name, setName] = useState("");
  const [type, setType] = useState<OrganizationCreate["type"]>("ubnd_xa");
  const [parentId, setParentId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isSuper = user?.role === "super_admin" || user?.role === "admin_global";
  const flatten = useMemo(() => flattenOrgTree(tree), [tree]);

  const load = useCallback(async () => {
    try {
      const roots = await api.get<Organization[]>("/orgs");
      setTree(Array.isArray(roots) ? roots : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được cây tổ chức");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const quickAdd = (t: OrganizationCreate["type"]) => {
    setType(t);
    setFormError(null);
    // Mặc định cấp trên = root (parent rỗng) cho UBND xã / Sở; cấp con chọn sau
    const nameEl = document.getElementById("org-name") as HTMLInputElement | null;
    nameEl?.focus();
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setSuccess(null);
    try {
      await api.post<Organization>("/orgs", {
        name,
        type,
        parent_id: parentId || null,
      } satisfies OrganizationCreate);
      setSuccess(`Đã thêm tổ chức “${name}”.`);
      setName("");
      setParentId("");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không tạo được tổ chức");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Cây tổ chức"
        description="1 máy thuộc 1 cá nhân; cá nhân thuộc UBND cấp xã hoặc Sở ban ngành (hoặc đơn vị cấp dưới). Admin tổ chức xem được cấp dưới; Super Admin xem tất cả."
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Nạp lại
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {success && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          <Check className="size-4" /> {success}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <Card
          className="lg:col-span-3"
          title="Sơ đồ tổ chức"
          subtitle="Cây phân cấp — màu theo loại tổ chức"
          padded={false}
        >
          {loading && tree.length === 0 ? (
            <Spinner label="Đang tải cây tổ chức…" />
          ) : tree.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center">
              <Building2 className="size-10 text-slate-300" />
              <p className="text-sm font-medium text-slate-600">Chưa có tổ chức nào</p>
              <p className="max-w-md text-xs text-slate-400">
                Dùng form bên phải để thêm UBND cấp xã / Sở ban ngành đầu tiên.
              </p>
            </div>
          ) : (
            <ul className="p-4">
              {tree.map((n) => (
                <OrgNode key={n.id} org={n} />
              ))}
            </ul>
          )}
          {tree.length > 0 && (
            <p className="border-t border-slate-100 px-4 py-2.5 text-xs text-slate-400">
              {tree.length} tổ chức gốc · {flatten.length} tổ chức trong phạm vi quyền của bạn
            </p>
          )}
        </Card>

        <Card className="lg:col-span-2" title="Thêm tổ chức" subtitle="Tạo UBND cấp xã / Sở ban ngành hoặc cấp con">
          {isSuper && (
            <div className="mb-4 grid grid-cols-2 gap-2">
              <Button variant="secondary" size="sm" onClick={() => quickAdd("ubnd_xa")}>
                <Landmark className="size-3.5" /> Thêm UBND cấp xã
              </Button>
              <Button variant="secondary" size="sm" onClick={() => quickAdd("so_ban_nganh")}>
                <Network className="size-3.5" /> Thêm Sở ban ngành
              </Button>
            </div>
          )}

          <form onSubmit={create} className="space-y-3">
            <Field label="Tên tổ chức" required>
              <Input id="org-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: UBND xã An Phú / Sở Tài chính" required />
            </Field>

            <Field
              label="Loại tổ chức"
              required
              hint={
                isSuper
                  ? "UBND cấp xã / Sở ban ngành do Super Admin tạo"
                  : "Admin tổ chức chỉ thêm cấp con (phòng / đơn vị trực thuộc)"
              }
            >
              <Select
                value={type}
                onChange={(e) => setType(e.target.value as OrganizationCreate["type"])}
              >
                {CREATE_TYPES.filter(
                  (t) => isSuper || t.value === "phong" || t.value === "don_vi",
                ).map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field label="Cấp trên" hint="Bỏ trống = cấp gốc (chỉ Super Admin)">
              <Select value={parentId} onChange={(e) => setParentId(e.target.value)}>
                <option value="">— Không có (cấp gốc) —</option>
                {flatten.map(({ org, depth }) => {
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

            {!isSuper && (
              <p className="rounded-md bg-[#f5f5f5] px-3 py-2 text-xs text-[#4f4848]">
                Cấp trên được chọn phải thuộc phạm vi quyền của bạn (tổ chức của bạn hoặc cấp dưới) — backend sẽ từ chối nếu vi phạm.
              </p>
            )}

            {formError && <p className="text-sm text-rose-600">{formError}</p>}

            <Button type="submit" loading={submitting} className="w-full" disabled={!name}>
              <Plus className="size-4" /> Tạo tổ chức
            </Button>
          </form>
        </Card>
      </div>

      <OrgAssignRulesPanel orgs={tree} />
    </div>
  );
}

/* ── Rule tự gán tổ chức (tính năng #13) ───────────────────── */

function OrgAssignRulesPanel({ orgs }: { orgs: Organization[] }) {
  const [rules, setRules] = useState<OrgAssignRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [orgId, setOrgId] = useState("");
  const [matchField, setMatchField] = useState<"hostname" | "ip_prefix">("hostname");
  const [pattern, setPattern] = useState("");
  const [priority, setPriority] = useState(100);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const flatten = useMemo(() => flattenOrgTree(orgs), [orgs]);

  const load = useCallback(async () => {
    try {
      setRules(await api.get<OrgAssignRule[]>("/org-rules"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được rule");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      await api.post<OrgAssignRule>("/org-rules", {
        name,
        org_id: orgId,
        match_field: matchField,
        pattern,
        enabled: true,
        priority,
      });
      setName("");
      setPattern("");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không tạo được rule");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (r: OrgAssignRule) => {
    if (!window.confirm(`Xóa rule "${r.name}"?`)) return;
    try {
      await api.delete(`/org-rules/${r.id}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Xóa thất bại");
    }
  };

  const orgName = (id: string) => {
    const f = flatten.find((x) => x.org.id === id);
    return f ? f.org.name : id.slice(0, 8);
  };

  return (
    <Card
      className="mt-6"
      title="Rule tự gán tổ chức"
      subtitle="Khi máy mới enroll, hostname/dải IP khớp rule → máy tự gán cho tổ chức đích (ưu tiên cao trước)"
      padded={false}
    >
      {error && (
        <div className="px-5 pt-4">
          <ErrorBanner message={error} onRetry={() => void load()} />
        </div>
      )}
      <div className="grid gap-6 p-5 lg:grid-cols-2">
        <div>
          {loading && rules.length === 0 ? (
            <Spinner />
          ) : rules.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có rule nào.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {rules.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 py-2.5">
                  <Badge className="bg-blue-50 text-blue-700 ring-blue-600/20">{r.match_field}</Badge>
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
                    {r.pattern}
                  </code>
                  <span className="text-xs text-slate-400">→</span>
                  <span className="text-sm text-slate-700">{orgName(r.org_id)}</span>
                  <span className="text-[11px] text-slate-400">prio {r.priority}</span>
                  <div className="ml-auto flex items-center gap-1.5">
                    <Badge
                      className={
                        r.enabled
                          ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                          : "bg-slate-100 text-slate-500 ring-slate-500/20"
                      }
                    >
                      {r.enabled ? "Bật" : "Tắt"}
                    </Badge>
                    <button
                      onClick={() => void remove(r)}
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                      title="Xóa rule"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <form onSubmit={create} className="space-y-3">
          <Field label="Tên rule" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Phòng Kế toán theo hostname" required />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Trường khớp" required>
              <Select
                value={matchField}
                onChange={(e) => setMatchField(e.target.value as "hostname" | "ip_prefix")}
              >
                <option value="hostname">Hostname (KT-*)</option>
                <option value="ip_prefix">Dải IP (10.0.)</option>
              </Select>
            </Field>
            <Field label="Pattern" required hint="VD: KT-* hoặc 10.0.">
              <Input value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="KT-*" required />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Gán cho tổ chức" required>
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)} required>
                <option value="">— Chọn —</option>
                {flatten.map(({ org, depth }) => {
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
            <Field label="Ưu tiên" hint="Nhỏ = ưu tiên cao">
              <Input type="number" min={1} max={1000} value={priority} onChange={(e) => setPriority(Number(e.target.value))} />
            </Field>
          </div>
          {formError && <p className="text-sm text-rose-600">{formError}</p>}
          <Button type="submit" loading={submitting} className="w-full" disabled={!name || !pattern || !orgId}>
            <Plus className="size-4" /> Thêm rule
          </Button>
        </form>
      </div>
    </Card>
  );
}