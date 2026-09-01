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

`POST {DEEPAGENT_URL}/v1/investigations` với `Authorization: Bearer <service-token>`.

```json
{
  "schema_version": "dfir.deepagent.request/1.1",
  "investigation_id": "uuid",
  "client_id": "C.x",
  "hostname": "WS-01",
  "time_range": {"from": "2026-08-31T00:00:00Z", "to": "2026-08-31T12:00:00Z"},
  "suspicious_activity": "PowerShell bất thường"
}
```

Backend chọn model, URL và policy agent theo cấu hình portal. Khi bổ sung runtime profile, chỉ truyền snapshot cho đúng job; không ghi API key vào Markdown, log, `raw_response` hoặc trạng thái job.

`system_prompt` là một phần của **LLM config / agent profile** tại portal, không phải input của modal investigation. Backend snapshot profile này khi dispatch để job đang chạy không đổi policy nếu admin cập nhật cấu hình. DeepAgent nối nó **sau** system prompt DFIR cố định; prompt cấu hình không thể nới allowlist, target lock hoặc các yêu cầu evidence-backed.

## Tiến độ

`POST /api/external/llm-dfir/investigations/{id}/status`, scope `investigation:write`.

```json
{"external_job_id":"deepagent-uuid","phase":"collecting","progress_percent":55,"current_step":2,"total_steps":5,"message":"Đang truy vấn event log"}
```

Phase chuẩn: `queued`, `verifying_target`, `planning`, `collecting`, `assessing`, `rendering`, `completed`, `failed`. Backend lưu snapshot để portal hiển thị song song nhiều investigation. Endpoint này không tạo notification.

## Kết quả cuối

`POST /api/external/llm-dfir/investigations/{id}/result`, scope `investigation:write`, header `X-Idempotency-Key: <external_job_id>`.

Body gồm `report_markdown`, `severity`, `findings_count`, `findings`, `iocs`, `llm_provider`, `llm_model`, `external_job_id` và tùy chọn `error`. Backend là nơi duy nhất lưu kết quả và gửi notification.

## Cấu hình Velociraptor

Super Admin nhập URL bằng `PUT /api/admin/velociraptor/config` và upload `api_client.yaml` qua `POST /api/admin/velociraptor/config/api-client/upload`. Backend validate, mã hoá file và không trả private key. Test trực tiếp Velociraptor qua `POST /api/admin/velociraptor/test`; MCP test cần chạy `list_clients` read-only qua DeepAgent.
