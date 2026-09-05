# Contract Backend – DeepAgent LangGraph

DeepAgent là worker LangGraph độc lập. Backend là nguồn cấu hình và trạng thái chính thức; DeepAgent không tạo notification.

## Luồng

```text
Backend → POST /v1/investigations → DeepAgent
DeepAgent → POST /status             → Backend (nhiều lần, không notification)
DeepAgent → POST /result             → Backend (một lần, lưu Markdown + notification)
```

Mỗi job được định danh bởi `investigation_id` (idempotency scope) và `external_job_id` (DeepAgent job).

## Dispatch

`POST http://deepagent:8090/v1/investigations` trong Docker network với `Authorization: Bearer <service-token>`. URL và token do Compose quản lý, không phải input Portal.

```json
{
  "schema_version": "dfir.deepagent.request/1.2",
  "investigation_id": "uuid",
  "client_id": "C.x",
  "hostname": "WS-01",
  "target_platform": "windows",
  "time_range": {"from": "2026-08-31T00:00:00Z", "to": "2026-08-31T12:00:00Z"},
  "suspicious_activity": "PowerShell bất thường"
}
```

Backend chọn model, URL và policy agent theo cấu hình portal. Khi bổ sung runtime profile, chỉ truyền snapshot cho đúng job; không ghi API key vào Markdown, log, `raw_response` hoặc trạng thái job.

`system_prompt` là một phần của **LLM config / agent profile** tại portal, không phải input của modal investigation. Backend snapshot profile này khi dispatch để job đang chạy không đổi policy nếu admin cập nhật cấu hình. DeepAgent ghép prompt này sau `INVARIANT_BOUNDARY` trong cùng một system message. Prompt database điều khiển cách triage; boundary điều khiển cách đánh giá bằng chứng và bảo vệ dữ liệu đầu ra. User message mô tả nghi vấn luôn nằm trong human message riêng.

Lượt triage ban đầu bị giới hạn cứng tối đa 3 tool. Trên Windows, prompt hiện chỉ cho phép `windows_pslist`, `windows_netstat_enriched` và `windows_services`; Linux/macOS chỉ dùng tối đa 3 custom artifact tương thích do backend ký phát trong catalog.

## Tiến độ

`POST /api/external/llm-dfir/investigations/{id}/status`, scope `investigation:write`.

```json
{"external_job_id":"deepagent-uuid","phase":"collecting","progress_percent":55,"current_step":2,"total_steps":5,"message":"Đang truy vấn event log"}
```

Phase chuẩn: `queued`, `verifying_target`, `planning`, `collecting`, `assessing`, `rendering`, `completed`, `failed`. Backend lưu snapshot để portal hiển thị song song nhiều investigation. Endpoint này không tạo notification.

## Kết quả cuối

`POST /api/external/llm-dfir/investigations/{id}/result`, scope `investigation:write`, header `X-Idempotency-Key: <external_job_id>`.

Body gồm `report_markdown`, `severity`, `findings_count`, `findings`, `iocs`, `llm_provider`, `llm_model`, `external_job_id` và tùy chọn `error`. Backend là nơi duy nhất lưu kết quả và gửi notification.

DeepAgent thử callback kết quả tối đa 3 lần, giữ nguyên `X-Idempotency-Key` và toàn bộ body. Chỉ HTTP 200 được xem là thành công. `report_markdown` bắt đầu bằng YAML front matter `schema_version: dfir.report/1.0` và được renderer tạo đủ 8 phần: Tóm tắt; Phạm vi và nguồn dữ liệu; Phát hiện; IoC; Dòng thời gian; Đánh giá và kết luận; Khuyến nghị; Hạn chế.

## Độ tin cậy MCP và deadline

DeepAgent áp dụng deadline phía caller cho mọi lệnh gọi MCP (`DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS`, mặc định `180`, khoảng hợp lệ `10–1800`). Khi deadline trước khi tool trả về, DeepAgent:

- log một sự kiện `mcp_tool_call` với `outcome=failed`, `error_type=MCPToolTimeout`, `error_message="MCP tool call exceeded its configured deadline."`, `tool_name` và `timeout_seconds`. Không ghi VQL, YAML, prompt, evidence, kết quả thô hay nội dung lỗi từ bridge.
- nâng `MCPToolTimeout(tool_name)` để graph tiếp tục thay vì dừng.
- chuyển evidence lỗi thành `EvidenceItem(ok=False, timeout=True, error="MCP collection timed out.")`. Raw exception không đi vào evidence, prompt model, report, callback hay log.
- cộng `timed_out_tool_count` vào `job_summary`. Số đếm successful/failed cũ vẫn tương thích.

Một timeout phía DeepAgent chỉ chứng minh cuộc gọi MCP không về trước deadline (gọi là `mcp_call_deadline`); nó KHÔNG phải bằng chứng Velociraptor flow thất bại. Phân loại nguyên nhân flow-level (`client_unavailable`, `collection_timeout`, `flow_error`, `result_read_timeout`) thuộc sở hữu của bridge MCP và chỉ được thực hiện qua patch/fork được theo dõi, áp dụng bằng Dockerfile sau khi clone pinned upstream. Phase 2 của plan DeepAgent MCP reliability phụ trách phần này và phải không chỉnh sửa bridge trong container đang chạy.

Không có automatic duplicate collection retry: sau timeout, chỉ hành động thủ công của operator mới tạo flow mới.

## Cấu hình Velociraptor

Super Admin nhập URL bằng `PUT /api/admin/velociraptor/config` và upload `api_client.yaml` qua `POST /api/admin/velociraptor/config/api-client/upload`. Backend validate, mã hoá file và không trả private key. Nút **Kiểm tra MCP → Velociraptor** gọi backend, backend gửi YAML chỉ qua network Docker tới DeepAgent, và DeepAgent chạy `list_clients(limit=1)` read-only trước khi xóa tệp tạm.
