"use client";

import { useState } from "react";
import { Bell, Check, Save, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertTemplate, AlertTemplatePreview } from "@/lib/types";
import { ALERT_CATEGORY_META, ALERT_SEVERITY_META, OPT_OUT_LABELS } from "@/lib/format";
import {
  Badge, Button, Card, ErrorBanner, Field, Input, Modal, Select, Textarea, Toggle,
} from "@/components/ui";

export default function TemplatesTab({
  templates, onReload,
}: {
  templates: AlertTemplate[];
  onReload: () => void;
}) {
  const [editing, setEditing] = useState<AlertTemplate | null>(null);
  const [titleTemplate, setTitleTemplate] = useState("");
  const [bodyTemplate, setBodyTemplate] = useState("");
  const [optOut, setOptOut] = useState<string[]>([]);
  const [defaultSeverity, setDefaultSeverity] = useState("info");
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [preview, setPreview] = useState<AlertTemplatePreview | null>(null);
  const [previewCtx, setPreviewCtx] = useState("{}");

  const openEdit = (t: AlertTemplate) => {
    setEditing(t);
    setTitleTemplate(t.title_template);
    setBodyTemplate(t.body_template ?? "");
    setOptOut(t.opt_out_controls ?? []);
    setDefaultSeverity(t.default_severity);
    setEnabled(t.enabled);
    setError(null);
    setInfo(null);
    setPreview(null);
    setPreviewCtx("{}");
  };

  const toggleOptOut = (c: string) => {
    setOptOut((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const updated = await api.patch<AlertTemplate>(`/admin/alert-templates/${editing.code}`, {
        title_template: titleTemplate,
        body_template: bodyTemplate || null,
        opt_out_controls: optOut,
        default_severity: defaultSeverity,
        enabled,
      });
      setEditing(updated);
      setInfo("Đã lưu template. Thay đổi áp dụng cho mọi rule dùng template này.");
      onReload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    if (!editing) return;
    try {
      let ctx: Record<string, unknown> = {};
      try { ctx = JSON.parse(previewCtx || "{}"); } catch { setError("Context preview phải là JSON hợp lệ"); return; }
      const r = await api.post<AlertTemplatePreview>(`/admin/alert-templates/${editing.code}/preview`, { context: ctx });
      setPreview(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview thất bại");
    }
  };

  return (
    <div className="space-y-6">
      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}
      {info && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" />{info}
        </div>
      )}

      <Card title="Templates" subtitle="Super Admin quản lý nội dung + opt-out controls cho từng loại alert" padded={false}>
        <ul className="divide-y divide-slate-100">
          {templates.map((t) => {
            const cat = ALERT_CATEGORY_META[t.category] ?? ALERT_CATEGORY_META.system;
            const sev = ALERT_SEVERITY_META[t.default_severity] ?? ALERT_SEVERITY_META.info;
            return (
              <li key={t.code} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <span className="flex size-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <Bell className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800">{t.name}</p>
                  <p className="text-xs text-slate-500">{t.code}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Badge className={cat.badge}>{cat.label}</Badge>
                    <Badge className={sev.badge}>{sev.label}</Badge>
                    {(t.opt_out_controls ?? []).map((c) => (
                      <Badge key={c} className="bg-slate-100 text-slate-600 ring-slate-500/20">{OPT_OUT_LABELS[c] ?? c}</Badge>
                    ))}
                    {!t.enabled && <Badge className="bg-slate-100 text-slate-500 ring-slate-500/20">Disabled</Badge>}
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => openEdit(t)}>Sửa template</Button>
              </li>
            );
          })}
        </ul>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={`Sửa template · ${editing?.code ?? ""}`}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>Hủy</Button>
            <Button onClick={() => void save()} disabled={saving} loading={saving}>
              <Save className="size-3.5" /> Lưu template
            </Button>
          </div>
        }>
        {editing && (
          <div className="space-y-4">
            <Field label="Tên" required>
              <Input value={editing.name} disabled />
            </Field>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Category">
                <Badge className={ALERT_CATEGORY_META[editing.category]?.badge ?? ""}>
                  {ALERT_CATEGORY_META[editing.category]?.label ?? editing.category}
                </Badge>
              </Field>
              <Field label="Severity mặc định">
                <Select value={defaultSeverity} onChange={(e) => setDefaultSeverity(e.target.value)}>
                  {Object.entries(ALERT_SEVERITY_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </Select>
              </Field>
            </div>

            <Field label="Title template" required hint={`Biến cho phép: ${(editing.allowed_vars ?? []).join(", ")}`}>
              <Input value={titleTemplate} onChange={(e) => setTitleTemplate(e.target.value)} />
            </Field>
            <Field label="Body template" hint={`Biến cho phép: ${(editing.allowed_vars ?? []).join(", ")}`}>
              <Textarea rows={4} value={bodyTemplate} onChange={(e) => setBodyTemplate(e.target.value)} />
            </Field>

            <Field label="Opt-out controls" hint="Template quyết định admin được mute theo cách nào">
              <div className="flex flex-wrap gap-3">
                {["template", "severity"].map((c) => (
                  <label key={c} className="flex items-center gap-1.5 text-sm text-slate-700">
                    <input type="checkbox" checked={optOut.includes(c)} onChange={() => toggleOptOut(c)}
                      className="size-4 rounded border-slate-300 text-blue-600 focus:ring-brand-600" />
                    {OPT_OUT_LABELS[c]}
                  </label>
                ))}
              </div>
            </Field>

            <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
              <span className="text-sm text-slate-700">Template enabled</span>
              <Toggle checked={enabled} onChange={setEnabled} label="Template enabled" />
            </div>

            {/* Live preview */}
            <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
                <Sparkles className="size-3.5" /> Live preview
              </p>
              <Field label="Context JSON (sample)">
                <Input value={previewCtx} onChange={(e) => setPreviewCtx(e.target.value)} placeholder='{"hostname": "PC-01"}' />
              </Field>
              <Button variant="outline" size="sm" onClick={() => void runPreview()}>Render preview</Button>
              {preview && (
                <div className="space-y-1 rounded bg-white p-2 text-xs ring-1 ring-slate-200">
                  <p className="font-medium text-slate-800">{preview.title}</p>
                  {preview.body && <pre className="whitespace-pre-wrap text-slate-600">{preview.body}</pre>}
                  {preview.warnings.length > 0 && (
                    <p className="text-amber-600">Warning: {preview.warnings.join(", ")}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
