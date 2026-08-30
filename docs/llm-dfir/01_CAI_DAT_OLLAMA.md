# 01 — Cài đặt Ollama (LLM Local) cho Endpoint Windows / Server

> **Mục tiêu:** Chạy 1 LLM model local, tương thích OpenAI API, phục vụ phân tích DFIR qua Velociraptor.
> **Áp dụng:** Endpoint Windows 10/11 (RAM ≥ 16GB) hoặc Server Linux (RAM ≥ 32GB, có GPU càng tốt).

---

## 1. Chọn model phù hợp

| Use case | Model khuyến nghị | Quant | RAM tối thiểu | Ghi chú |
|---|---|---|---|---|
| Pilot, máy trạm 16GB | `qwen2.5:14b-instruct-q4_K_M` | Q4 | 10 GB | **Tiếng Việt tốt** |
| Máy trạm 32GB, có GPU | `qwen2.5:32b-instruct-q4_K_M` | Q4 | 22 GB | Phân tích sâu hơn |
| Server GPU (A100 40GB) | `llama-3.3-70b-instruct-q3_K_M` | Q3 | 38 GB | Chất lượng cao nhất |
| Nhẹ, nhanh (8GB RAM) | `llama3.2:3b-instruct-q5_K_M` | Q5 | 4 GB | Chỉ triage cơ bản |
| Tiếng Anh chuyên sâu | `llama3.1:8b-instruct-q5_K_M` | Q5 | 6 GB | Tài liệu MITRE ATT&CK chuẩn |

> **Khuyến nghị cho Hà Tĩnh CATP:** `qwen2.5:14b-instruct-q4_K_M` — cân bằng tiếng Việt + tốc độ + tài nguyên.

---

## 2. Cài đặt Ollama

### 2.1 Windows (endpoint)

```powershell
# Tải installer
winget install Ollama.Ollama

# Hoặc tải trực tiếp
# https://ollama.com/download/OllamaSetup.exe

# Verify
ollama --version
# ollama version 0.5.x
```

Ollama mặc định chạy `http://127.0.0.1:11434` và OpenAI-compatible tại `http://127.0.0.1:11434/v1`.

### 2.2 Linux server (khuyến nghị cho tier-2)

```bash
# Ubuntu 22.04+ / Debian 12+
curl -fsSL https://ollama.com/install.sh | sh

# Cấu hình chạy như service
sudo systemctl enable ollama
sudo systemctl start ollama

# Cho phép bind 0.0.0.0 (nếu cần truy cập từ máy khác trong LAN)
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_ORIGINS=*"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama

# Verify
curl http://127.0.0.1:11434/api/tags
```

### 2.3 Docker (server tập trung)

```yaml
# deploy/llm/docker-compose.yml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    environment:
      - OLLAMA_KEEP_ALIVE=24h
      - OLLAMA_NUM_PARALLEL=4
      - OLLAMA_MAX_LOADED_MODELS=2
    # Nếu có GPU NVIDIA
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:11434/api/tags"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  ollama_data:
```

```bash
cd deploy/llm && docker compose up -d

# Pull model (chạy 1 lần)
docker exec ollama ollama pull qwen2.5:14b-instruct-q4_K_M
```

---

## 3. Pull model và test

```bash
# Pull model (~9GB)
ollama pull qwen2.5:14b-instruct-q4_K_M

# Test nhanh
ollama run qwen2.5:14b-instruct-q4_K_M "Xin chào, bạn có thể giúp tôi phân tích log Windows không?"

# Test OpenAI-compatible API
curl http://127.0.0.1:11434/v1/models

curl http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:14b-instruct-q4_K_M",
    "messages": [
      {"role": "user", "content": "Tóm tắt 1+1"}
    ],
    "temperature": 0.0
  }'
```

---

## 4. Cấu hình trên Portal

1. Đăng nhập Super Admin
2. Vào **/admin/llm-dfir/settings**
3. Form:
   - **Provider**: `Ollama`
   - **Base URL**: `http://127.0.0.1:11434/v1` (local) hoặc `http://10.0.0.5:11434/v1` (server LAN)
   - **API Key**: (để trống nếu Ollama local)
   - **Model**: `qwen2.5:14b-instruct-q4_K_M`
   - **Fallback Model**: `qwen2.5:7b-instruct-q4_K_M` (model nhỏ hơn nếu model chính lỗi)
   - **System Prompt**: (để trống, dùng mặc định)
   - **Max Tokens**: 4096
   - **Temperature**: 0.0
4. Bấm **"Test connection"** → chờ ~5s → OK nếu thấy danh sách model
5. Bấm **"Lưu"**

---

