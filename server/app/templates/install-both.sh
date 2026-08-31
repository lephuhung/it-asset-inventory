#!/usr/bin/env bash
# ============================================================================
# install-both.sh — Cai dat CUNG LUC 2 agent tren Linux bang 1 lenh:
#   1) OrgInventory Agent  - kiem ke tai san CNTT & ATTT (daemon + systemd)
#   2) Velociraptor Client - DFIR (deb/rpm -> systemd "velociraptor_client")
#
# Cach dung (1 lenh):
#   curl -fsSL https://portal.gov.vn/download/install-both.sh | sudo bash -s -- \
#       --token t_xxx --endpoint https://agent.gov.vn --portal-url https://portal.gov.vn
#
# Hoac chay truc tiep:
#   sudo bash install-both.sh --token t_xxx --endpoint https://agent.gov.vn
#
# PHILOSOPHY: KHONG GO package neu khong can thiet.
#   - Neu OrgInventory chua cai → cai binary moi
#   - Neu OrgInventory da cai → chi UPDATE config (token, endpoints) + restart service
#   - Tuong tu cho Velociraptor → chi UPDATE client.config.yaml + restart service
#   - ForceReinstall: go + cai lai (chi dung khi package bi loi)
# ============================================================================
set -euo pipefail

# ── Color helpers ───────────────────────────────────────────────────────
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
CYAN=$'\033[0;36m'
GRAY=$'\033[0;90m'
NC=$'\033[0m'

log_step()  { echo -e "${CYAN}$1${NC}"; }
log_ok()    { echo -e "      ${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "      ${YELLOW}[WARN]${NC} $1"; }
log_fail()  { echo -e "      ${RED}[FAIL]${NC} $1"; }
log_info()  { echo -e "      ${GRAY}[INFO]${NC} $1"; }

usage() {
    cat <<'EOF'
Cach dung:
  sudo bash install-both.sh [options]

Options:
  --token <token>              Enroll token OrgInventory (env ORGINVENTORY_TOKEN)
  --endpoint <url>             Agent server URL mTLS (env ORGINVENTORY_ENDPOINT)
  --portal-url <url>           Base URL portal de tai package (env ORGINVENTORY_PORTAL_URL)
  --agent-binary-url <url|path> URL/path binary OrgInventoryAgent linux-x64
                               (env ORGINVENTORY_BINARY_URL; mac dinh: $PORTAL_URL/download/agent-linux-x64)
  --velociraptor-config-url <url|path>    URL Velociraptor client.config.yaml (full install)
  --velociraptor-config-only-zip <url>  URL ZIP config-only ~2KB (Smart Update mode)
  --velociraptor-package-url <url|path>  URL/path goi .deb hoac .rpm cua Velociraptor
                               (env VELOCIRAPTOR_PACKAGE_URL; mac dinh:
                                $PORTAL_URL/download/velociraptor-linux-amd64.deb)
  --data-dir <path>            Thu muc du lieu OrgInventory (mac dinh /var/lib/orginventory)
  --skip-orginventory          Chi cai Velociraptor
  --skip-velociraptor          Chi cai OrgInventory
  --force-reinstall            GO package cu + cai lai (chi khi loi)
  -h, --help                   Huong dan nay

Vi du:
  sudo bash install-both.sh --token t_xxx --endpoint https://agent.gov.vn \
      --portal-url https://portal.gov.vn
EOF
}

# ── Tham so ──────────────────────────────────────────────────────────────
TOKEN="${ORGINVENTORY_TOKEN:-}"
ENDPOINT="${ORGINVENTORY_ENDPOINT:-}"
PORTAL_URL="${ORGINVENTORY_PORTAL_URL:-}"
AGENT_BINARY_URL="${ORGINVENTORY_BINARY_URL:-}"
VR_PKG_URL="${VELOCIRAPTOR_PACKAGE_URL:-}"
VR_CFG_URL="${VELOCIRAPTOR_CONFIG_URL:-}"
VR_CFG_ONLY_ZIP_URL="${VELOCIRAPTOR_CONFIG_ONLY_ZIP_URL:-}"
DATA_DIR="${ORGINVENTORY_DATA_DIR:-/var/lib/orginventory}"
INSTALL_DIR="/opt/orginventory"
SKIP_OI=0
SKIP_VR=0
FORCE_REINSTALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token) TOKEN="$2"; shift 2 ;;
        --endpoint) ENDPOINT="$2"; shift 2 ;;
        --portal-url) PORTAL_URL="$2"; shift 2 ;;
        --agent-binary-url) AGENT_BINARY_URL="$2"; shift 2 ;;
        --velociraptor-package-url) VR_PKG_URL="$2"; shift 2 ;;
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        --skip-orginventory) SKIP_OI=1; shift ;;
        --skip-velociraptor) SKIP_VR=1; shift ;;
        --force-reinstall) FORCE_REINSTALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) log_fail "Tham so khong hop le: $1"; usage; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=========================================================================="
