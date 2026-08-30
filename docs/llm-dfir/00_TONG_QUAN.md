# Tích hợp LLM vào Velociraptor cho DFIR — Tổng quan & Kiến trúc

> **Căn cứ:** dự án IT Asset Inventory — Công an tỉnh Hà Tĩnh (`KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md` v1.2, `PLAN_THUC_HIEN.md` v1.3)
> **Phạm vi tài liệu:** Nghiên cứu + kế hoạch tích hợp Model LLM (Local/Cloud) để hỗ trợ phân tích, điều tra sự cố an ninh mạng qua Velociraptor.
> **Phiên bản:** v1.0 — 2026-08-29

---

## 1. BỐI CẢNH

Dự án hiện **đã có sẵn**:
- Tích hợp Velociraptor Server (`server/app/services/velociraptor.py` — 728 dòng) + REST/VQL wrapper
- Background sync hostname ↔ client_id mỗi 5 phút (`velociraptor_sync.py`)
- Cấu hình Velociraptor (`VelociraptorConfig` table) với allowlist 15 artifact read-only
- DFIR Hunt/Collect/Schedule API (`server/app/api/routes/velociraptor.py` — 1333 dòng)
- Top 10 sự kiện (`velociraptor_top10.py`)
- Monitor loop chạy nền (`services/monitor.py`)

**Chưa có**: tự động phân tích log bằng AI. Hiện tại admin phải:
1. Mở Velociraptor GUI thủ công
2. Đọc JSON thô từ flow results
3. Tự đối chiếu, đánh giá
4. Viết báo cáo bằng tay

**Mục tiêu tích hợp LLM**:
- (T1) Cho phép Super Admin cấu hình 1 hoặc nhiều LLM backend trên portal
- (T2) Thêm endpoint `POST /api/admin/llm-dfir/investigate` — nhận machine_id, tự động:
  - Trigger Velociraptor collect các artifact phù hợp
  - Poll kết quả
  - Gọi LLM phân tích
  - Lưu báo cáo có cấu trúc + cho phép Q&A tiếp
- (T3) Background task tự động scan log định kỳ, gọi LLM tóm tắt anomaly

---

## 2. KIẾN TRÚC ĐỀ XUẤT

### 2.1 Sơ đồ tổng quan

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         PORTAL (Next.js)                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ /admin/llm-dfir/settings  — cấu hình LLM (1 row)               │    │
│  │ /admin/llm-dfir/investigations — list báo cáo DFIR              │    │
│  │ /admin/llm-dfir/investigations/[id] — chi tiết + Q&A           │    │
│  │ /machines/[id]  — nút "Điều tra AI" trigger investigate         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
                              │ HTTPS / JWT
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      API SERVER (FastAPI)                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────┐    │
│  │ routes/          │  │ services/        │  │ services/           │    │
│  │  llm_dfir.py     │──│  llm.py          │  │  dfir_investigation │    │
│  │  (CRUD config,   │  │  (OpenAI-compat  │  │  .py (orchestrator) │    │
│  │   investigate,   │  │   client)        │  │                     │    │
│  │   chat)          │  │                  │  │  - trigger hunt     │    │
│  └──────────────────┘  └──────────────────┘  │  - poll flow        │    │
│           │                    │              │  - call LLM         │    │
│           ▼                    ▼              │  - persist report   │    │
│  ┌─────────────────────────────────────────┐  └─────────────────────┘    │
│  │ monitor.py — background task            │            │                │
│  │  * llm_dfir_investigation_runner        │◄───────────┘                │
│  │    (chạy mỗi 30s, xử lý job pending)    │                            │
│  └─────────────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────┘
            │                            │                          │
            ▼                            ▼                          ▼
   ┌──────────────────┐         ┌──────────────────┐       ┌──────────────┐
   │ Velociraptor     │         │ Ollama           │       │ OpenAI/      │
   │ Server (docker)  │         │ 127.0.0.1:11434  │       │ Qwen API     │
   │ :8889 REST       │         │ hoặc server LAN  │       │ (cloud)      │
   └──────────────────┘         └──────────────────┘       └──────────────┘
            │
            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Endpoint (Windows)                                       │
   │  Velociraptor Client ──collect──► gửi về server          │
   │  (artifact results)                                       │
   └──────────────────────────────────────────────────────────┘
