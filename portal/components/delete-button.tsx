"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/ui";
import { api } from "@/lib/api";

/** Nút xóa 1 hàng — icon thùng rác + confirm dialog.
 *
 * Hành động xóa không thể undo. Gọi `api.delete(path)`, rồi `onDeleted()`
 * để parent refresh table.
 *
 * Dùng:
 *   <DeleteButton
 *     resource="tài khoản"
 *     itemName={u.email}
 *     deletePath={`/users/${u.id}`}
 *     onDeleted={() => load(true)}
 *   />
 */
export function DeleteButton({
  resource,
  itemName,
  deletePath,
  onDeleted,
  disabled,
  disabledReason,
  className = "",
}: {
  /** Tên resource (tiếng Việt) hiển thị trong confirm: "tài khoản", "máy", "token"… */
  resource: string;
  /** Tên cụ thể của hàng (vd email, hostname, token code) để user xác nhận đúng đối tượng. */
  itemName?: string | null;
  /** Path gọi `api.delete(...)`. */
  deletePath: string;
  /** Sau khi xóa thành công — thường là refresh list. */
  onDeleted: () => void | Promise<void>;
  /** Disable nút (vd không được xóa chính mình, không được xóa super admin cuối). */
  disabled?: boolean;
  /** Tooltip khi disabled. */
  disabledReason?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doDelete = async () => {
    setErr(null);
    setLoading(true);
    try {
      await api.delete(deletePath);
      setOpen(false);
      await onDeleted();
    } catch (e) {
      setErr(e instanceof Error ? e.message : `Không xóa được ${resource}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        aria-label={`Xóa ${resource}${itemName ? ` ${itemName}` : ""}`}
        title={disabled ? disabledReason : `Xóa ${resource}`}
        disabled={disabled}
        onClick={() => {
          setErr(null);
          setOpen(true);
        }}
        className={`inline-flex size-7 items-center justify-center rounded-md text-rose-500 transition-colors duration-150 motion-reduce:transition-none hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-rose-500 ${className}`}
      >
        <Trash2 className="size-3.5" />
      </button>

      <ConfirmDialog
        open={open}
        onClose={() => (loading ? undefined : setOpen(false))}
        title={`Xóa ${resource}?`}
        message={
          <div className="space-y-2">
            <p>
              Hành động này <strong>không thể hoàn tác</strong>.
              {itemName && (
                <>
                  {" "}Bạn sắp xóa {resource}:{" "}
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800">
                    {itemName}
                  </code>
                </>
              )}
            </p>
            {err && <p className="text-rose-600">{err}</p>}
          </div>
        }
        confirmLabel="Xóa"
        danger
        loading={loading}
        onConfirm={() => void doDelete()}
      />
    </>
  );
}
