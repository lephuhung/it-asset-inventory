"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Building2,
  Check,
  ChevronRight,
  Landmark,
  Network,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Organization, OrganizationCreate } from "@/lib/types";
import { useAuth } from "@/components/auth-context";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  IconButton,
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

/* Chấm màu phân loại theo loại tổ chức — điểm chấm trang trí duy nhất
   mà palette sticker được phép đảm nhiệm (Design.md §Colors). */
const TYPE_DOT: Record<string, string> = {
  root: "bg-brand-600",
  ubnd_xa: "bg-sky-600",
  so_ban_nganh: "bg-violet-600",
  phong: "bg-amber-500",
  don_vi: "bg-slate-400",
};

/* Tiền tố hiển thị trước tên theo loại tổ chức. */
const TYPE_PREFIX: Record<string, string> = {
  ubnd_xa: "UBND Xã/Phường",
  so_ban_nganh: "Sở/Ban/Ngành",
};

/* Chuẩn hóa cho tìm kiếm: bỏ dấu tiếng Việt, đ→d, lowercase. */
function normText(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

/** Duyệt cây: thêm vào `acc` các id nằm trên đường dẫn tới node khớp.
    Tìm trên cả tên lẫn tiền tố/nhãn loại (VD: gõ "so" ra Sở ban ngành).
    Trả về số node tự khớp trong cây con. */
function collectVisible(orgs: Organization[], q: string, acc: Set<string>): number {
  let count = 0;
  for (const org of orgs) {
    const childAcc = new Set<string>();
    const childMatches = org.children?.length ? collectVisible(org.children, q, childAcc) : 0;
    const meta = ORG_TYPE_META[org.type];
    const haystack = normText(
      `${org.name} ${TYPE_PREFIX[org.type] ?? ""} ${meta?.label ?? ""}`,
    );
    const selfMatch = haystack.includes(q);
    if (selfMatch || childMatches > 0) {
      acc.add(org.id);
      if (selfMatch) count += 1;
    }
    for (const id of childAcc) acc.add(id);
    count += childMatches;
  }
  return count;
}

function OrgNode({
  org,
  depth = 0,
  collapsed,
  onToggle,
  visibleIds,
}: {
  org: Organization;
  depth?: number;
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  /** null = không lọc; khi lọc chỉ render node thuộc đường dẫn khớp (luôn mở). */
  visibleIds: Set<string> | null;
}) {
  if (visibleIds && !visibleIds.has(org.id)) return null;
  const meta =
    ORG_TYPE_META[org.type] ?? { label: org.type, badge: "bg-slate-100 text-slate-600 ring-slate-500/20" };
  const children = org.children ?? [];
  const hasChildren = children.length > 0;
  const open = visibleIds !== null || !collapsed.has(org.id);

  return (
    <li>
      <div
        className="group flex items-center gap-1.5 rounded-sm py-1 pr-2 transition-colors hover:bg-slate-50"
        style={{ marginLeft: depth * 18 }}
      >
        {/* Nút mở/đóng hoặc chỗ trống căn lề */}
        {hasChildren ? (
          <button
            onClick={() => onToggle(org.id)}
            aria-expanded={open}
            aria-label={`${open ? "Thu gọn" : "Mở"} ${org.name}`}
            className="flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-sm text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <ChevronRight
              className={`size-3.5 transition-transform motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
            />
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}

        <span className={`size-2 shrink-0 rounded-full ${TYPE_DOT[org.type] ?? "bg-slate-400"}`} aria-hidden />
        <Building2 className="size-3.5 shrink-0 text-slate-300 group-hover:text-slate-400" aria-hidden />
        {TYPE_PREFIX[org.type] && (
          <span className="shrink-0 text-xs font-medium text-slate-400">{TYPE_PREFIX[org.type]}</span>
        )}
        <span className={`truncate text-sm text-slate-800 ${depth === 0 ? "font-medium" : ""}`}>
          {org.name}
        </span>
        <Badge className={meta.badge}>{meta.label}</Badge>
        {hasChildren && !open && (
          <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
            {children.length} cấp dưới
          </span>
        )}
      </div>

      {hasChildren && open && (
        <ul className="ml-[13px] border-l border-slate-200 pl-1.5">
          {children.map((c) => (
            <OrgNode
              key={c.id}
              org={c}
              depth={depth + 1}
              collapsed={collapsed}
              onToggle={onToggle}
              visibleIds={visibleIds}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Tách cây thành 2 khối hiển thị RIÊNG: UBND cấp xã / Sở ban ngành.
    - Node gốc type=root là "cha chung" (VD: UBND tỉnh) → bỏ qua chính nó,
      các con của nó được phân vào khối theo type.
    - Node type=ubnd_xa → khối UBND (giữ nguyên cây con: đơn vị trực thuộc).
    - Node type=so_ban_nganh → khối Sở (giữ nguyên cây con: phòng ban).
    - Loại khác đứng đầu cây (phong/don_vi lẻ) → khối "Khác" để không mất dữ liệu. */
function splitTree(tree: Organization[]): {
  ubnd: Organization[];
  so: Organization[];
  other: Organization[];
} {
  const ubnd: Organization[] = [];
  const so: Organization[] = [];
  const other: Organization[] = [];
  const push = (nodes: Organization[]) => {
    for (const n of nodes) {
      if (n.type === "root") push(n.children ?? []);
      else if (n.type === "ubnd_xa") ubnd.push(n);
      else if (n.type === "so_ban_nganh") so.push(n);
      else other.push(n);
    }
  };
  push(tree);
  return { ubnd, so, other };
}

/** Đếm tổng node trong cây con (kể cả gốc). */
function countNodes(org: Organization): number {
  return 1 + (org.children ?? []).reduce((acc, c) => acc + countNodes(c), 0);
}

/** Cây con của `org` có node thuộc `visibleIds` (đang tìm kiếm) không? */
function subtreeHasVisible(org: Organization, visibleIds: Set<string>): boolean {
  if (visibleIds.has(org.id)) return true;
  return (org.children ?? []).some((c) => subtreeHasVisible(c, visibleIds));
}

/** Một khối tổ chức (UBND cấp xã / Sở ban ngành) — header + cây con riêng. */
function OrgSection({
  icon,
  title,
  nodes,
  collapsed,
  onToggle,
  visibleIds,
}: {
  icon: React.ReactNode;
  title: string;
  nodes: Organization[];
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  visibleIds: Set<string> | null;
}) {
  if (nodes.length === 0) return null;
  // Đang tìm kiếm mà khối không có kết quả → ẩn cả khối (tránh header rỗng).
  if (visibleIds && !nodes.some((n) => subtreeHasVisible(n, visibleIds))) return null;

  const count = nodes.reduce((acc, n) => acc + countNodes(n), 0);
  return (
    <div className="mb-4 last:mb-0">
      <div className="mb-1.5 flex items-center gap-2 rounded-md bg-slate-50/80 px-2.5 py-1.5">
        <span className="text-slate-400">{icon}</span>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">{title}</h3>
        <span className="ml-auto rounded-full bg-white px-2 py-0.5 text-[11px] font-medium tabular-nums text-slate-400 ring-1 ring-inset ring-slate-200">
          {count} tổ chức
        </span>
      </div>
      <ul>
        {nodes.map((n) => (
          <OrgNode
            key={n.id}
            org={n}
            collapsed={collapsed}
            onToggle={onToggle}
            visibleIds={visibleIds}
          />
        ))}
      </ul>
    </div>
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

  /* 2 khối hiển thị riêng: UBND cấp xã / Sở ban ngành (không trộn chung). */
  const { ubnd, so, other } = useMemo(() => splitTree(tree), [tree]);

  /* ── Cây co cụm + tìm kiếm ── */
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const bootstrapped = useRef(false);

  // Lần đầu tải xong: thu gọn TOÀN BỘ các nhánh có cấp dưới (mặc định đóng)
  useEffect(() => {
    if (bootstrapped.current || tree.length === 0) return;
    bootstrapped.current = true;
    const init = new Set<string>();
    const walk = (nodes: Organization[]) => {
      for (const n of nodes) {
        if (n.children?.length) init.add(n.id);
        walk(n.children ?? []);
      }
    };
    walk(tree);
    setCollapsed(init);
  }, [tree]);

  const q = useMemo(() => normText(query.trim()), [query]);
  const filtering = q.length > 0;
  const { visibleIds, matchCount } = useMemo(() => {
    if (!filtering) return { visibleIds: null as Set<string> | null, matchCount: 0 };
    const acc = new Set<string>();
    const n = collectVisible(tree, q, acc);
    return { visibleIds: acc, matchCount: n };
  }, [tree, q, filtering]);

  const toggle = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const setAll = (open: boolean) => {
    if (open) {
      setCollapsed(new Set());
    } else {
      setCollapsed(new Set(flatten.filter((n) => n.org.children?.length).map((n) => n.org.id)));
    }
  };

  const typeCounts = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const { org } of flatten) acc[org.type] = (acc[org.type] ?? 0) + 1;
    return acc;
  }, [flatten]);

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
          subtitle="2 khối riêng: UBND cấp xã · Sở ban ngành — chấm màu theo loại · nhấn mũi tên để mở/thu gọn"
          padded={false}
          actions={
            <>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Tìm tổ chức… (không cần dấu)"
                  className="h-8! w-52! min-w-0 pl-8! text-xs!"
                  aria-label="Tìm kiếm tổ chức"
                />
              </div>
              {tree.length > 0 && (
                <Button variant="ghost" size="sm" onClick={() => setAll(filtering || collapsed.size > 0)}>
                  {filtering || collapsed.size > 0 ? "Mở tất cả" : "Thu gọn"}
                </Button>
              )}
            </>
          }
        >
          {loading && tree.length === 0 ? (
            <Spinner label="Đang tải cây tổ chức…" />
          ) : ubnd.length + so.length + other.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center">
              <Building2 className="size-10 text-slate-300" />
              <p className="text-sm font-medium text-slate-600">Chưa có tổ chức nào</p>
              <p className="max-w-md text-xs text-slate-400">
                Dùng form bên phải để thêm UBND cấp xã / Sở ban ngành đầu tiên.
              </p>
            </div>
          ) : (
            <>
              {/* Chip thống kê theo loại — tổng quan nhanh khi danh sách dài */}
              <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 px-4 py-2.5">
                {Object.entries(typeCounts).map(([t, n]) => (
                  <Badge key={t} className={ORG_TYPE_META[t as keyof typeof ORG_TYPE_META]?.badge ?? "bg-slate-100 text-slate-600 ring-slate-500/20"}>
                    {ORG_TYPE_META[t as keyof typeof ORG_TYPE_META]?.label ?? t}: {n}
                  </Badge>
                ))}
                {filtering && (
                  <span className="ml-auto text-xs text-slate-500">
                    {matchCount}/{flatten.length} kết quả
                  </span>
                )}
              </div>

              {filtering && matchCount === 0 ? (
                <div className="flex flex-col items-center gap-1.5 py-12 text-center">
                  <Search className="size-8 text-slate-300" />
                  <p className="text-sm font-medium text-slate-600">Không có tổ chức nào khớp</p>
                  <p className="text-xs text-slate-400">
                    Không tìm thấy kết quả cho “{query.trim()}”.
                  </p>
                </div>
              ) : (
                /* Khung cuộn nội bộ — danh sách dài không đẩy trang.
                   2 khối RIÊNG: UBND cấp xã · Sở ban ngành (không trộn chung). */
                <div className="max-h-[560px] overflow-y-auto p-3">
                  <OrgSection
                    icon={<Landmark className="size-4" />}
                    title="UBND cấp xã"
                    nodes={ubnd}
                    collapsed={collapsed}
                    onToggle={toggle}
                    visibleIds={visibleIds}
                  />
                  <OrgSection
                    icon={<Network className="size-4" />}
                    title="Sở ban ngành"
                    nodes={so}
                    collapsed={collapsed}
                    onToggle={toggle}
                    visibleIds={visibleIds}
                  />
                  <OrgSection
                    icon={<Building2 className="size-4" />}
                    title="Khác"
                    nodes={other}
                    collapsed={collapsed}
                    onToggle={toggle}
                    visibleIds={visibleIds}
                  />
                </div>
              )}
            </>
          )}
          {tree.length > 0 && (
            <p className="border-t border-slate-100 px-4 py-2.5 text-xs text-slate-400">
              {ubnd.length + so.length + other.length} tổ chức hiển thị trong phạm vi quyền của bạn
              {ubnd.length > 0 && so.length > 0 && " · 2 khối: UBND cấp xã & Sở ban ngành"}
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
              <p className="rounded-md bg-brand-50 px-3 py-2 text-xs text-brand-700">
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
    </div>
  );
}