echo -e "  ${CYAN}CAI DAT DONG THOI 2 AGENT (Linux - Smart Update)${NC}"
echo "    1. OrgInventory Agent (kiem ke)  -> systemd: orginventory-agent"
echo "    2. Velociraptor Client (DFIR)    -> systemd: velociraptor_client"
echo "=========================================================================="
[[ -n "$ENDPOINT" ]] && echo "  Endpoint: $ENDPOINT"
[[ -n "$PORTAL_URL" ]] && echo "  Portal  : $PORTAL_URL"
[[ -n "$TOKEN" ]] && echo "  Token  : ${TOKEN:0:8}..."
echo ""

# ── Kiem tra root ────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    log_fail "Can chay voi quyen root: sudo bash $0 ..."
    exit 1
fi

# ── 1. Detect trang thai hien tai ─────────────────────────────────────────
log_step "[1/5] Kiem tra trang thai agent hien tai..."

# OrgInventory: check binary + service
oi_installed=0
oi_service_status=""
if [[ $SKIP_OI -eq 0 ]]; then
    if [[ -x "$INSTALL_DIR/OrgInventoryAgent" ]]; then
        oi_installed=1
        oi_version="unknown"
        # Lay version tu binary
        if "$INSTALL_DIR/OrgInventoryAgent" --version >/dev/null 2>&1; then
            oi_version=$("$INSTALL_DIR/OrgInventoryAgent" --version 2>&1 | head -1)
        fi
        log_info "OrgInventory Agent da cai ($oi_version)"
        if systemctl is-active --quiet orginventory-agent; then
            oi_service_status="active"
            log_info "  Service: active"
        else
            oi_service_status=$(systemctl is-active orginventory-agent || echo "unknown")
            log_warn "  Service: $oi_service_status"
        fi
    else
        log_info "OrgInventory Agent chua duoc cai"
    fi
fi

# Velociraptor: check service
vr_installed=0
vr_service_status=""
if [[ $SKIP_VR -eq 0 ]]; then
    if systemctl list-unit-files velociraptor_client.service >/dev/null 2>&1; then
        vr_installed=1
        # Lay version
        vr_version=$(dpkg -l 2>/dev/null | grep velociraptor | awk '{print $3}' | head -1)
        [[ -z "$vr_version" ]] && vr_version=$(rpm -q velociraptor-client 2>/dev/null | head -1)
        [[ -z "$vr_version" ]] && vr_version="unknown"
        log_info "Velociraptor da cai ($vr_version)"
        if systemctl is-active --quiet velociraptor_client; then
            vr_service_status="active"
            log_info "  Service: active"
        else
            vr_service_status=$(systemctl is-active velociraptor_client 2>/dev/null || echo "unknown")
            log_warn "  Service: $vr_service_status"
        fi
    else
        log_info "Velociraptor chua duoc cai"
    fi
fi

