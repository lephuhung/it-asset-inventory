"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { GitCompareArrows } from "lucide-react";
import { api } from "@/lib/api";
import type { MachineDetail, MachineListItem } from "@/lib/types";
import {
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  PageHeader,
  Select,
  Spinner,
  TABLE,
  TABLE_WRAP,
  TD,
  TH,
  THEAD,
  TR_HOVER,
} from "@/components/ui";

const FIELDS: Array<{ key: string; label: string }> = [
  { key: "os_name", label: "Hệ điều hành" },
  { key: "os_version", label: "Phiên bản OS" },
  { key: "os_build", label: "Build" },
  { key: "cpu", label: "CPU" },
  { key: "ram_gb", label: "RAM (GB)" },
  { key: "gpu", label: "GPU" },
  { key: "disks", label: "Ổ đĩa" },
  { key: "network", label: "Card mạng" },
  { key: "logged_user", label: "Người dùng đăng nhập" },
];

function pick(spec: MachineDetail["latest_spec"], key: string): string {
  if (!spec) return "—";
  const v = (spec as Record<string, unknown>)[key];
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) {
    return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(" | ");
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Diff cấu hình giữa 2 máy (#20, Phase 3) — so sánh snapshot mới nhất. */
export default function DiffPage() {
  const [machines, setMachines] = useState<MachineListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aId, setAId] = useState("");
  const [bId, setBId] = useState("");
  const [a, setA] = useState<MachineDetail | null>(null);
  const [b, setB] = useState<MachineDetail | null>(null);

  useEffect(() => {
    api
      .get<MachineListItem[]>("/machines")
      .then((list) => {
        setMachines(list);
        if (list.length > 0) setAId(list[0].id);
        if (list.length > 1) setBId(list[1].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Không tải được danh sách máy"))
      .finally(() => setLoading(false));
  }, []);

  const loadPair = useCallback(async () => {
    if (!aId || !bId || aId === bId) {
      setA(null);
      setB(null);
      return;
    }
    try {
      const [ma, mb] = await Promise.all([
        api.get<MachineDetail>(`/machines/${aId}`),
        api.get<MachineDetail>(`/machines/${bId}`),
      ]);
      setA(ma);
      setB(mb);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được chi tiết máy");
    }
  }, [aId, bId]);

  useEffect(() => {
    void loadPair();
  }, [loadPair]);

  return (
    <div>
      <PageHeader
        title="So sánh cấu hình (Diff)"
        description="So sánh snapshot mới nhất của 2 máy — phát hiện sai lệch khi đối soát tài sản (#20)"
      />

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <Spinner label="Đang tải danh sách máy…" />
      ) : machines.length < 2 ? (
        <EmptyState
          icon={<GitCompareArrows className="size-10" />}
          title="Cần ít nhất 2 máy để so sánh"
        />
      ) : (
        <>
          <Card className="mb-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Máy A">
                <Select value={aId} onChange={(e) => setAId(e.target.value)}>
                  {machines.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.hostname ?? m.machine_uuid.slice(0, 8)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Máy B">
                <Select value={bId} onChange={(e) => setBId(e.target.value)}>
                  {machines.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.hostname ?? m.machine_uuid.slice(0, 8)}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </Card>

          {a && b ? (
            <div className={TABLE_WRAP}>
              <table className={TABLE}>
                <thead className={THEAD}>
                  <tr>
                    <th className={TH}>Trường</th>
                    <th className={TH}>
                      <Link href={`/machines/${a.id}`} className="text-blue-600 hover:underline">
                        {a.hostname ?? a.machine_uuid.slice(0, 8)}
                      </Link>
                    </th>
                    <th className={TH}>
                      <Link href={`/machines/${b.id}`} className="text-blue-600 hover:underline">
                        {b.hostname ?? b.machine_uuid.slice(0, 8)}
                      </Link>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {FIELDS.map((f) => {
                    const va = pick(a.latest_spec, f.key);
                    const vb = pick(b.latest_spec, f.key);
                    const diff = va !== vb;
                    return (
                      <tr key={f.key} className={`${TR_HOVER} ${diff ? "bg-amber-50/60" : ""}`}>
                        <td className={`${TD} font-medium text-slate-700`}>
                          {f.label}
                          {diff && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">khác</span>}
                        </td>
                        <td className={`${TD} text-xs ${diff ? "text-amber-900" : "text-slate-600"}`}>{va}</td>
                        <td className={`${TD} text-xs ${diff ? "text-amber-900" : "text-slate-600"}`}>{vb}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Chọn 2 máy khác nhau để so sánh.</p>
          )}
        </>
      )}
    </div>
  );
}