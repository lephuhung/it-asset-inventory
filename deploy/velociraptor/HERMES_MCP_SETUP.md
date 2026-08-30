# Hermes MCP Integration — Velociraptor gRPC Setup

Để Hermes agent (ở máy khác) có thể dùng `mcp-velociraptor` để query
Velociraptor qua gRPC API, cần 2 thay đổi ở Velociraptor server:

## 1. Expose gRPC API port (docker-compose.yml)

`deploy/velociraptor/docker-compose.yml` cần thêm port mapping:

```yaml
ports:
  - "8889:8889"   # GUI + REST API (đã có)
  - "8888:8000"   # gRPC client enroll (đã có)
  - "18001:8001"  # gRPC API cho api_client (THÊM)
```

`18001` là host port (vì port `8001` trên host bị container khác
chiếm — `hrag-vllm-ocr`). Container vẫn listen ở `8001` (default).

## 2. Bind gRPC API ra 0.0.0.0 (server.config.yaml)

`deploy/velociraptor/etc/server.config.yaml` chứa certificates nên
không commit được. Sửa thủ công sau khi generate config:

```yaml
API:
  bind_address: 0.0.0.0   # đổi từ 127.0.0.1
  bind_port: 8001
  bind_scheme: tcp
```

Restart Velociraptor sau khi sửa:
```bash
cd deploy/velociraptor
docker compose restart
```

## 3. Generate API client credentials cho Hermes

```bash
docker exec velociraptor velociraptor \
  --config /etc/velociraptor/server.config.yaml \
  config api_client --name hermes --role administrator,api /tmp/api_client.yaml

# Copy ra + sửa connection string
docker cp velociraptor:/tmp/api_client.yaml /tmp/api_client.yaml
sed -i 's|api_connection_string:.*|api_connection_string: VelociraptorServer:18001|' \
  /tmp/api_client.yaml
chmod 600 /tmp/api_client.yaml
```

Cert VelociraptorServer có SAN `DNS:VelociraptorServer`. Trên Hermes
machine phải thêm vào `/etc/hosts`:
```
10.10.0.241 VelociraptorServer
```

## 4. Bảo mật

- Cert mTLS hết hạn 2027-08-30 → tạo cron job remind trước ngày đó
- Nên chặn firewall chỉ cho phép IP Hermes (10.10.0.229):
  ```bash
  iptables -A INPUT -p tcp --dport 18001 -s 10.10.0.229 -j ACCEPT
  iptables -A INPUT -p tcp --dport 18001 -j DROP
  ```
- Cert được lưu ở `~/.config/velociraptor/api_client.yaml` trên Hermes,
  chmod 600.
- Cert chứa `administrator,api` role — full quyền admin trên Velociraptor.
  Nếu Hermes bị compromise, attacker có toàn quyền.
