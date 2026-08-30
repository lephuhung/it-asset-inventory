# Hermes Agent — Integration Guide cho IT Asset Inventory

> **Mục đích:** Hướng dẫn team Hermes Agent tích hợp với hệ thống IT Asset Inventory (CATP Hà Tĩnh) để nhận job điều tra từ Velociraptor và push kết quả phân tích về hệ thống.

**Base URL (production):** `https://inventory.example.gov.vn` (sẽ thay bằng domain thật)
**Auth:** API key (Bearer token), lưu trong env `HERMES_API_KEY`
**API version:** v1 (compatible với OpenAI-style REST)

---

## 1. Tổng quan flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. Admin bấm "Điều tra AI" trên trang máy                         │
│  2. Inventory tạo investigation → orchestrator thu thập artifacts    │
│     Velociraptor (collect + parse)                                   │
│  3. Orchestrator set status=analyzing + flag external                │
│  4. Hermes (polling) nhận job qua GET /investigations/pending         │
│  5. Hermes phân tích dữ liệu (gọi tools, suy luận)                  │
│  6. Hermes POST kết quả về /investigations/{id}/result                │
│  7. Inventory lưu report, fire notification cho admin                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Latency mục tiêu:** Hermes nên xử lý mỗi job trong **< 2 phút** (đặt timeout 10 phút).

---

## 2. Authentication

Hermes dùng **API key** (Bearer token). Key do Super Admin tạo qua portal → `/admin/api-keys` với scope `investigation:read investigation:write`.

**Lưu ý:**
- Key chỉ trả 1 lần lúc tạo — lưu vào env `HERMES_API_KEY` ngay.
- Key có thể rotate bất kỳ lúc nào (revoke + tạo mới).

**Ví dụ header:**
```http
Authorization: Bearer hermes_inv_<32-bytes-base64>
```

---

## 3. API Endpoints (3 endpoints chính)

### 3.1 `GET /api/external/llm-dfir/investigations/pending` — Polling job mới

Hermes gọi mỗi **30 giây** để lấy danh sách investigation đang chờ xử lý.

**Auth:** API key với scope `investigation:read` (cũng chấp nhận `investigation:write`).

**Request:**
```http
GET /api/external/llm-dfir/investigations/pending?limit=10
Authorization: Bearer <HERMES_API_KEY>
```

**Response 200:**
```json
[
  {
    "id": "a8e6b44d-027c-43bc-af05-bb4dbd75103f",
    "machine_id": "3f436e4d-3ff9-406a-88b2-70da56647fcb",
    "velociraptor_client_id": "C.aef6d6bedbd2f017",
    "machine_hostname": "DESKTOP-BIS5DD0",
    "machine_fqdn": null,
    "machine_os": null,
    "artifacts": [
      "Windows.System.Pslist",
      "Windows.Network.Netstat"
    ],
    "custom_instructions": "Tập trung vào lateral movement",
    "created_at": "2026-08-30T02:10:00Z",
    "callback_url": "https://inventory.example.gov.vn/api/external/llm-dfir/investigations/a8e6b44d-027c-43bc-af05-bb4dbd75103f/result"
  }
]
```

**Response khi không có job:** `200 []`

**Lưu ý:**
- Mỗi lần Hermes poll, server sẽ mark investigation là `claim` (timestamp `external_polled_at`). Lần poll tiếp theo sẽ không trả investigation này nữa.
- Nếu investigation không được submit trong **10 phút** → auto-fail (timeout).
- Sau khi nhận job, Hermes **chỉ** submit về `callback_url` trong payload (KHÔNG tự ý gọi URL khác).

**Pseudo-code cho Hermes:**
```python
while True:
    resp = requests.get(f"{BASE}/api/external/llm-dfir/investigations/pending", headers=auth)
    for job in resp.json():
        try:
            result = analyze(job)  # gọi Velociraptor, LLM, etc.
            requests.post(job["callback_url"], json=result, headers=auth)
        except Exception as e:
            requests.post(job["callback_url"], json={"error": str(e)}, headers=auth)
    time.sleep(30)
```

---

### 3.2 `POST /api/external/llm-dfir/investigations/{id}/result` — Submit kết quả

Hermes gọi endpoint này khi đã phân tích xong (thành công HOẶC thất bại).

**Auth:** API key với scope `investigation:write`.

