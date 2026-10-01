"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button, Card } from "@/components/ui";

/**
 * Error boundary cấp route group `(portal)` — render lỗi ở một trang KHÔNG còn
 * nổ cả app (app/global-error.tsx thay toàn bộ shell gồm sidebar, bell,
 * realtime). Component này nằm TRONG (portal)/layout nên sidebar vẫn giữ,
 * user có thể điều hướng sang trang khác hoặc bấm thử lại.
 */
export default function PortalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <Card className="w-full max-w-md text-center">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-xl bg-rose-50 text-rose-600">
          <AlertTriangle className="size-6" />
        </div>
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          Trang này gặp lỗi khi hiển thị
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
          Vui lòng thử lại. Nếu lỗi tiếp tục, liên hệ quản trị viên kèm mã lỗi.
        </p>
        {error.digest && (
          <code className="mt-2 block text-[11px] text-slate-400">digest: {error.digest}</code>
        )}
        <Button className="mt-5" onClick={reset}>
          <RotateCcw className="size-4" /> Thử lại
        </Button>
      </Card>
    </div>
  );
}
