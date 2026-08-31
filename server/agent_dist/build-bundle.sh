#!/usr/bin/env bash
# build-bundle.sh — đóng gói OrgInventoryAgent + Velociraptor vào 1 ZIP duy nhất
#
# Output:
#   ./agent-bundle-windows.zip
#     ├── README.txt                          (hướng dẫn nhanh)
#     ├── install-all.bat                     (master entrypoint — gọi install-all.ps1)
#     ├── install-all.ps1                     (PowerShell: cả 2 agent tuần tự)
#     ├── OrgInventoryAgent.msi               (agent inventory — build bằng WiX trên Windows)
#     ├── velociraptor-windows-amd64.msi      (Velociraptor client gốc Velocidex)
#     └── client.config.yaml                  (Velociraptor client config — URL enroll đúng)
#
# Workflow trên máy Windows sau khi copy bundle:
#   1. Right-click install-all.bat → "Run as administrator"
#   2. Script sẽ hỏi Token + Endpoint (hoặc truyền qua env/argument)
#   3. Cài OrgInventoryAgent trước (cần mTLS với Inventory server)
#   4. Cài Velociraptor + copy client.config.yaml + start service
#   5. Verify cả 2 enroll thành công
#
# Cách build:
#   cd server/agent_dist
#   bash build-bundle.sh
#
# Tuỳ chọn:
#   --inventory-url URL    URL Inventory Server (vd https://agent.gov.vn)
#                         Mặc định: $INVENTORY_URL hoặc hỏi khi cài
#   --veloci-config PATH   Đường dẫn Velociraptor client config (mặc định:
#                         sinh lại từ container Velociraptor đang chạy)
#   --output PATH          Đường dẫn file ZIP output (mặc định ./agent-bundle-windows.zip)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Defaults ──────────────────────────────────────────────────────────────
INVENTORY_URL="${INVENTORY_URL:-}"
VELOCI_CONTAINER="${VELOCI_CONTAINER:-velociraptor}"
OUTPUT="$SCRIPT_DIR/agent-bundle-windows.zip"
VELOCI_CONFIG_SRC=""
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ─── Parse args ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --inventory-url) INVENTORY_URL="$2"; shift 2 ;;
    --veloci-config) VELOCI_CONFIG_SRC="$2"; shift 2 ;;
    --output)        OUTPUT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,28p' "$0"
      exit 0 ;;
    *)
      echo "[!] Unknown arg: $1" >&2; exit 1 ;;
  esac
done

echo "════════════════════════════════════════════════════════════════"
echo "  Build agent-bundle-windows.zip"
echo "════════════════════════════════════════════════════════════════"

# ─── 1. OrgInventoryAgent MSI ──────────────────────────────────────────────
MSI_INV="OrgInventoryAgent.msi"
if [[ ! -f "$MSI_INV" ]]; then
    echo "[!] Không tìm thấy $MSI_INV" >&2
    echo "    Build trên Windows: cd agent/installer && powershell -File build-msi.ps1" >&2
    exit 1
fi
echo "[1/4] OrgInventoryAgent.msi      : $(du -h "$MSI_INV" | cut -f1)"

# ─── 2. Velociraptor MSI ───────────────────────────────────────────────────
MSI_VELOCI="velociraptor-windows-amd64.msi"
if [[ ! -f "$MSI_VELOCI" ]]; then
    echo "[!] Không tìm thấy $MSI_VELOCI" >&2
    echo "    Tải từ: https://github.com/Velocidex/velociraptor/releases" >&2
    echo "    Chọn bản 'velociraptor-v0.77.2-windows-amd64.msi' tương ứng version server." >&2
    exit 1
fi
echo "[2/4] velociraptor-windows-amd64.msi : $(du -h "$MSI_VELOCI" | cut -f1)"

# ─── 3. Velociraptor client config ─────────────────────────────────────────
CFG_VELOCI="$WORK/client.config.yaml"
if [[ -n "$VELOCI_CONFIG_SRC" && -f "$VELOCI_CONFIG_SRC" ]]; then
    cp "$VELOCI_CONFIG_SRC" "$CFG_VELOCI"
    echo "[3/4] client.config.yaml       : copy từ $VELOCI_CONFIG_SRC"
elif docker inspect "$VELOCI_CONTAINER" >/dev/null 2>&1; then
    echo "[3/4] Sinh client config từ container '$VELOCI_CONTAINER' …"
    docker exec "$VELOCI_CONTAINER" \
        velociraptor --config /etc/velociraptor/server.config.yaml config client \
        > "$CFG_VELOCI" 2>/dev/null
    # Verify URL đúng (port 8888 cho host)
    if ! grep -q ":8888/" "$CFG_VELOCI"; then
        echo "[!] client config không chứa :8888/ — URL có thể sai" >&2
        echo "    Đã sửa: deploy/velociraptor/etc/server.config.yaml chưa?" >&2
        grep "server_urls" "$CFG_VELOCI" || true
        exit 1
    fi
else
    echo "[!] Container '$VELOCI_CONTAINER' không chạy — không sinh được client config" >&2
    echo "    Khởi động Velociraptor trước: cd deploy/velociraptor && docker compose up -d" >&2
    exit 1
fi

# ─── 4. Tạo ZIP ────────────────────────────────────────────────────────────
echo "[4/4] Đóng gói bundle → $OUTPUT"
rm -f "$OUTPUT"

# Sử dụng zip nếu có, fallback sang Python
if command -v zip >/dev/null 2>&1; then
    (cd "$WORK" && zip -q "$OUTPUT" client.config.yaml)
    zip -q -j "$OUTPUT" \
        "$MSI_INV" \
        "$MSI_VELOCI" \
        "$SCRIPT_DIR/install-all.bat" \
        "$SCRIPT_DIR/install-all.ps1" \
        "$SCRIPT_DIR/README.txt"
else
    python3 - "$OUTPUT" "$WORK/client.config.yaml" \
        "$MSI_INV" "$MSI_VELOCI" \
        "$SCRIPT_DIR/install-all.bat" "$SCRIPT_DIR/install-all.ps1" \
        "$SCRIPT_DIR/README.txt" <<'PY'
import sys, zipfile, os
out = sys.argv[1]
files = sys.argv[2:]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        if os.path.isfile(f):
            z.write(f, arcname=os.path.basename(f))
PY
fi

# ─── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✓ Bundle: $OUTPUT"
echo "  ✓ Size  : $(du -h "$OUTPUT" | cut -f1)"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Bước tiếp theo:"
echo "  1. Copy file ZIP lên máy Windows cần giám sát."
echo "  2. Extract zip vào 1 thư mục bất kỳ (vd C:\\Temp\\agent-bundle\\)."
echo "  3. Right-click 'install-all.bat' → 'Run as administrator'."
echo "  4. Script sẽ hỏi:"
echo "       - Endpoint (URL Inventory Server, vd https://agent.gov.vn)"
echo "       - Token   (Enroll Token lấy từ Portal → tab Deploy)"
echo "  5. Cả 2 service (OrgInventoryAgent + Velociraptor) sẽ tự khởi động."
echo "  6. Verify trên Velociraptor GUI: https://10.10.0.241:8889"
