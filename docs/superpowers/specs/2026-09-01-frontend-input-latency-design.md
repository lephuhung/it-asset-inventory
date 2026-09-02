# Frontend Input Latency — Design Specification

**Date:** 2026-09-01
**Scope:** Portal Next.js client only

## Goal

Loại bỏ cảm giác trễ khi gõ vào các ô nhập liệu, ưu tiên luồng nhập yêu cầu điều tra AI và chat investigation, đồng thời ngăn các ô tìm kiếm gọi API theo từng ký tự.

## Root causes to address

1. `MachineDetailPage` giữ state `investigationInstructions`; mỗi ký tự làm render lại toàn bộ page chi tiết máy.
2. Investigation detail page giữ `chatInput` cùng state report/messages; mỗi ký tự có thể parse lại report Markdown và toàn bộ messages.
3. Machines, Audit và Telegram linked-users gọi API ngay sau mỗi thay đổi search state, không debounce và không hủy request cũ.
4. Tokens page parse CSV và đọc `sessionStorage` trong render, nên các input trong page đều chịu thêm chi phí không cần thiết.

## Functional requirements

- Nội dung prompt AI được giữ nguyên khi đóng/mở modal trong cùng lần mount.
- API tạo investigation chỉ gọi khi người dùng bấm “Bắt đầu điều tra”.
- API chat chỉ gọi khi người dùng bấm “Gửi” hoặc Ctrl/Cmd+Enter.
- Search API chỉ chạy sau khi người dùng ngừng gõ khoảng 350ms.
- Request tìm kiếm cũ phải bị hủy hoặc bị bỏ qua kết quả nếu đã lỗi thời.
- Không thay đổi endpoint, payload, quyền hạn, text nghiệp vụ hoặc contract backend.
- Không thêm dependency mới.

## Performance acceptance criteria

- Gõ liên tục 20 ký tự vào prompt AI hoặc chat không tạo request mạng.
- Trong lúc gõ prompt AI, chỉ component modal thay đổi; `MachineDetailPage` không render lại.
- Trong lúc gõ chat, chỉ `InvestigationChatPanel` thay đổi; report Markdown không parse lại theo từng ký tự.
- Search machines/audit/Telegram tạo tối đa một request cho giá trị cuối sau 350ms im lặng.
- `npm run typecheck` và `npm run build` thành công.
