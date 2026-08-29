"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Tag } from "@/lib/types";
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
import { CLASSIFICATION_META, tagBadgeClass } from "@/lib/format";

/** Màu badge cho tag mới (preset tailwind classes). */
const COLOR_PRESETS = [
  { label: "Xanh dương", value: "bg-blue-50 text-blue-700 ring-blue-600/20" },
  { label: "Tím", value: "bg-violet-50 text-violet-700 ring-violet-600/20" },
  { label: "Hồng", value: "bg-pink-50 text-pink-700 ring-pink-600/20" },
  { label: "Cam", value: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  { label: "Xanh lá", value: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  { label: "Xám", value: "bg-slate-100 text-slate-600 ring-slate-500/20" },
];

export default function TagsPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"classification" | "purpose">("purpose");
  const [color, setColor] = useState(COLOR_PRESETS[0].value);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.get<Tag[]>("/tags");
      setTags(Array.isArray(list) ? list : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách phân loại & mục đích");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createTag = async () => {
    setCreateError(null);
    if (!label.trim()) {
      setCreateError("Nhập tên mục đích");
      return;
    }
    setCreating(true);
    try {
      await api.post<Tag>("/tags", { label: label.trim(), kind, color });
      setLabel("");
      await load();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.detail : "Không tạo được mục đích");
    } finally {
      setCreating(false);
    }
  };

  const classification = tags.filter((t) => t.kind === "classification");
  const purpose = tags.filter((t) => t.kind === "purpose");

  if (loading && tags.length === 0) return <Spinner label="Đang tải danh sách…" />;

  return (
    <div>
      <PageHeader
        title="Phân loại & mục đích sử dụng"
        description="Loại máy (cá nhân / công vụ / BMNN) là phân loại hệ thống — quyết định thống kê. Mục đích sử dụng linh hoạt, bổ sung theo việc máy dùng để làm gì (dịch vụ công, soạn thảo văn bản…) và không ảnh hưởng thống kê công vụ."
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Tag phân loại — hệ thống, không đổi */}
        <Card title="Loại máy (phân loại hệ thống)" subtitle="Mỗi máy có đúng 1 loại — nguồn duy nhất của thống kê công vụ">
          <div className="space-y-2">
            {classification.map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <Badge className={tagBadgeClass(t)}>{t.label}</Badge>
                  <code className="font-mono text-xs text-slate-400">{t.key}</code>
                </div>
                <Badge className="bg-zinc-100 text-zinc-500 ring-zinc-500/20">Hệ thống</Badge>
              </div>
            ))}
            <p className="pt-1 text-xs leading-snug text-slate-400">
              {CLASSIFICATION_META.personal.label} không tính vào công vụ · {CLASSIFICATION_META.bmnn.label} là công vụ
              · công vụ thực tế = {CLASSIFICATION_META.official.label} + {CLASSIFICATION_META.bmnn.label}.
            </p>
          </div>
        </Card>

        {/* Mục đích sử dụng — linh hoạt */}
        <Card
          title="Mục đích sử dụng (linh hoạt)"
          subtitle="Tạo mục đích mới theo nhu cầu — máy để làm gì: dịch vụ công, soạn thảo văn bản…"
        >
          <div className="mb-4 space-y-2">
            {purpose.length === 0 && (
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
                Chưa có mục đích sử dụng — tạo mục đích đầu tiên bên dưới.
              </p>
            )}
            {purpose.map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2">
                <div className="flex items-center gap-2">
                  <Badge className={tagBadgeClass(t)}>{t.label}</Badge>
                  <code className="font-mono text-xs text-slate-400">{t.key}</code>
                </div>
                <span className="text-[11px] text-slate-400">Nhiều mục đích / máy</span>
              </div>
            ))}
          </div>

          <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/50 p-3">
            <Field label="Tên mục đích mới" required>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="VD: Dịch vụ công"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void createTag();
                }}
              />
            </Field>
            <Field label="Loại" hint="Mục đích sử dụng = mục đích linh hoạt gán cho máy; Loại máy (phân loại) là 3 loại hệ thống cố định — không tạo mới được.">
              <Select value={kind} onChange={(e) => setKind(e.target.value as "classification" | "purpose")}>
                <option value="purpose">Mục đích sử dụng</option>
                <option value="classification">Loại máy (phân loại)</option>
              </Select>
            </Field>
            {kind === "classification" && (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-200">
                Không tạo được loại máy mới — chỉ có 3 loại hệ thống (cá nhân / công vụ / BMNN). Chọn
                "Mục đích sử dụng" để tạo mục đích gán cho máy.
              </p>
            )}
            <Field label="Màu badge">
              <Select value={color} onChange={(e) => setColor(e.target.value)}>
                {COLOR_PRESETS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Field>
            {createError && <p className="text-sm text-rose-600">{createError}</p>}
            <div className="flex justify-end">
              <Button onClick={() => void createTag()} loading={creating} disabled={!label.trim() || kind === "classification"}>
                <Plus className="size-4" /> Tạo tag
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