**Idempotency:** gửi kèm header `X-Idempotency-Key` (khuyến nghị = Hermes job_id). Server sẽ check key này để chống duplicate khi retry.

**Request — thành công:**
```http
POST /api/external/llm-dfir/investigations/{id}/result
Authorization: Bearer <HERMES_API_KEY>
Content-Type: application/json
X-Idempotency-Key: hermes-job-20260830-abc123
```
```json
{
  "report_markdown": "# Báo cáo điều tra máy DESKTOP-BIS5DD0\n\n**Mức độ:** high\n\n## 1. Tóm tắt\nPhát hiện PowerShell encoded command.\n\n## 2. Phát hiện\n- PowerShell -enc flag (T1059.001)\n- Outbound connection 10.0.0.99:443\n\n## 3. Đề xuất\n1. Kill process PowerShell\n2. Capture memory dump\n3. Block outbound IP",
  "severity": "high",
  "findings_count": 2,
  "findings": [
    {
      "id": "F-001",
      "title": "PowerShell Encoded Command",
      "mitre_id": "T1059.001",
      "severity": "high",
      "evidence": "powershell -enc SQBFAFgAIAAo...",
      "recommendation": "Isolate + memory dump"
    }
  ],
  "iocs": [
    {"type": "ip", "value": "10.0.0.99", "source": "Windows.Network.Netstat"},
    {"type": "hash", "value": "abc123def456", "source": "Windows.System.Pslist"}
  ],
  "llm_provider": "hermes-agent",
  "llm_model": "hermes-agent",
  "input_tokens": 1500,
  "output_tokens": 800,
  "estimated_cost_usd": 0.0023,
  "external_job_id": "hermes-job-20260830-abc123"
}
```

**Request — thất bại (set `error` thay vì report):**
```json
{
  "error": "Velociraptor timeout sau 5 phút",
  "external_job_id": "hermes-job-20260830-abc123"
}
```

**Response 200:**
```json
{
  "id": "a8e6b44d-027c-43bc-af05-bb4dbd75103f",
  "status": "completed",
  "message": "Đã lưu kết quả",
  "notification_id": null
}
```

**Status values:**
- `completed` — report lưu thành công
- `failed` — error được ghi nhận
- `pending` — investigation chưa qua giai đoạn collect (lỗi)

**Side effects sau khi submit thành công:**
- Investigation → status=completed
- Notification tự động gửi tới:
  - Admin đã trigger investigation
  - Tất cả Super Admin
- Notification có thể qua Telegram nếu user link

---

### 3.3 `GET /api/external/llm-dfir/investigations/{id}` — Xem chi tiết 1 investigation (optional)

Dùng để debug hoặc re-fetch job info.

**Auth:** API key với scope `investigation:read` hoặc `investigation:write`.

**Response:** giống item trong array `pending` ở trên.

---

### 3.4 (Optional) `POST /api/external/notifications` — Gửi notification riêng

Ngoài investigation result, Hermes có thể gửi notification độc lập (VD: cảnh báo machine mới có suspicious activity trong khi đang investigate cái khác).

**Auth:** API key với scope `notify:write`.

**Request:**
```http
POST /api/external/notifications
Authorization: Bearer <HERMES_API_KEY>
Content-Type: application/json
X-Idempotency-Key: hermes-notif-001
X-Source: hermes
```
```json
{
  "recipients": {"type": "role", "role": "admin_global"},
  "category": "alert",
  "severity": "warning",
  "title": "Hermes: phát hiện anomaly trên PC-CATP-001",
  "body": "Chi tiết...",
  "link": "/admin/llm-dfir/investigations/abc-123",
  "entity_type": "dfir_investigation",
  "entity_id": "abc-123"
}
```

**Lưu ý quan trọng:** `entity_id` phải là **UUID hợp lệ** nếu bạn muốn link đến investigation thật. Test với ID giả (`"abc-123"`) sẽ gây 422 khi user click vào notification.

---

## 4. Error codes

| Code | Ý nghĩa | Hermes nên làm |
|---|---|---|
| 200 | Thành công | — |
| 204 | Thành công, không có body | — |
| 401 | Missing/invalid API key | Check `HERMES_API_KEY` env |
| 403 | API key thiếu scope | Liên hệ Super Admin cấp scope |
| 404 | Investigation không tồn tại | Bỏ qua job_id |
| 409 | Investigation đang chạy, không thể xoá | (chỉ cho DELETE) |
| 422 | Input không hợp lệ (UUID sai, v.v.) | Check request body/path |
| 500 | Lỗi server | Retry với backoff |

