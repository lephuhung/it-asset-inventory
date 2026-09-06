"use client";

/** Badge cấp độ (1–3) và trạng thái hồ sơ cấp độ hệ thống thông tin. */
import { Badge } from "@/components/ui";
import type { SystemProfileStatus } from "@/lib/types";

const STATUS_META: Record<SystemProfileStatus, { label: string; cls: string }> = {
  drafted: { label: "Nháp", cls: "bg-slate-100 text-slate-600 ring-slate-500/20" },
  pending_review: { label: "Chờ duyệt", cls: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  approved: { label: "Đã phê duyệt", cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  rejected: { label: "Bị từ chối", cls: "bg-rose-50 text-rose-700 ring-rose-600/20" },
};

const LEVEL_BADGE: Record<number, string> = {
  1: "bg-sky-50 text-sky-700 ring-sky-600/20",
  2: "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
  3: "bg-violet-50 text-violet-700 ring-violet-600/20",
};

export function StatusBadge({ status }: { status: SystemProfileStatus }) {
  const meta = STATUS_META[status];
  return <Badge className={meta.cls}>{meta.label}</Badge>;
}

export function LevelBadge({ level }: { level: number }) {
  return <Badge className={LEVEL_BADGE[level] ?? ""}>Cấp độ {level}</Badge>;
}