# ── 2. OrgInventory Agent ────────────────────────────────────────────────
if [[ $SKIP_OI -eq 0 ]]; then
    log_step "[2/5] Cai dat / cap nhat OrgInventory Agent..."

    if [[ -z "$TOKEN" ]] || [[ -z "$ENDPOINT" ]]; then
        log_fail "Can cung cap --token va --endpoint (hoac env ORGINVENTORY_TOKEN / ORGINVENTORY_ENDPOINT)."
        exit 1
    fi

    # === Case 1: Chua cai HOẶC ForceReinstall → cai binary moi ===
    if [[ $oi_installed -eq 0 ]] || [[ $FORCE_REINSTALL -eq 1 ]]; then
        if [[ $FORCE_REINSTALL -eq 1 ]] && [[ $oi_installed -eq 1 ]]; then
            log_info "ForceReinstall = true → stop service va thay binary"
            systemctl stop orginventory-agent 2>/dev/null || true
        fi

        # Lay binary
        bin_src=""
        if [[ -z "$AGENT_BINARY_URL" && -n "$PORTAL_URL" ]]; then
            AGENT_BINARY_URL="$PORTAL_URL/download/agent-linux-x64"
        fi
        if [[ -n "$AGENT_BINARY_URL" ]]; then
            if [[ "$AGENT_BINARY_URL" == http* ]]; then
                log_info "Tai binary tu $AGENT_BINARY_URL ..."
                curl -fsSL "$AGENT_BINARY_URL" -o /tmp/OrgInventoryAgent.bin
                bin_src=/tmp/OrgInventoryAgent.bin
            else
                bin_src="$AGENT_BINARY_URL"
            fi
        elif [[ -x "$SCRIPT_DIR/publish/linux-x64/OrgInventoryAgent" ]]; then
            bin_src="$SCRIPT_DIR/publish/linux-x64/OrgInventoryAgent"
        elif [[ -d "$SCRIPT_DIR/src/OrgInventoryAgent" ]] && command -v dotnet >/dev/null 2>&1; then
            log_info "Build binary linux-x64 (dotnet publish) ..."
            dotnet publish "$SCRIPT_DIR/src/OrgInventoryAgent" -c Release -r linux-x64 \
                --self-contained -p:PublishSingleFile=true -p:DebugType=none \
                -o /tmp/oi-build >/dev/null
            bin_src=/tmp/oi-build/OrgInventoryAgent
        else
            log_fail "Khong tim thay binary OrgInventoryAgent. Cung cap --agent-binary-url."
            exit 1
        fi
        [[ -x "$bin_src" ]] || chmod +x "$bin_src"

        mkdir -p "$INSTALL_DIR" "$DATA_DIR"
        install -m 0755 "$bin_src" "$INSTALL_DIR/OrgInventoryAgent"
        log_ok "Binary da cai vao $INSTALL_DIR/OrgInventoryAgent"
    else
        log_info "OrgInventory Agent da cai → chi UPDATE config + restart service (KHONG thay binary)"
    fi

    # User chay dich vu (idempotent)
    if ! id -u orginventory >/dev/null 2>&1; then
        useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin orginventory
    fi
    chown -R orginventory:orginventory "$DATA_DIR"

    # === Case 2: Da cai → cap nhat token/endpoint + restart ===
    # Doc token hien tai tu config (neu co)
    oi_current_token=""
    oi_current_endpoint=""
    cfg_path="$DATA_DIR/config.json"
    if [[ -f "$cfg_path" ]]; then
        oi_current_token=$(grep -o '"token"[[:space:]]*:[[:space:]]*"[^"]*"' "$cfg_path" 2>/dev/null | sed 's/.*"\([^"]*\)"$/\1/' | head -1)
        oi_current_endpoint=$(grep -o '"endpoints"[[:space:]]*:[[:space:]]*\[[^]]*\]' "$cfg_path" 2>/dev/null | head -1)
    fi

    # Luon update unit file de co token moi (se bi xoa neu enroll thanh cong)
    local token_args=""
    if [[ -n "$TOKEN" ]]; then
        token_args="--enroll-token $TOKEN"
    fi

    cat > /etc/systemd/system/orginventory-agent.service <<EOF