---

## 5. Test thực tế (đã chạy)

| Test | Endpoint | Status | Ghi chú |
|---|---|---|---|
| Không có auth | GET pending | 401 | Đúng |
| API key sai scope (read only) | GET pending | 403 | Đúng |
| API key sai scope | POST result | 403 | Đúng |
| Submit với severity=high | POST result | 200 | Lưu đúng |
| Submit với severity=critical | POST result | 200 | Lưu đúng |
| Idempotency retry (cùng key) | POST result | 200 | Không tạo duplicate |
| Idempotency với key mới | POST result | 200 | Tạo notification mới |
| 404 với ID không tồn tại | GET | 404 | Đúng |
| Investigation invalid UUID | GET | 422 | **KHÔNG gửi invalid UUID!** |

**Test thủ công (Hermes test flow):**
1. Admin bấm "Điều tra AI" trên 1 máy
2. Đợi ~35s cho background worker chạy Velociraptor collect
3. Hermes poll → nhận 1 job
4. Hermes phân tích → POST result
5. Đợi 2s → kiểm tra `/api/admin/llm-dfir/investigations/{id}` thấy `status=completed, severity, findings, iocs`
6. Kiểm tra `/api/notifications` thấy notification mới với source=`hermes`

---

## 6. Field reference

### `severity` (enum)
- `critical` — phát hiện tấn công nghiêm trọng (ransomware, lateral movement confirmed)
- `high` — IoC mạnh cần hành động ngay
- `medium` — suspicious nhưng cần thêm context
- `low` — informational
- `info` — bình thường, không có dấu hiệu tấn công

### `findings` (array)
Mỗi finding:
```json
{
  "id": "F-001",  // unique trong investigation
  "title": "...",  // ngắn gọn, 1 câu
  "mitre_id": "T1059.001",  // optional, MITRE ATT&CK technique
  "severity": "high",  // critical/high/medium/low/info
  "evidence": "...",  // dòng log / hash / IP cụ thể
  "recommendation": "..."  // hành động cần làm
}
```

### `iocs` (array)
```json
{"type": "ip" | "domain" | "hash" | "email" | "url" | "registry" | "process", "value": "...", "source": "..."}
```

### `report_markdown`
Format chuẩn (khuyến nghị, không bắt buộc):
```markdown
# Báo cáo điều tra máy {hostname}
**Mức độ nghiêm trọng:** {severity}
**Số phát hiện:** {N}

## 1. Tóm tắt điều hành
[2-4 câu cho lãnh đạo]

## 2. Phát hiện chi tiết
### 2.1 {tiêu đề}
- **Mô tả:** ...
- **Bằng chứng:** ...
- **MITRE ATT&CK:** Txxxx
- **Mức độ:** ...

## 3. IoC
- ...

## 4. Đề xuất hành động
1. [khẩn cấp]
2. [trong 24h]
3. [theo dõi]

## 5. Hạn chế của dữ liệu
[Artifacts chưa thu thập được, cần thu thập thêm]
```

---

## 7. Open items

| Item | Status | Action |
|---|---|---|
| Webhook push (server → Hermes) | Pending | Hiện tại chỉ support pull. Nếu cần push, thêm endpoint `POST <hermes_url>/webhook/...` |
| Streaming progress | Pending | Hiện tại chỉ submit final result. Có thể thêm `POST /investigations/{id}/progress` cho partial update |
| Multi-job parallel | Supported | Hermes có thể xử lý nhiều job cùng lúc (mỗi investigation độc lập) |
| Retry strategy | Client-side | Hermes tự retry 3 lần với backoff 5s/30s/2m. Nếu vẫn fail → set `error` trong POST result |

---

## 8. Liên hệ

- **Backend team:** dev-inventory@catp.hatinh.gov.vn
- **Slack:** #it-asset-inventory
- **Git:** https://github.com/catp-hatinh/it-asset-inventory (xem `server/app/api/routes/llm_dfir_external.py` để biết chi tiết implementation)
- **OpenAPI spec:** `http://<inventory_url>/openapi.json` (filter path `/api/external/llm-dfir`)

---

**Cập nhật lần cuối:** 2026-08-30
**Phiên bản API:** v1
**Người tạo:** Backend team — Phòng An ninh mạng CATP Hà Tĩnh
