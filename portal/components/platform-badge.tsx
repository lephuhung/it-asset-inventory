import React from "react";

const config: Record<string, { label: string; color: string; icon: string }> = {
  windows: { label: "Windows", color: "bg-blue-100 text-blue-700", icon: "🪟" },
  linux: { label: "Linux", color: "bg-amber-100 text-amber-800", icon: "🐧" },
  unknown: { label: "Unknown", color: "bg-gray-100 text-gray-700", icon: "❓" },
};

export function PlatformBadge({ platform }: { platform?: string | null }) {
  const key = (platform ?? "unknown").toLowerCase();
  const c = config[key] ?? config.unknown;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${c.color}`}
      aria-label={`Platform: ${c.label}`}
    >
      <span aria-hidden>{c.icon}</span>
      <span>{c.label}</span>
    </span>
  );
}