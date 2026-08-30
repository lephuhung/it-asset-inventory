import React from "react";

interface Props {
  platform: string;
  security: any;
}

export function SecuritySection({ platform, security }: Props) {
  if (platform?.toLowerCase() === "linux") return <LinuxSecurity security={security} />;
  return <WindowsSecurity security={security} />;
}

function WindowsSecurity({ security }: { security: any }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <Card title="Windows Update" value={security?.windows_update_status} />
      <Card title="RDP" value={fmt(security?.rdp_enabled)} />
      <Card title="BitLocker" value={security?.bitlocker} />
      <Card
        title="Antivirus"
        value={security?.antivirus?.length ? `${security.antivirus.length} sản phẩm` : "—"}
      />
      <Card title="Firewall" value={fmt(security?.firewall_enabled)} />
      <Card title="UAC" value={fmt(security?.uac_enabled)} />
      <Card title="Secure Boot" value={fmt(security?.secure_boot_enabled)} />
      <Card title="USB Storage" value={security?.usb_storage_blocked === true ? "BỊ CHẶN" : "CHO PHÉP"} />
    </div>
  );
}

function LinuxSecurity({ security }: { security: any }) {
  const update = security?.update ?? {};
  const enc = security?.disk_encryption ?? {};
  const ra = security?.remote_access ?? {};
  const ep = security?.endpoint_protection ?? [];
  const priv = security?.privilege_control ?? {};
  return (
    <div className="grid grid-cols-2 gap-4">
      <Card
        title="Cập nhật hệ thống"
        value={update.status}
        subtitle={
          update.pending_count != null
            ? `${update.pending_count} bản (${update.security_pending_count ?? 0} bảo mật)`
            : undefined
        }
      />
      <Card
        title="Mã hóa ổ đĩa"
        value={enc.enabled ? `${(enc.technology ?? "").toString().toUpperCase() || "Đã mã hóa"}` : "Chưa mã hóa"}
      />
      <Card title="SSH" value={fmt(ra.ssh_enabled)} />
      <Card title="Remote Desktop" value={fmt(ra.remote_desktop_enabled)} />
      <Card
        title="Endpoint Protection"
        value={ep.length ? ep.map((p: any) => p.name ?? p.displayName).join(", ") : "Không phát hiện"}
      />
      <Card title="Sudo" value={fmt(priv.sudo_installed)} />
      <Card title="Root locked" value={fmt(priv.root_account_locked)} />
      <Card title="Firewall" value={fmt(security?.firewall_enabled)} />
    </div>
  );
}

function Card({ title, value, subtitle }: { title: string; value?: any; subtitle?: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-gray-500">{title}</div>
      <div className="text-lg font-semibold">{value ?? "—"}</div>
      {subtitle && <div className="text-xs text-gray-400 mt-1">{subtitle}</div>}
    </div>
  );
}

function fmt(v: boolean | null | undefined): string {
  if (v === true) return "BẬT";
  if (v === false) return "TẮT";
  return "—";
}