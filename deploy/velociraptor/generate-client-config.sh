#!/usr/bin/env bash
# generate-client-config.sh — sinh YAML mTLS client config cho Inventory Server portal.
#
# Velociraptor dùng cơ chế CA + mTLS cho API integration. Lệnh
# `velociraptor config api_client` sinh YAML gồm:
#   - ca_certificate: CA cert của Velociraptor Server (để Inventory Server verify)
#   - client_cert:     client cert (do Velociraptor CA ký — chứng minh identity)
#   - client_private_key: private key tương ứng (KHÔNG share lộ)
#
# ⚠️ CẢNH BÁO:
#   - client_private_key là BÍ MẬT — paste toàn bộ YAML vào portal qua HTTPS,
#     KHÔNG gửi qua email/chat. Portal mã hoá AES-256-GCM rồi lưu DB.
#   - Chỉ Velociraptor-native — KHÔNG phải API key dạng base64 (Velociraptor
#     default authenticator là HTTP Basic, không phải Bearer).
#
# CÁCH DÙNG:
#   1. cd deploy/velociraptor
#   2. bash generate-client-config.sh "inventory-portal"
#      → In ra YAML (~3KB). PASTE TOÀN BỘ vào portal /dfir/settings
#        (ô "Client Config (YAML)" → bấm "Lưu").
#   3. Nếu Velociraptor Server dùng authenticator mặc định (Basic) thì mTLS cert
#      bị IGNORE — phải đổi Velociraptor authenticator sang `type: Certs` (xem
#      RUNBOOK mục 8.6 + docs Velociraptor server-automation).
#      Cách đơn giản hơn cho hầu hết use case: dùng HTTP Basic
#      (username + password) — portal có sẵn form cho cả 2 cách.
#
# LƯU Ý:
#   - Script idempotent — nếu cert đã tồn tại (cùng name), sẽ sinh cert mới
#     với suffix timestamp (Velociraptor không cho phép trùng CN).
#   - File YAML sinh ra ở /tmp bên trong container; script tự đọc + in ra
#     stdout, KHÔNG lưu trên host.
#   - Nếu container chưa sẵn sàng (đang init), đợi healthcheck OK rồi chạy lại.

set -euo pipefail

NAME="${1:-inventory-portal}"
CONTAINER="${VELOCIRAPTOR_CONTAINER:-velociraptor}"
CONFIG_PATH="/etc/velociraptor/server.config.yaml"
OUTPUT_FILE="/tmp/${NAME}-$(date +%Y%m%d%H%M%S).yaml"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "[!] Container '$CONTAINER' không tồn tại. Chạy: docker compose up -d" >&2
  exit 1
fi

# Ch� config sinh xong (entrypoint generate config lần đầu ~10-30s)
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER" test -f "$CONFIG_PATH" 2>/dev/null; then
    break
  fi
  echo "… đợi $CONFIG_PATH sinh xong (lần đầu init có thể ~30s)"
  sleep 2
done

if ! docker exec "$CONTAINER" test -f "$CONFIG_PATH" 2>/dev/null; then
  echo "[!] Chưa thấy $CONFIG_PATH sau 60s — xem logs: docker logs $CONTAINER" >&2
  exit 1
fi

# Tạo cert — thêm suffix nếu cert cùng name đã tồn tại
# (Velociraptor reject cert trùng CN; portal tự lưu nhiều cert với CN khác nhau)
CLIENT_NAME="$NAME"
if docker exec "$CONTAINER" velociraptor --config "$CONFIG_PATH" \
    config api_client list 2>/dev/null | grep -q "${NAME}"; then
  CLIENT_NAME="${NAME}-$(date +%Y%m%d%H%M%S)"
  echo "[i] Cert '$NAME' đã tồn tại → sinh cert mới với name '$CLIENT_NAME'."
fi

echo ">>> Sinh client config YAML cho '$CLIENT_NAME' (role=administrator) trong container '$CONTAINER' …"

# Sinh YAML trong container, đọc ra stdout
if docker exec "$CONTAINER" velociraptor --config "$CONFIG_PATH" \
    config api_client --name "$CLIENT_NAME" --role administrator \
    "$OUTPUT_FILE" 2>&1; then
  echo ">>> Đọc YAML từ container và in ra stdout:"
  echo ""
  echo "----- COPY TỪ ĐÂY -----"
  docker exec "$CONTAINER" cat "$OUTPUT_FILE"
  echo "----- ĐẾN ĐÂY -----"
  echo ""
  echo "==> Paste toàn bộ YAML (kể cả dòng ----- COPY / ĐẾN ĐÂY) vào portal /dfir/settings."
  echo "    Lưu ý: KHÔNG share YAML qua email/chat — chứa private key."
else
  echo "[!] Sinh client config thất bại — xem logs ở trên." >&2
  exit 1
fi
