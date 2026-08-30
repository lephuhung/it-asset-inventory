"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain, Settings } from "lucide-react";
import { ReactNode } from "react";

/** Layout cho khu vực LLM-DFIR — header + subnav chia 2 trang.
 *  Theo Design.md: title heavy + tracking âm, icon sticker tile (màu trang trí),
 *  tab active dùng vạch primary (màu cấu trúc duy nhất). */
export default function LlmDfirLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const tabs = [
    { href: "/admin/llm-dfir/settings", label: "Cấu hình LLM", icon: Settings },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
          <Brain className="size-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-[22px] font-bold tracking-tight text-slate-900">
            AI Điều tra (LLM-DFIR)
          </h1>
          <p className="mt-0.5 text-sm leading-snug text-slate-500">
            Tích hợp Model LLM (Ollama / OpenAI / Qwen) để phân tích log Velociraptor tự động
          </p>
        </div>
      </div>

      <nav className="flex gap-1 border-b border-slate-200" aria-label="LLM-DFIR">
        {tabs.map((t) => {
          const active = pathname === t.href || pathname.startsWith(t.href + "/");
          const Icon = t.icon;
          return (
            <Link
              key={t.href}
              href={t.href}
              aria-current={active ? "page" : undefined}
              className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none ${
                active
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
              }`}
            >
              <Icon className="size-4" />
              {t.label}
            </Link>
          );
        })}
      </nav>

      {children}
    </div>
  );
}
