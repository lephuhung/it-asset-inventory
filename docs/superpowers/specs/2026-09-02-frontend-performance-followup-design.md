# Frontend Performance Follow-up Design

**Date:** 2026-09-02
**Status:** Approved for implementation planning
**Evidence:**
- `docs/superpowers/handoffs/2026-09-01-frontend-performance-minimax-audit.md`
- `docs/superpowers/handoffs/2026-09-01-frontend-performance-luna-review.md`

## Goal

Loại bỏ các điểm nghẽn frontend còn lại có bằng chứng source rõ ràng: audit filter bị kẹt, fan-out EOL lớn, refresh realtime/polling chồng nhau, chi phí render bảng khi nhập liệu, và các phép tính cây tổ chức lặp lại.

## Scope

1. Sửa state machine debounce/reset của Audit khi đang ở page > 1.
2. Giới hạn và hủy fan-out tải chi tiết máy ở trang EOL; ngăn các lần tính lại chồng nhau.
3. Tách context realtime theo nhu cầu dữ liệu và giới hạn refresh từ realtime/polling tối đa một lần mỗi 5 giây trên Dashboard/Machines.
4. Cô lập bảng kết quả khỏi draft input search và memoize dữ liệu dẫn xuất.
5. Memoize `flattenOrgTree` ở các trang còn lại và dùng lookup map nơi cần.
6. Tránh refresh notification trùng khi mở trang và bỏ blur trên modal dùng chung nếu đang ở hot path paint.

## Non-goals

- Không sửa `server/`, `deepagent/` hoặc backend/API contract.
- Không đổi endpoint, HTTP method, payload, quyền hạn, nội dung nghiệp vụ hay kết quả lọc.
- Không thêm dependency.
- Không sửa các finding đã bị Luna xác định là false-positive: chat/report parse lại mỗi phím, Top10 không dừng poll, Sidebar chứa OrgNode, `InvestigationHistoryRow` là bottleneck lớn, hoặc parser Markdown thiếu memo.
- Không thêm virtual scrolling hay endpoint backend mới trong iteration này.

## Performance decisions

- Search text vẫn debounce 350ms; nút Apply là hành động chủ động và có thể dùng giá trị hiện tại.
- Audit phải luôn tải đúng một request sau khi filter debounced ổn định, kể cả khi offset cũ khác 0.
- EOL dùng tối đa 4 request chi tiết đồng thời; kết quả cũ không được ghi đè kết quả mới.
- Refresh do WebSocket và polling dùng chung throttle/backpressure tối thiểu 5 giây.
- Memo chỉ được dùng khi props/data reference ổn định; không thêm memo hình thức cho component nhỏ không nằm trên hot path.
- Blur trên overlay cố định được loại bỏ ở modal dùng chung để giảm composite/repaint khi cuộn hoặc tương tác.

## Acceptance criteria

- Audit page > 1: nhập filter, sau 350ms có kết quả mới với offset 0; không dead-end và không request với filter cũ sau reset.
- EOL: một lần load có tối đa 4 request `/machines/:id` đồng thời; bấm Tính lại khi đang tải không tạo thêm fan-out; request cũ bị abort/bỏ qua.
- Dashboard/Machines: nhiều WebSocket event trong 5 giây không tạo hơn một silent refresh mỗi trang; consumer chỉ đọc `connected` không re-render theo từng event array.
- Machines/Audit: nhập search không dựng lại bảng khi data không đổi; bảng cập nhật khi response mới về.
- Các select organization không gọi `flattenOrgTree` mỗi render; API keys không flatten lại cho từng row.
- NotificationsAlerts không gọi initial notification refresh trùng provider.
- Modal dùng chung không còn backdrop/sticky-header blur gây repaint toàn viewport.
- `cd portal && npm run typecheck && npm run build` pass.
- `git diff --check` pass; không có file `server/` hoặc `deepagent/` bị thêm vào diff của implementation.
