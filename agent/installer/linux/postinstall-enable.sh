#!/bin/bash
# =============================================================================
# OrgInventory Agent Linux — post-install enable + verify
# Chạy ngay sau `dpkg -i orginventory-agent_X.Y.Z_amd64.deb` hoặc `dnf install .rpm`
# để:
#   1. Ghi config enroll (nếu có token + endpoint)
#   2. Verify helper socket
#   3. Enable + start service chính
#   4. In trạng thái + hướng dẫn tiếp theo
# =============================================================================
set -euo pipefail

# ── Args / env ───────────────────────────────────────────────────────────────
TOKEN="${ORGINV_TOKEN:-${1:-}}"
HOST="${ORGINV_HOST:-${2:-}}"
DRY_RUN="${DRY_RUN:-0}"

# ── Privilege check ──────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "❌ Cần chạy với quyền root. Chạy lại: sudo $0 [TOKEN] [HOST]" >&2
    exit 1
fi

# ── Detect install paths ─────────────────────────────────────────────────────
BIN_DIR="/opt/orginventory"
ETC_DIR="/etc/orginventory"
DATA_DIR="/var/lib/orginventory"
LOG_DIR="/var/log/orginventory"
RUN_DIR="/run/orginventory"
SERVICE="orginventory-agent.service"
SOCKET="orginventory-helper.socket"

if [[ ! -x "$BIN_DIR/OrgInventoryAgent" ]]; then
    echo "❌ Không tìm thấy $BIN_DIR/OrgInventoryAgent. Cài package trước:" >&2
    echo "   sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ./orginventory-agent_*.deb" >&2
    echo "   hoặc: sudo dnf install -y ./orginventory-agent-*.rpm" >&2
    exit 2
fi

echo "============================================================"
echo "OrgInventory Agent — Post-install"
echo "============================================================"

# ── Step 1: Verify helper socket ──────────────────────────────────────────────
echo ""
echo "[1/5] Verify helper socket…"
if systemctl is-active --quiet "$SOCKET"; then
    echo "  ✓ Helper socket $SOCKET đang active."
else
    echo "  ⚠ Helper socket chưa active — khởi động…"
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "    (DRY_RUN — bỏ qua)"
    else
        systemctl enable --now "$SOCKET"
    fi
fi

if [[ -S "$RUN_DIR/helper.sock" ]]; then
    OWNER="$(stat -c '%U:%G' "$RUN_DIR/helper.sock")"
    MODE="$(stat -c '%a' "$RUN_DIR/helper.sock")"
    echo "  Socket: $RUN_DIR/helper.sock  owner=$OWNER  mode=$MODE"
else
    echo "  ❌ Socket file không tồn tại." >&2
    exit 3
fi

# ── Step 2: Helper self-test ─────────────────────────────────────────────────
echo ""
echo "[2/5] Self-test helper (đọc bios_version)…"
HELPER_RESP="$(echo '{"operation":"dmi","args":{"field":"bios_version"}}' \
    | "$BIN_DIR/orginventory-helper" 2>/dev/null || echo '{"ok":false,"error":"helper failed"}')"
echo "  Phản hồi helper: $HELPER_RESP"

# ── Step 3: Write config.json (nếu có token + host) ──────────────────────────
echo ""
echo "[3/5] Cấu hình enroll…"
if [[ -n "$TOKEN" && -n "$HOST" ]]; then
    mkdir -p "$ETC_DIR"
    cat > "$ETC_DIR/config.json" <<EOF
{
  "endpoints": ["${HOST}"],
  "enroll_token": "${TOKEN}",
  "data_dir": "${DATA_DIR}"
}
EOF
    chmod 0640 "$ETC_DIR/config.json"
    chown root:orginventory "$ETC_DIR/config.json"
    echo "  ✓ Đã ghi $ETC_DIR/config.json với token enroll."
else
    echo "  ⚠ Chưa có token/host. Bỏ qua ghi config. Bạn sẽ tự enroll sau."
    if [[ ! -f "$ETC_DIR/config.json" ]]; then
        mkdir -p "$ETC_DIR"
        cat > "$ETC_DIR/config.json" <<'EOF'
{
  "endpoints": ["https://agent.example.gov.vn"],
  "enroll_token": "",
  "data_dir": "/var/lib/orginventory"
}
EOF
        chmod 0640 "$ETC_DIR/config.json"
        chown root:orginventory "$ETC_DIR/config.json"
        echo "  Đã ghi config mẫu tại $ETC_DIR/config.json — sửa trước khi enroll."
    fi
fi

# ── Step 4: Enable + start service chính ─────────────────────────────────────
echo ""
echo "[4/5] Enable + start $SERVICE…"
if [[ "$DRY_RUN" == "1" ]]; then
    echo "  (DRY_RUN — bỏ qua systemctl)"
else
    systemctl daemon-reload
    systemctl enable "$SERVICE"
    systemctl restart "$SOCKET" || true
    if systemctl start "$SERVICE"; then
        echo "  ✓ Service đã start."
    else
        echo "  ⚠ Service start fail — kiểm tra: journalctl -u $SERVICE -n 50"
    fi
fi

# ── Step 5: In trạng thái + hướng dẫn tiếp theo ────────────────────────────
echo ""
echo "[5/5] Trạng thái:"
echo "------------------------------------------------------------"
systemctl --no-pager --full status "$SERVICE" 2>&1 | sed -n '1,8p' || true
systemctl --no-pager --full status "$SOCKET" 2>&1 | sed -n '1,8p' || true
echo "------------------------------------------------------------"

echo ""
echo "============================================================"
echo "✅ Hoàn tất."
echo "============================================================"
echo ""
echo "Bước tiếp theo:"
echo "  • Xem log:      tail -f $LOG_DIR/agent.log"
echo "  • Xem journal:  journalctl -u $SERVICE -f"
echo "  • Trạng thái:   systemctl status $SERVICE"
echo "  • Restart:      sudo systemctl restart $SERVICE"
echo ""
if [[ -n "$TOKEN" && -n "$HOST" ]]; then
    echo "Agent sẽ tự enroll với server $HOST trong vòng 1 chu kỳ heartbeat."
    echo "Sau ~30s, máy sẽ hiển thị 'online' trên Portal."
else
    echo "Để enroll, sửa $ETC_DIR/config.json (điền token + endpoint) rồi:"
    echo "  sudo systemctl restart $SERVICE"
fi
echo ""