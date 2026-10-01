"use client";

/**
 * Trang cấu hình hồ sơ cấp độ (chỉ Super Admin):
 * - Tab "Loại thiết bị": CRUD catalog `/api/device-types` (icon emoji dùng trên sơ đồ mạng).
 * - Tab "Yêu cầu ATTT": CRUD catalog `/api/level-requirements` theo cấp độ 1–3.
 *
 * Sidebar đặt trong nhóm "Vận hành" — đây là trang cấu hình hệ thống, không thuộc nhóm
 * "Tổ chức" (dù có quan hệ với hồ sơ cấp độ).
 */
import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DeviceType, LevelRequirement } from "@/lib/types";
import {
  Badge,
  Button,
  ErrorBanner,
  Field,
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
  Textarea,
} from "@/components/ui";
import { useAuth } from "@/components/auth-context";

type Tab = "device-types" | "level-requirements";

export default function SystemProfileConfigPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [tab, setTab] = useState<Tab>("device-types");
  const [devTypes, setDevTypes] = useState<DeviceType[]>([]);
  const [levelReqs, setLevelReqs] = useState<LevelRequirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Modal loại thiết bị
  const [dtModal, setDtModal] = useState<DeviceType | "new" | null>(null);
  const [dtCode, setDtCode] = useState("");
  const [dtLabel, setDtLabel] = useState("");
  const [dtIcon, setDtIcon] = useState("");
  const [dtSort, setDtSort] = useState(0);
  const [dtActive, setDtActive] = useState(true);

  // Modal yêu cầu ATTT theo cấp độ
  const [lrModal, setLrModal] = useState<LevelRequirement | "new" | null>(null);
  const [lrLevel, setLrLevel] = useState<1 | 2 | 3>(1);
  const [lrCode, setLrCode] = useState("");
  const [lrTitle, setLrTitle] = useState("");
  const [lrDesc, setLrDesc] = useState("");
  const [lrSort, setLrSort] = useState(0);
  const [lrActive, setLrActive] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [dts, lrs] = await Promise.all([
        api.get<DeviceType[]>("/device-types", { active_only: false }),
        api.get<LevelRequirement[]>("/level-requirements"),
      ]);
      setDevTypes(dts);
      setLevelReqs(lrs);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Không tải được cấu hình");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isSuperAdmin) void load();
    else setLoading(false);
  }, [isSuperAdmin, load]);

  if (!isSuperAdmin) {
    return <ErrorBanner message="Chỉ quản trị viên hệ thống mới vào được trang cấu hình này." />;
  }
  if (loading) return <Spinner label="Đang tải cấu hình…" />;

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Thao tác thất bại");
    } finally {
      setBusy(false);
    }
  };

  const saveDeviceType = () => {
    if (!dtLabel.trim()) return;
    const payload = { label: dtLabel.trim(), icon: dtIcon.trim() || null, sort_order: dtSort, is_active: dtActive };
    setDtModal(null);
    void act(() =>
      dtModal === "new"
        ? api.post("/device-types", { ...payload, code: dtCode.trim() })
        : api.patch(`/device-types/${(dtModal as DeviceType).id}`, payload),
    );
  };

  const saveLevelRequirement = () => {
    if (!lrCode.trim() || !lrTitle.trim()) return;
    const payload = {
      level: lrLevel,
      code: lrCode.trim(),
      title: lrTitle.trim(),
      description: lrDesc.trim() || null,
      sort_order: lrSort,
      is_active: lrActive,
    };
    setLrModal(null);
    void act(() =>
      lrModal === "new"
        ? api.post("/level-requirements", payload)
        : api.patch(`/level-requirements/${(lrModal as LevelRequirement).id}`, {
            title: payload.title,
            description: payload.description,
            sort_order: payload.sort_order,
            is_active: payload.is_active,
          }),
    );
  };

  return (
    <div>
      <PageHeader
        title="Cấu hình hồ sơ cấp độ"
        description="Danh mục dùng chung cho mọi hồ sơ: loại thiết bị và yêu cầu an toàn theo cấp độ."
        actions={
          <Button
            onClick={() => {
              if (tab === "device-types") {
                setDtCode(""); setDtLabel(""); setDtIcon(""); setDtSort(0); setDtActive(true);
                setDtModal("new");
              } else {
                setLrLevel(1); setLrCode(""); setLrTitle(""); setLrDesc(""); setLrSort(0); setLrActive(true);
                setLrModal("new");
              }
            }}
          >
            <Plus className="size-4" /> {tab === "device-types" ? "Thêm loại thiết bị" : "Thêm yêu cầu"}
          </Button>
        }
      />

      {error && <ErrorBanner message={error} />}

      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {([
          ["device-types", "Loại thiết bị"],
          ["level-requirements", "Yêu cầu ATTT theo cấp độ"],
        ] as Array<[Tab, string]>).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
              tab === key ? "border-brand-600 text-slate-900" : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
            }`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "device-types" && (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr><th className={TH}>Loại</th><th className={TH}>Mã</th><th className={TH}>Icon</th><th className={TH}>Thứ tự</th><th className={TH}>Trạng thái</th><th className={TH}></th></tr>
            </thead>
            <tbody>
              {devTypes.map((t) => (
                <tr key={t.id} className={TR_HOVER}>
                  <td className={`${TD} font-medium`}>{t.label}</td>
                  <td className={`${TD} font-mono text-xs`}>{t.code}</td>
                  <td className={`${TD} text-lg`}>{t.icon ?? "—"}</td>
                  <td className={TD}>{t.sort_order}</td>
                  <td className={TD}>
                    <Badge className={t.is_active ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/20"}>
                      {t.is_active ? "Đang dùng" : "Đã tắt"}
                    </Badge>
                  </td>
                  <td className={TD}>
                    <div className="flex gap-1">
                      <Button size="sm" variant="secondary" onClick={() => {
                        setDtCode(t.code); setDtLabel(t.label); setDtIcon(t.icon ?? ""); setDtSort(t.sort_order); setDtActive(t.is_active);
                        setDtModal(t);
                      }}>Sửa</Button>
                      <Button size="sm" variant="danger" loading={busy} onClick={() => void act(() => api.delete(`/device-types/${t.id}`))}>Xóa</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "level-requirements" && (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr><th className={TH}>Cấp độ</th><th className={TH}>Mã</th><th className={TH}>Yêu cầu</th><th className={TH}>Thứ tự</th><th className={TH}>Trạng thái</th><th className={TH}></th></tr>
            </thead>
            <tbody>
              {levelReqs.map((r) => (
                <tr key={r.id} className={TR_HOVER}>
                  <td className={TD}><Badge className="bg-indigo-50 text-indigo-700 ring-indigo-600/20">Cấp {r.level}</Badge></td>
                  <td className={`${TD} font-mono text-xs`}>{r.code}</td>
                  <td className={`${TD} max-w-md`}>
                    <div className="font-medium">{r.title}</div>
                    {r.description && <div className="text-xs text-slate-500">{r.description}</div>}
                  </td>
                  <td className={TD}>{r.sort_order}</td>
                  <td className={TD}>
                    <Badge className={r.is_active ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/20"}>
                      {r.is_active ? "Áp dụng" : "Ngừng áp dụng"}
                    </Badge>
                  </td>
                  <td className={TD}>
                    <div className="flex gap-1">
                      <Button size="sm" variant="secondary" onClick={() => {
                        setLrLevel(r.level); setLrCode(r.code); setLrTitle(r.title); setLrDesc(r.description ?? ""); setLrSort(r.sort_order); setLrActive(r.is_active);
                        setLrModal(r);
                      }}>Sửa</Button>
                      <Button
                        size="sm"
                        variant="danger"
                        loading={busy}
                        onClick={() => void act(() => api.delete(`/level-requirements/${r.id}`))}
                        title="Chỉ xóa được yêu cầu chưa dùng trong hồ sơ nào"
                      >
                        Xóa
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal loại thiết bị */}
      <Modal
        open={dtModal !== null}
        onClose={() => setDtModal(null)}
        title={dtModal === "new" ? "Thêm loại thiết bị" : "Sửa loại thiết bị"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDtModal(null)}>Hủy</Button>
            <Button loading={busy} onClick={saveDeviceType}>Lưu</Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Mã loại" required hint={dtModal === "new" ? "Chữ thường, không dấu (vd: camera)" : "Không đổi được sau khi tạo"}>
              <Input value={dtCode} onChange={(e) => setDtCode(e.target.value)} disabled={dtModal !== "new"} placeholder="camera" />
            </Field>
            <Field label="Icon (emoji)" hint="Hiển thị kèm node trên sơ đồ mạng">
              <Input value={dtIcon} onChange={(e) => setDtIcon(e.target.value)} placeholder="📷" />
            </Field>
          </div>
          <Field label="Tên loại" required>
            <Input value={dtLabel} onChange={(e) => setDtLabel(e.target.value)} placeholder="Camera giám sát" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Thứ tự hiển thị">
              <Input type="number" value={dtSort} onChange={(e) => setDtSort(Number(e.target.value))} />
            </Field>
            <Field label="Trạng thái">
              <Select value={dtActive ? "1" : "0"} onChange={(e) => setDtActive(e.target.value === "1")}>
                <option value="1">Đang dùng</option>
                <option value="0">Tắt (ẩn khỏi form nhập)</option>
              </Select>
            </Field>
          </div>
        </div>
      </Modal>

      {/* Modal yêu cầu ATTT theo cấp độ */}
      <Modal
        open={lrModal !== null}
        onClose={() => setLrModal(null)}
        title={lrModal === "new" ? "Thêm yêu cầu ATTT" : "Sửa yêu cầu ATTT"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setLrModal(null)}>Hủy</Button>
            <Button loading={busy} onClick={saveLevelRequirement}>Lưu</Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Cấp độ" required hint={lrModal !== "new" ? "Không đổi được sau khi tạo" : undefined}>
              <Select value={lrLevel} onChange={(e) => setLrLevel(Number(e.target.value) as 1 | 2 | 3)} disabled={lrModal !== "new"}>
                <option value={1}>Cấp 1</option>
                <option value={2}>Cấp 2</option>
                <option value={3}>Cấp 3</option>
              </Select>
            </Field>
            <Field label="Mã yêu cầu" required hint={lrModal === "new" ? "VD: PL1_02" : "Không đổi được sau khi tạo"}>
              <Input value={lrCode} onChange={(e) => setLrCode(e.target.value)} disabled={lrModal !== "new"} />
            </Field>
          </div>
          <Field label="Nội dung yêu cầu" required>
            <Input value={lrTitle} onChange={(e) => setLrTitle(e.target.value)} />
          </Field>
          <Field label="Mô tả chi tiết">
            <Textarea value={lrDesc} onChange={(e) => setLrDesc(e.target.value)} rows={3} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Thứ tự hiển thị">
              <Input type="number" value={lrSort} onChange={(e) => setLrSort(Number(e.target.value))} />
            </Field>
            <Field label="Trạng thái">
              <Select value={lrActive ? "1" : "0"} onChange={(e) => setLrActive(e.target.value === "1")}>
                <option value="1">Áp dụng</option>
                <option value="0">Ngừng áp dụng</option>
              </Select>
            </Field>
          </div>
        </div>
      </Modal>
    </div>
  );
}