## 5. Khắc phục sự cố

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `connection refused` | Ollama chưa chạy | `systemctl start ollama` (Linux) hoặc mở app Ollama (Windows) |
| `model not found` | Chưa pull model | `ollama pull <model>` |
| `out of memory` | Model quá lớn | Dùng quant thấp hơn (q3_K_M) hoặc model nhỏ hơn |
| Response rất chậm (>60s) | CPU thuần, không GPU | Acceptable; hoặc chuyển sang model 7B |
| `OLLAMA_ORIGINS` error | Browser CORS | Set `OLLAMA_ORIGINS=*` (chỉ LAN) hoặc dùng qua server portal |
| Port 11434 bị firewall chặn | Windows Firewall | `New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow` |

---

## 6. Bảo mật Ollama khi bind ra LAN

```bash
# Nếu OLLAMA_HOST=0.0.0.0, BẮT BUỘC:
# 1. Chỉ bind trong VLAN nội bộ (firewall)
sudo ufw allow from 10.0.0.0/8 to any port 11434
sudo ufw deny 11434

# 2. Bật reverse proxy có auth (nginx)
# deploy/llm/nginx-ollama.conf (xem file kèm theo)
```

Nếu cần public ra ngoài, **BẮT BUỘC** dùng nginx + BasicAuth + TLS:
```nginx
server {
  listen 443 ssl http2;
  server_name llm.internal.gov.vn;
  ssl_certificate     /etc/ssl/certs/llm.crt;
  ssl_certificate_key /etc/ssl/private/llm.key;

  auth_basic "LLM API";
  auth_basic_user_file /etc/nginx/.htpasswd;

  location /v1/ {
    proxy_pass http://127.0.0.1:11434/v1/;
    proxy_set_header Host $host;
    proxy_read_timeout 300s;  # LLM có thể chậm
    proxy_send_timeout 300s;
  }
}
```

Trong Portal, base URL sẽ là `https://llm.internal.gov.vn/v1`, API key là `user:password` base64.

---

## 7. Nâng cấp / gỡ cài

```bash
# Update Ollama
curl -fsSL https://ollama.com/install.sh | sh    # Linux
winget upgrade Ollama.Ollama                     # Windows

# Xoá model không dùng
ollama rm llama3.1:8b-instruct-q5_K_M
ollama list                                      # xem model đang có

# Gỡ hoàn toàn
sudo systemctl stop ollama
sudo rm -rf /usr/local/bin/ollama /usr/share/ollama
# Windows: Programs & Features → Uninstall
```

---

## 4b. Cấu hình Hermes Agent (Nous Research)

[Hermes Agent](https://hermes-agent.nousresearch.com/) là 1 agent AI từ **Nous Research** — khác với LLM thông thường ở chỗ có thể **tự gọi tools** (Velociraptor, file system, shell, web search) để hoàn thành task đa bước. Rất phù hợp cho DFIR vì có thể tự:
- Gọi Velociraptor artifact
- Đọc file log
- Tìm kiếm OSINT
- Suy luận nhiều bước

### Cài đặt Hermes Agent (chạy ở server trung tâm)

```bash
# Xem hướng dẫn cài tại: https://hermes-agent.nousresearch.com/docs/getting-started/quickstart
# Mặc định Hermes serve OpenAI-compatible API tại http://localhost:8642/v1
# Model: "hermes-agent"
# Auth: Bearer <API_SERVER_KEY> (default dev: "change-me-local-dev")
```

### Cấu hình trên Portal

1. Mở **/admin/llm-dfir/settings**
2. **Provider**: chọn `Hermes Agent (Nous Research) — OpenAI-compatible` (model tự điền `hermes-agent`)
3. **Base URL**: `http://<hermes-host>:8642/v1` (vd `http://10.0.0.5:8642/v1` nếu chạy server trung tâm)
4. **API Key**: `<API_SERVER_KEY>` của Hermes
5. **Allow cloud**: bật lên (Hermes là remote service)
6. **Bấm "Test connection"** → chờ ~5s → OK
7. Lưu

### So sánh Hermes vs Ollama thuần

| Tiêu chí | Ollama + LLM 14B | Hermes Agent |
|---|---|---|
| Chi phí | $0 (local) | $0 nếu self-host |
| Data ra ngoài máy | Không | Tùy setup |
| Multi-step reasoning | Yếu (chỉ text) | Mạnh (gọi tools) |
| Tự gọi Velociraptor artifact | Không (orchestrator phải bundle) | Có (qua tool gateway) |
| Streaming | Tuỳ model | Có (SSE) |
| Inline image | Tuỳ model | Có |
| Phù hợp cho DFIR | Triage cơ bản | Phân tích sâu, multi-step |

**Khuyến nghị cho Hà Tĩnh CATP**: dùng **Ollama local** cho máy trạm analyst (privacy), dùng **Hermes self-host** ở server trung tâm cho deep investigation khi cần multi-step.
