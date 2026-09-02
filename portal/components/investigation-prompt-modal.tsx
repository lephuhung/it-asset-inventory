"use client";

import { useState } from "react";
import { Button, Field, Modal, Textarea } from "@/components/ui";

/**
 * Modal nhập yêu cầu điều tra AI (tách khỏi `MachineDetailPage`).
 *
 * Giữ state `instructions` bên trong component để khi user gõ vào textarea
 * KHÔNG render lại toàn bộ trang máy. Modal luôn được mount và chỉ ẩn/hiện
 * theo prop `open`, nên nội dung prompt được giữ nguyên khi đóng/mở trong
 * cùng lần mount.
 *
 * Component KHÔNG gọi API trực tiếp — chỉ trả về chuỗi đã trim qua
 * `onSubmit`. Parent chịu trách nhiệm gọi `/admin/llm-dfir/investigations`.
 */
export interface InvestigationPromptModalProps {
  open: boolean;
  machineHostname: string | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (instructions: string) => void;
}

export function InvestigationPromptModal({
  open,
  machineHostname,
  busy,
  error,
  onClose,
  onSubmit,
}: InvestigationPromptModalProps) {
  // State local — gõ ký tự chỉ re-render component này, không ảnh hưởng page cha.
  // Không reset khi `open` đổi → đóng/mở modal vẫn giữ nội dung trong cùng mount.
  const [instructions, setInstructions] = useState("");

  const handleSubmit = () => {
    onSubmit(instructions.trim());
  };

  return (
    <Modal
      open={open}
      title="Khởi tạo điều tra AI"
      onClose={onClose}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Hủy
          </Button>
          <Button loading={busy} onClick={handleSubmit}>
            Bắt đầu điều tra
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          Điều tra máy <strong>{machineHostname ?? ""}</strong> qua LangGraph và Velociraptor. Agent dùng
          policy cố định; chỉ thời gian hiện tại và dấu hiệu dưới đây được đưa vào cuộc điều tra.
        </p>
        <Field label="Dấu hiệu nghi ngờ / yêu cầu điều tra">
          <Textarea
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            placeholder="Ví dụ: nghi ngờ PowerShell thực thi bất thường trong 24 giờ gần đây"
            rows={5}
          />
        </Field>
        {error && <p className="text-sm text-rose-600">{error}</p>}
      </div>
    </Modal>
  );
}
