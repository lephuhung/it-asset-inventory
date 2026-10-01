"use client";

import { memo } from "react";
import { AlertOctagon, Info, Search, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui";
import type { InvestigationSeverity } from "@/lib/types";

/**
 * Finding trong report DFIR — server trả từ `/admin/llm-dfir/investigations/{id}`.
 * Cấu trúc ổn định theo `dfir.report/1.0` schema; nếu server thêm trường mới
 * component sẽ bỏ qua (chỉ render những key đã biết).
 */
export interface InvestigationFinding {
  id: string;
  title: string;
  status: "observed" | "not_observed" | string;
  evidence?: string | null;
  mitre_id?: string | null;
  severity: InvestigationSeverity | string;
  confidence?: "low" | "medium" | "high" | string | null;
  evidence_refs?: string[] | null;
  recommendation?: string | null;
}

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-rose-100 text-rose-700 ring-rose-600/20",
  high: "bg-amber-100 text-amber-700 ring-amber-600/20",
  medium: "bg-amber-50 text-amber-800 ring-amber-600/20",
  low: "bg-blue-100 text-blue-700 ring-blue-600/20",
  info: "bg-emerald-100 text-emerald-700 ring-emerald-600/20",
};

const SEVERITY_ICON: Record<string, typeof AlertOctagon> = {
  critical: AlertOctagon,
  high: ShieldAlert,
  medium: ShieldAlert,
  low: Search,
  info: Info,
};

const STATUS_LABEL: Record<string, string> = {
  observed: "Đã quan sát",
  not_observed: "Không quan sát",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  low: "Thấp",
  medium: "Trung bình",
  high: "Cao",
};

function InvestigationFindingsInner({ findings }: { findings: InvestigationFinding[] }) {
  return (
    <div className="space-y-3">
      {findings.map((f) => {
        const sev = String(f.severity || "info").toLowerCase();
        const sevBadge = SEVERITY_BADGE[sev] ?? SEVERITY_BADGE.info;
        const SevIcon = SEVERITY_ICON[sev] ?? Info;
        const statusLabel = STATUS_LABEL[f.status] ?? f.status;
        const confLabel = f.confidence ? CONFIDENCE_LABEL[String(f.confidence).toLowerCase()] ?? f.confidence : null;
        return (
          <div
            key={f.id}
            className="rounded-lg border border-slate-200 bg-white p-4 transition-colors hover:border-slate-300"
          >
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <Badge className={sevBadge}>
                <SevIcon className="size-3.5" />
                {sev}
              </Badge>
              {f.mitre_id && (
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                  {f.mitre_id}
                </code>
              )}
              <span className="text-xs text-slate-500">{statusLabel}</span>
              {confLabel && (
                <span className="text-xs text-slate-500">· Tin cậy: {confLabel}</span>
              )}
            </div>
            <div className="text-sm font-semibold tracking-tight text-slate-900">
              {f.title}
            </div>
            {f.evidence && (
              <p className="mt-1.5 break-words text-[13px] leading-relaxed text-slate-600">
                <span className="font-semibold text-slate-700">Bằng chứng:</span>{" "}
                {f.evidence}
              </p>
            )}
            {f.recommendation && (
              <p className="mt-1.5 break-words text-[13px] leading-relaxed text-slate-600">
                <span className="font-semibold text-slate-700">Khuyến nghị:</span>{" "}
                {f.recommendation}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Memo để tránh re-render khi parent polling `load()`. */
export const InvestigationFindings = memo(InvestigationFindingsInner);
