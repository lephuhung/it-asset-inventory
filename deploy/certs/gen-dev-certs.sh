#!/usr/bin/env bash
# Sinh chứng chỉ dev tạm để nginx + agent mTLS demo được (KHÔNG dùng cho production).
# Tạo: deploy/certs/{server.key,server.crt,ca.crt,agent.key,agent.crt}
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERTS="$ROOT/certs"
mkdir -p "$CERTS"

echo "[*] Sinh CA dev tạm..."
openssl genrsa -out "$CERTS/ca.key" 4096 2>/dev/null
openssl req -x509 -new -nodes -key "$CERTS/ca.key" -sha256 -days 3650 \
  -subj "/C=VN/O=OrgInventory/CN=Inventory Dev CA" -out "$CERTS/ca.crt"

echo "[*] Sinh server cert (CN=inventory.local) - cho nginx TLS..."
openssl genrsa -out "$CERTS/server.key" 2048 2>/dev/null
openssl req -new -key "$CERTS/server.key" -subj "/CN=inventory.local" -out "$CERTS/server.csr"
cat > "$CERTS/openssl-server.ext" <<'EOF'
subjectAltName=DNS:inventory.local,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
EOF
openssl x509 -req -in "$CERTS/server.csr" -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" \
  -CAcreateserial -days 365 -sha256 -extfile "$CERTS/openssl-server.ext" \
  -out "$CERTS/server.crt"

echo "[*] Sinh agent client cert mẫu (CN=test-agent-uuid) - cho mTLS demo..."
openssl genrsa -out "$CERTS/agent.key" 2048 2>/dev/null
openssl req -new -key "$CERTS/agent.key" -subj "/CN=test-agent-uuid" -out "$CERTS/agent.csr"
cat > "$CERTS/openssl-client.ext" <<'EOF'
extendedKeyUsage=clientAuth
EOF
openssl x509 -req -in "$CERTS/agent.csr" -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" \
  -CAcreateserial -days 365 -sha256 -extfile "$CERTS/openssl-client.ext" \
  -out "$CERTS/agent.crt"

# nginx cần CA bundle (root + intermediate trong production)
cat "$CERTS/ca.crt" > "$CERTS/ca.bundle"

echo "[OK] Chứng chỉ dev đã tạo:"
ls -1 "$CERTS"
echo
echo "Nếu xài nginx: 'ssl_certificate $CERTS/server.crt', 'ssl_client_certificate $CERTS/ca.crt'."
echo "Chạy: bash deploy/certs/gen-dev-certs.sh"
