#!/usr/bin/env bash
# build-config-zip.sh — Tao ZIP config-only (~5KB) cho Smart Update mode.
#
# Chi chua:
#   - velociraptor-client.config.yaml  (Velociraptor enroll URL + CA cert)
#
# So voi bundle day du (~50MB), ZIP nay chi ~5KB → tang toc do re-install
# len rat nhieu (5s thay vi 30-60s download).
#
# Usage:
#   bash build-config-zip.sh
#
# Build mot lan moi khi Velociraptor URL/CA cert thay doi (sau khi recreate Velociraptor cert
# hoac doi hostname Portal/Velociraptor).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

WORK_DIR="$SCRIPT_DIR/velociraptor-config-only"
OUT_ZIP="$SCRIPT_DIR/velociraptor-config-only.zip"

echo "=== Build ZIP config-only ==="
mkdir -p "$WORK_DIR"

# Copy README
cat > "$WORK_DIR/README.txt" <<'EOF'
Config-only bundle for Smart Update.

Chứa duy nhất client.config.yaml (Velociraptor) - không có MSI/deb/rpm.
Dùng khi máy đã cài Velociraptor, chỉ cần update URL enrollment.

Size: ~5KB (so với ~50MB cho bundle đầy đủ).
EOF

# Copy client.config.yaml đã được Portal generate (URL đúng)
if [[ -f velociraptor-client.config.yaml ]]; then
    cp velociraptor-client.config.yaml "$WORK_DIR/client.config.yaml"
    echo "[OK] Copy client.config.yaml tu velociraptor-client.config.yaml"
elif [[ -f velociraptor-agent-windows.zip ]]; then
    echo "[INFO] Extract client.config.yaml tu velociraptor-agent-windows.zip"
    unzip -p velociraptor-agent-windows.zip 'velociraptor-agent-windows/client.config.yaml' > "$WORK_DIR/client.config.yaml" 2>/dev/null || \
    unzip -p velociraptor-agent-windows.zip 'client.config.yaml' > "$WORK_DIR/client.config.yaml"
else
    echo "[LOI] Khong tim thay velociraptor-client.config.yaml. Tao file truoc." >&2
    exit 1
fi

# Verify config có server_urls đúng
if ! grep -q 'server_urls:' "$WORK_DIR/client.config.yaml"; then
    echo "[LOI] client.config.yaml khong co server_urls." >&2
    exit 1
fi
echo "[OK] client.config.yaml co server_urls"

# Tạo ZIP (deflate)
rm -f "$OUT_ZIP"
zip -r "$OUT_ZIP" "$(basename "$WORK_DIR")" >/dev/null

size=$(du -h "$OUT_ZIP" | cut -f1)
echo ""
echo "=== Build hoan tat ==="
echo "  File: $OUT_ZIP"
echo "  Size: $size"
echo "  Chua: README.txt, client.config.yaml"
echo ""
echo "Test serve:"
echo "  curl http://10.10.0.241:8000/download/velociraptor-config-only.zip -o /tmp/test.zip"
echo "  unzip -l /tmp/test.zip"
