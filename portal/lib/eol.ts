/**
 * Windows EOL report — tính cục bộ từ dữ liệu OS (os_name + os_build) vì backend
 * chưa có endpoint chuyên dụng (tính năng #5 trong kế hoạch, Phase 2).
 *
 * Dữ liệu tham khảo theo Microsoft Lifecycle; ngày dành cho Home/Pro (phổ biến ở cơ quan).
 */

export type EolStatus = "expired" | "warning" | "ok" | "unknown";

export interface EolInfo {
  release: string;
  eolDate: string | null; // ISO
  status: EolStatus;
  daysLeft: number | null;
  note: string;
}

const WARNING_DAYS = 180;

/** Map build → (release, EOL ISO). */
const WIN11_BUILDS: Array<[number, string, string]> = [
  [26100, "Windows 11 24H2", "2026-10-13"],
  [22631, "Windows 11 23H2", "2025-11-11"],
  [22621, "Windows 11 22H2", "2024-10-08"],
  [22000, "Windows 11 21H2", "2023-10-10"],
];

const SERVER_EOL: Array<[string, string, string]> = [
  ["2012", "Windows Server 2012/R2", "2023-10-10"],
  ["2016", "Windows Server 2016", "2027-01-12"],
  ["2019", "Windows Server 2019", "2029-01-09"],
  ["2022", "Windows Server 2022", "2031-10-14"],
];

function classify(eolIso: string | null, release: string): EolInfo {
  if (!eolIso) {
    return { release, eolDate: null, status: "unknown", daysLeft: null, note: "Chưa có dữ liệu vòng đời" };
  }
  const eol = new Date(eolIso).getTime();
  const now = Date.now();
  const days = Math.ceil((eol - now) / 86_400_000);
  const status: EolStatus = days < 0 ? "expired" : days <= WARNING_DAYS ? "warning" : "ok";
  const note =
    status === "expired"
      ? "Đã hết hỗ trợ — cần nâng cấp lên Windows 11"
      : status === "warning"
        ? `Sắp hết hỗ trợ (còn ${days} ngày)`
        : `Còn hỗ trợ (${days} ngày)`;
  return { release, eolDate: eolIso, status, daysLeft: days, note };
}

export function getWindowsEol(osName: string | null | undefined, osBuild: string | null | undefined): EolInfo {
  const name = (osName ?? "").toLowerCase();
  const build = (osBuild ?? "").trim();

  if (name.includes("windows 11")) {
    const buildNum = Number.parseInt(build, 10);
    const match = WIN11_BUILDS.find(([b]) => b === buildNum);
    if (match) return classify(match[2], match[1]);
    if (!Number.isNaN(buildNum) && buildNum > 26100) {
      return classify("2027-10-12", `Windows 11 (bản mới, build ${buildNum})`);
    }
    return classify(null, `Windows 11 (build ${build || "?"})`);
  }

  if (name.includes("windows 10")) {
    return classify("2025-10-14", "Windows 10");
  }

  if (name.includes("windows 8.1")) {
    return classify("2023-01-10", "Windows 8.1");
  }
  if (name.includes("windows 8")) {
    return classify("2016-01-12", "Windows 8");
  }
  if (name.includes("windows 7")) {
    return classify("2020-01-14", "Windows 7");
  }
  if (name.includes("windows xp")) {
    return classify("2014-04-08", "Windows XP");
  }

  if (name.includes("server")) {
    const match = SERVER_EOL.find(([v]) => build.includes(v) || name.includes(`server ${v}`));
    if (match) return classify(match[2], match[1]);
  }

  return classify(null, name || "Không xác định");
}

export const EOL_STATUS_META: Record<
  EolStatus,
  { label: string; badge: string }
> = {
  expired: { label: "Hết hạn hỗ trợ", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
  warning: { label: "Sắp hết hạn", badge: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  ok: { label: "Còn hỗ trợ", badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  unknown: { label: "Không xác định", badge: "bg-slate-100 text-slate-500 ring-slate-500/20" },
};