```

### 2.2 Các thành phần chính

| Thành phần | File mới / sửa | Vai trò |
|---|---|---|
| **Settings** (env + DB) | `server/app/core/config.py` + bảng `llm_config` | Cấu hình provider, model, API key (mã hoá) |
| **DB models** | `server/app/db/models.py` | `LlmConfig`, `DfirInvestigation`, `DfirInvestigationMessage` |
| **Migration** | `server/alembic/versions/n_llm_dfir_*.py` | Tạo bảng mới |
| **Pydantic schemas** | `server/app/schemas/__init__.py` | Request/response DTO |
| **LLM service** (mới) | `server/app/services/llm.py` | Wrapper OpenAI-compatible (dùng được cho Ollama, vLLM, LocalAI, OpenAI) |
| **Investigation orchestrator** (mới) | `server/app/services/dfir_investigation.py` | Trigger hunt → poll → call LLM → save |
| **API routes** (mới) | `server/app/api/routes/llm_dfir.py` | CRUD config + investigate + chat |
| **Background worker** | `server/app/services/monitor.py` (sửa) | Process job `pending` mỗi 30s |
| **System prompt** | `server/app/services/llm_prompts.py` | Template tiếng Việt cho DFIR |
| **Docs** | `docs/llm-dfir/*` | Hướng dẫn cài đặt, vận hành |

### 2.3 Tại sao chọn OpenAI-compatible API?

- **Ollama** cung cấp `/v1/chat/completions` (tương thích OpenAI)
- **LocalAI** cũng tương thích
- **vLLM** có OpenAI-compatible server
- **OpenAI / Qwen / DeepSeek** đều dùng OpenAI format

→ 1 client duy nhất xử lý được mọi backend, chỉ khác `base_url` + `api_key`.

### 2.4 Bảo mật & Privacy

| Mối đe doạ | Biện pháp |
|---|---|
| Lộ log nhạy cảm ra ngoài | Mặc định `provider=ollama` + `require_approval_for_cloud=true` |
| Lộ API key | AES-256-GCM (`encrypt_aes_gcm`) giống Velociraptor token |
| Prompt injection từ log | System prompt cứng + escape user data; ghi log full prompt/response |
| LLM hallucination | Luôn kèm raw data; LLM chỉ tổng hợp, không tự sinh sự kiện |
| LLM "nhớ" log qua các lần gọi | `temperature=0.0`, không bật memory; reset context mỗi investigation |
| Chi phí cloud API | Token-budget per investigation (default 8K); cost estimate trước khi gọi |

---

## 3. SCHEMA DB (3 bảng mới)

### 3.1 `llm_config` (singleton, id=1)

```sql
CREATE TABLE llm_config (
  id              INTEGER PRIMARY KEY DEFAULT 1,
  enabled         BOOLEAN NOT NULL DEFAULT FALSE,
  provider        VARCHAR(32) NOT NULL DEFAULT 'ollama',  -- ollama|openai|localai|vllm|custom
  base_url        VARCHAR(512) NOT NULL,                  -- http://127.0.0.1:11434/v1
  api_key_encrypted TEXT,                                 -- AES-256-GCM (None với Ollama local)
  model           VARCHAR(128) NOT NULL,                  -- llama3.1:8b-instruct-q5_K_M
  fallback_model  VARCHAR(128),                           -- model phụ khi model chính lỗi
  system_prompt   TEXT,                                   -- custom system prompt (optional)
  max_tokens      INTEGER NOT NULL DEFAULT 4096,
  temperature     NUMERIC(3,2) NOT NULL DEFAULT 0.0,
  request_timeout INTEGER NOT NULL DEFAULT 120,
  max_context_chars INTEGER NOT NULL DEFAULT 200000,      -- giới hạn log đưa vào prompt
  allow_cloud     BOOLEAN NOT NULL DEFAULT FALSE,         -- cho phép gọi OpenAI/Qwen API?
  daily_token_budget INTEGER,                             -- optional: chặn chi phí
  tokens_used_today INTEGER NOT NULL DEFAULT 0,
  tokens_reset_at  TIMESTAMPTZ,
  test_status     VARCHAR(32),                            -- ok|error|untested
  test_error      TEXT,
  test_at         TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by      UUID REFERENCES users(id)
);
```

### 3.2 `dfir_investigations` (mỗi lần điều tra 1 row)

```sql
CREATE TABLE dfir_investigations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  machine_id      UUID NOT NULL REFERENCES machines(id),
  velociraptor_client_id VARCHAR(64),
  hunt_id         VARCHAR(64),                  -- Velociraptor hunt id (cho multi-artifact)
  artifacts       JSONB NOT NULL,               -- ["Windows.EventLogs.LogFile", ...]
  status          VARCHAR(32) NOT NULL DEFAULT 'pending',  
                  -- pending|running|collecting|analyzing|completed|failed|timeout
  llm_provider    VARCHAR(32),
  llm_model       VARCHAR(128),
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  estimated_cost_usd NUMERIC(10,6),
  report_markdown TEXT,                         -- báo cáo cuối cùng
  severity        VARCHAR(16),                  -- critical|high|medium|low|info
  findings_count  INTEGER,
  raw_artifacts   JSONB,                        -- lưu JSON thu thập (cho audit)
  error           TEXT,
  requested_by    UUID NOT NULL REFERENCES users(id),
  started_at      TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.3 `dfir_investigation_messages` (chat Q&A với LLM về cuộc điều tra)

```sql
CREATE TABLE dfir_investigation_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id UUID NOT NULL REFERENCES dfir_investigations(id) ON DELETE CASCADE,
  role            VARCHAR(16) NOT NULL,  -- system|user|assistant
  content         TEXT NOT NULL,
  tokens          INTEGER,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 4. FLOW NGHIỆP VỤ CHÍNH

### 4.1 Admin cấu hình LLM (lần đầu)

```
1. Admin mở /admin/llm-dfir/settings
2. Form: provider=ollama, base_url=http://127.0.0.1:11434/v1, model=llama3.1:8b
3. Submit → POST /api/admin/llm-dfir/config
4. Server lưu DB, mã hoá api_key nếu có
5. Admin bấm "Test connection" → POST /api/admin/llm-dfir/config/test
6. Server gọi GET {base_url}/models → trả về danh sách model available
7. UI hiển thị: ✓ Kết nối OK, 12 model khả dụng
```

### 4.2 Điều tra 1 máy (workflow chính)

```
┌──────────────────────────────────────────────────────────────────────┐
│ 0. User mở /machines/[id] → bấm "Điều tra AI"                       │
│ 1. UI gọi POST /api/admin/llm-dfir/investigate {machine_id,         │
│    artifacts: [Windows.EventLogs.LogFile, Windows.System.Pslist,    │
│                Windows.Network.Netstat,                              │
│                Windows.Persistence.PermanentWMIBackdoor,             │
│                Windows.Forensics.Prefetch]}                          │
│ 2. Server tạo DfirInvestigation(status=pending)                     │
│ 3. Background worker (chạy mỗi 30s) nhặt job pending:               │
│    a. Set status=running                                             │
│    b. Gọi Velociraptor.collect_artifact(client_id, artifacts)        │
│    c. Lưu hunt_id; set status=collecting                             │
│ 4. Background worker tiếp tục poll:                                 │
│    a. Mỗi 10s gọi Velociraptor.get_flow(flow_id)                    │
│    b. Khi flow.status="OK" → lấy results JSON                        │
│    c. Set status=analyzing                                           │
│ 5. Service bundle data:                                              │
│    - Rút trích key columns (ProcessName, CommandLine, ParentImage,  │
│      DestinationIp, EventID, TargetObject...)                        │
│    - Cắt còn max_context_chars (200K mặc định)                       │
│ 6. Build prompt tiếng Việt:                                          │
│    [System] Bạn là chuyên gia DFIR, hãy phân tích...                │
│    [User] Dữ liệu thu thập:                                         │
│      ## Windows.System.Pslist (1,234 process)                       │
│      PID 1234  cmd.exe  /c whoami                                   │
│      ...                                                             │
│      ## Windows.EventLogs.LogFile (5,678 events)                    │
│      ...                                                             │
│    Hãy: 1) Tóm tắt tình trạng 2) Liệt kê dấu hiệu đáng ngờ        │
│         3) Đánh giá severity 4) Đề xuất hành động                    │
│ 7. Gọi LLM (timeout 120s)                                           │
│ 8. Lưu report_markdown + tokens_used + severity vào DB             │
│ 9. Set status=completed, completed_at=NOW                           │
│ 10. UI polling /api/admin/llm-dfir/investigations/[id] → render    │
│     - Executive summary (markdown)                                  │
│     - Severity badge                                                 │
│     - Findings table (sortable)                                      │
│     - Raw data button → JSON                                         │
│     - Chat input: "Hỏi tiếp về..."                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.3 Q&A tiếp theo

```
1. User nhập "Có dấu hiệu crypto miner không?"
2. POST /api/admin/llm-dfir/investigations/[id]/chat {message}
3. Server build context mới:
   - System prompt gốc
   - Tất cả messages trước (user + assistant)
   - Câu hỏi mới
4. Gọi LLM, lưu 2 message mới
5. Trả response
```

### 4.4 Background scan định kỳ (optional, Phase 2)

```
Mỗi 6 giờ:
  1. Với mỗi machine online:
     - Lấy kết quả artifact "Top 10 sự kiện bất thường" (đã có)
     - Gọi LLM tóm tắt thành 1 câu tiếng Việt
     - Nếu severity >= high → sinh alert + gửi Telegram/email
```

---

## 5. BẢO MẬT & AUDIT

| Item | Cách xử lý |
|---|---|
| Lưu API key | AES-256-GCM qua `encrypt_aes_gcm` (đã có sẵn) |
| Audit log cập nhật config | `append_audit(action="llm.config.update", ...)` |
| Audit log trigger investigate | `append_audit(action="llm.investigate.start", ...)` |
| Quyền truy cập | `@require_super_admin()` (giống Velociraptor config) |
| Rate limit investigate | max 5 investigate/giờ/máy (chống abuse) |
| Mask API key khi trả về API | `api_key_masked: "oll-***xyz"` |
| CORS LLM base_url | Chỉ cho phép http://, https://, hoặc host nội bộ |
| Dữ liệu nhạy cảm (SĐT, CCCD) | Tự động mask trước khi đưa vào prompt |
| Test connection timeout | 10s riêng cho endpoint check |

---

## 6. CHI PHÍ & HIỆU NĂNG

| Mô hình | VRAM/RAM | Tốc độ (8K ctx) | Chất lượng | Chi phí |
|---|---|---|---|---|
| `llama3.1:8b-instruct-q5_K_M` | 6 GB | 30-50 tok/s | Tốt cho tiếng Anh | $0 (local) |
| `qwen2.5:14b-instruct-q4_K_M` | 10 GB | 20-30 tok/s | Tốt cho tiếng Việt | $0 (local) |
| `llama-3.3-70b-instruct-q3` | 40 GB | 5-10 tok/s | Rất tốt | $0 (local, cần GPU) |
| `gpt-4o-mini` (OpenAI) | 0 | 2-5s | Rất tốt | $0.15/$0.6 per 1M tok |
| `qwen-plus` (Alibaba) | 0 | 3-8s | Tốt tiếng Việt | ¥0.0008/1K tok (rất rẻ) |
| `deepseek-chat` | 0 | 3-5s | Tốt | ¥0.001/1K tok |

**Khuyến nghị cho Hà Tĩnh CATP:**
- **Pilot**: Ollama + `qwen2.5:14b-instruct-q4_K_M` (hỗ trợ tiếng Việt tốt, chạy được trên máy trạm 16GB RAM)
- **Production tier-2**: Server trung tâm có GPU → vLLM + Qwen2.5-32B-Instruct
- **Dự phòng cloud**: Qwen-Plus API cho sự cố lớn (cần approval)

---

## 7. ROADMAP TRIỂN KHAI

| Phase | Thời gian | Nội dung |
|---|---|---|
| **P0** — thiết kế | Tuần 1 | Tài liệu này + review kiến trúc |
| **P1** — settings + LLM wrapper | Tuần 2 | Bảng `llm_config`, service `llm.py`, route config CRUD, test connection |
| **P2** — investigation core | Tuần 3-4 | `dfir_investigation.py`, background worker, route investigate + chat |
| **P3** — UI portal | Tuần 5 | 3 trang: settings / investigations list / investigation detail với chat |
| **P4** — pilot | Tuần 6-7 | Cài Ollama + qwen2.5:14b trên 3 máy analyst; chạy thử trên 5 máy thật |
| **P5** — tối ưu | Tuần 8 | Thêm prompt caching, batch process, dashboard tổng hợp |

---

## 8. FILE MỚI / SỬA

### 8.1 File mới (cần tạo)
- `server/alembic/versions/n2o3p4q5r6s7_llm_dfir.py` — migration
- `server/app/services/llm.py` — LLM wrapper
- `server/app/services/llm_prompts.py` — system prompt
- `server/app/services/dfir_investigation.py` — orchestrator
- `server/app/api/routes/llm_dfir.py` — API routes
- `portal/src/app/(portal)/admin/llm-dfir/settings/page.tsx`
- `portal/src/app/(portal)/admin/llm-dfir/investigations/page.tsx`
- `portal/src/app/(portal)/admin/llm-dfir/investigations/[id]/page.tsx`
- `deploy/llm/ollama.service` — systemd unit
- `docs/llm-dfir/01_CAI_DAT_OLLAMA.md` — hướng dẫn cài Ollama
- `docs/llm-dfir/02_VAN_HANH.md` — runbook vận hành
- `docs/llm-dfir/03_PROMPT_TEMPLATES.md` — thư viện prompt

### 8.2 File sửa
- `server/app/core/config.py` — thêm `llm_*` settings (defaults + env)
- `server/.env.example` — thêm block LLM_*
- `server/app/db/models.py` — thêm 3 class model
- `server/app/schemas/__init__.py` — thêm pydantic DTO
- `server/app/main.py` — include router
- `server/app/services/monitor.py` — thêm `_run_pending_investigations` + đăng ký
- `server/app/api/routes/velociraptor.py` — thêm nút "Điều tra AI" (hoặc link sang route mới)

Xem chi tiết ở các file tiếp theo trong thư mục `docs/llm-dfir/`:
- `01_CAI_DAT_OLLAMA.md` — cài Ollama + pull model
- `02_SETTINGS_API.md` — code settings + API CRUD
- `03_LLM_SERVICE.md` — code LLM wrapper
- `04_INVESTIGATION_FLOW.md` — code orchestrator + monitor
- `05_API_ROUTES.md` — code API
- `06_UI_PORTAL.md` — code Next.js pages
- `07_VAN_HANH.md` — runbook
- `08_SECURITY.md` — security checklist