[Unit]
Description=OrgInventory Agent - IT Asset Inventory (Cong an tinh Ha Tinh)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=orginventory
Group=orginventory
WorkingDirectory=$DATA_DIR
ExecStart=$INSTALL_DIR/OrgInventoryAgent --data-dir $DATA_DIR --endpoint $ENDPOINT $token_args
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
    chmod 644 /etc/systemd/system/orginventory-agent.service

    systemctl daemon-reload
    systemctl enable orginventory-agent

    # Neu service dang chay → restart de doc config moi
    if [[ $oi_installed -eq 1 ]] && [[ "$oi_service_status" == "active" ]]; then
        log_info "Restart service OrgInventoryAgent de doc config moi (token: ${TOKEN:0:8}...)"
        systemctl restart orginventory-agent
    else
        # Moi cai → start luon
        systemctl start orginventory-agent
    fi

    # Cho service start
    sleep 3
    if systemctl is-active --quiet orginventory-agent; then
        log_ok "Service orginventory-agent: active (running)"
    else
        log_warn "Service orginventory-agent khong the start. Kiem tra: journalctl -u orginventory-agent -n 50"
    fi

    # ── Smoke test enroll (lan dau) ──
    if [[ $oi_installed -eq 0 ]] || [[ $FORCE_REINSTALL -eq 1 ]]; then
        local enrolled=0
        log_info "Thu enroll lan dau (--once, toi da 120s) ..."
        if sudo -u orginventory timeout 120 "$INSTALL_DIR/OrgInventoryAgent" \
            --data-dir "$DATA_DIR" --endpoint "$ENDPOINT" --enroll-token "$TOKEN" --once \
            >/tmp/oi-once.log 2>&1; then
            enrolled=1
            log_ok "Enroll thanh cong ngay khi cai dat!"
            # Token da dung → xoa khoi unit file de service tu lay tu config.json
            sed -i 's/ --enroll-token [^ ]*//' /etc/systemd/system/orginventory-agent.service
            systemctl daemon-reload
            systemctl restart orginventory-agent
        else
            log_warn "Enroll chua thanh cong (may offline?). Service se tu retry khi co mang."
        fi
    fi
fi

# ── 3. Velociraptor Client ───────────────────────────────────────────────
if [[ $SKIP_VR -eq 0 ]]; then
    log_step "[3/5] Cai dat / cap nhat Velociraptor Client..."

    if [[ -z "$VR_PKG_URL" ]]; then
        if [[ -n "$PORTAL_URL" ]]; then
            VR_PKG_URL="$PORTAL_URL/download/velociraptor-linux-amd64.deb"
        else
            log_fail "Can cung cap --velociraptor-package-url (hoac --portal-url, env VELOCIRAPTOR_PACKAGE_URL)."
            exit 1
        fi
    fi

    # === Case 1: Chua cai HOẶC ForceReinstall → cai package moi ===
    if [[ $vr_installed -eq 0 ]] || [[ $FORCE_REINSTALL -eq 1 ]]; then
        if [[ $FORCE_REINSTALL -eq 1 ]] && [[ $vr_installed -eq 1 ]]; then
            log_info "ForceReinstall = true → stop service va remove package cu"
            systemctl stop velociraptor_client 2>/dev/null || true
            if command -v dpkg >/dev/null 2>&1 && dpkg -l velociraptor-client >/dev/null 2>&1; then
                dpkg -r velociraptor-client || true
            elif rpm -q velociraptor-client >/dev/null 2>&1; then
                rpm -e velociraptor-client || true
            fi
        fi

        local pkg=""
        if [[ "$VR_PKG_URL" == http* ]]; then
            log_info "Tai package tu $VR_PKG_URL ..."
            curl -fsSL "$VR_PKG_URL" -o /tmp/velociraptor-client.pkg
            pkg=/tmp/velociraptor-client.pkg
        else
            pkg="$VR_PKG_URL"
        fi

        case "$pkg" in
            *.deb)
                dpkg -i "$pkg"
                ;;
            *.rpm)
                rpm -i "$pkg"
                ;;
            *)
                log_fail "Khong nhan dien dinh dang goi ($pkg). Can .deb hoac .rpm."
                exit 1
                ;;
        esac
        log_ok "Package Velociraptor da cai"
    else
        log_info "Velociraptor da cai → chi restart service (KHONG go package)"
    fi

    systemctl enable velociraptor_client 2>/dev/null || true

    # Cap nhat client.config.yaml (uu tien ZIP nho de nhanh)
    if [[ $vr_use_config_only -eq 1 ]] && [[ -n "$VR_CFG_ONLY_ZIP_URL" ]]; then
        log_info "Smart Update: tai ZIP config-only (~2KB)..."
        if curl -fsSL "$VR_CFG_ONLY_ZIP_URL" -o /tmp/velociraptor-config.zip 2>/dev/null; then
            # Extract client.config.yaml tu ZIP
            if command -v unzip >/dev/null 2>&1; then
                unzip -o -j /tmp/velociraptor-config.zip "*/client.config.yaml" -d /tmp/velociraptor-cfg/ >/dev/null 2>&1 &&                 cp -f /tmp/velociraptor-cfg/client.config.yaml /etc/velociraptor/client.config.yaml &&                 log_ok "Config (tu ZIP 2KB) da cap nhat" ||                 log_warn "Extract ZIP that bai, fallback download client.config.yaml"
            else
                log_warn "unzip khong co, fallback download client.config.yaml"
            fi
            rm -rf /tmp/velociraptor-cfg /tmp/velociraptor-config.zip
        fi
    fi
    # Fallback: download client.config.yaml rieng neu ZIP fail
    if [[ -n "$VR_CFG_URL" ]] && ! diff -q /etc/velociraptor/client.config.yaml <(curl -fsSL "$VR_CFG_URL" 2>/dev/null) >/dev/null 2>&1; then
        curl -fsSL "$VR_CFG_URL" -o /etc/velociraptor/client.config.yaml 2>/dev/null &&         log_ok "Config da cap nhat (URL rieng)" || true
    fi

    # Luôn restart service để đảm bảo client.config.yaml mới nhất được load
    if [[ "$vr_service_status" == "active" ]] || [[ $vr_installed -eq 1 ]]; then
        log_info "Restart service velociraptor_client de dam bao client.config.yaml moi nhat"
        systemctl restart velociraptor_client 2>/dev/null || true
    else
        systemctl start velociraptor_client 2>/dev/null || true
    fi

    sleep 3
    if systemctl is-active --quiet velociraptor_client; then
        log_ok "Service velociraptor_client: active (running)"
    else
        log_warn "Service velociraptor_client khong the start. Kiem tra: journalctl -u velociraptor_client -n 50"
    fi
fi

# ── 4. Verify cuoi cung ──────────────────────────────────────────────────
log_step "[4/5] Verify cuoi cung..."
sleep 5

all_ok=1
if [[ $SKIP_OI -eq 0 ]]; then
    if systemctl is-active --quiet orginventory-agent; then
        log_ok "orginventory-agent: active (running)"
    else
        log_fail "orginventory-agent: $(systemctl is-active orginventory-agent 2>/dev/null || echo unknown)"
        all_ok=0
    fi
fi
if [[ $SKIP_VR -eq 0 ]]; then
    if systemctl is-active --quiet velociraptor_client; then
        log_ok "velociraptor_client: active (running)"
    else
        log_fail "velociraptor_client: $(systemctl is-active velociraptor_client 2>/dev/null || echo unknown)"
        all_ok=0
    fi
fi

# ── 5. Hoan tat ────────────────────────────────────────────────────────
log_step "[5/5] Hoan tat"
echo ""
if [[ $all_ok -eq 1 ]]; then
    echo -e "${GREEN}=========================================================="
    echo "  TAT CA AGENT DANG CHAY THANH CONG!"
    echo -e "==========================================================${NC}"
    echo ""
    [[ $SKIP_OI -eq 0 ]] && echo "  - OrgInventory: systemctl status orginventory-agent   (data: $DATA_DIR)"
    [[ $SKIP_VR -eq 0 ]] && echo "  - Velociraptor:  systemctl status velociraptor_client"
    [[ $SKIP_OI -eq 0 ]] && echo "  - Log OI:        journalctl -u orginventory-agent -f"
    [[ $SKIP_VR -eq 0 ]] && echo "  - Log VR:        journalctl -u velociraptor_client -f"
    echo ""

    # ── Cleanup temp files ──
    rm -rf /tmp/velociraptor-cfg /tmp/velociraptor-config.zip /tmp/velociraptor-client.pkg /tmp/OrgInventoryAgent.bin /tmp/oi-once.log /tmp/oi-build 2>/dev/null || true
    log_info "Da xoa temp files"

    exit 0
else
    echo -e "${YELLOW}=========================================================="
    echo "  CAI DAT HOAN TAT NHUNG CO LOI O 1 SO SERVICE"
    echo -e "==========================================================${NC}"
    exit 1
fi
