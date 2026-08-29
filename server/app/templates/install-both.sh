#!/usr/bin/env bash
# ============================================================================
# install-both.sh — Cai dat CUNG LUC 2 agent tren Linux bang 1 lenh:
#   1) OrgInventory Agent  - kiem ke tai san CNTT & ATTT (daemon + systemd)
#   2) Velociraptor Client - DFIR (deb/rpm -> systemd service "velociraptor_client")
#
# Cach dung (1 lenh, tu server /download/install-both.sh):
#   curl -fsSL https://portal.gov.vn/download/install-both.sh | sudo bash -s -- \
#       --token t_xxx --endpoint https://agent.gov.vn --portal-url https://portal.gov.vn
#
# Hoac chay truc tiep:
#   sudo bash install-both.sh --token t_xxx --endpoint https://agent.gov.vn \
#       --velociraptor-package-url https://portal.gov.vn/download/velociraptor-linux-amd64.deb
#
# Yeu cau:
#   - Chay voi quyen root (sudo).
#   - OrgInventory: truyen --agent-binary-url (binary linux-x64 self-contained),
#     hoac chay trong repo co source (agent/src/OrgInventoryAgent) + dotnet SDK,
#     hoac da co publish/linux-x64/OrgInventoryAgent.
#   - Velociraptor: goi .deb (Debian/Ubuntu) hoac .rpm (RHEL/Fedora) DA NHUNG
#     client.config.yaml (tao bang artifact Server.Utils.CreateLinuxPackages hoac
#     lenh `velociraptor debian client --config client.config.yaml` tren VR server).
#
# Ghi chu bao mat: token enroll chi 1 lan (agent tu xoa sau khi enroll thanh cong).
# Neu enroll that bai luc cai (may offline), token duoc giu trong unit file de
# service tu retry — sau khi enroll OK nen xoa dong --enroll-token trong
# /etc/systemd/system/orginventory-agent.service.
# ============================================================================
set -euo pipefail

usage() {
    cat <<'EOF'
Cach dung:
  sudo bash install-both.sh [options]

Options:
  --token <token>              Enroll token OrgInventory (env ORGINVENTORY_TOKEN)
  --endpoint <url>             Agent server URL mTLS (env ORGINVENTORY_ENDPOINT)
  --portal-url <url>           Base URL portal de tai package (env ORGINVENTORY_PORTAL_URL)
  --agent-binary-url <url|path> URL/path binary OrgInventoryAgent linux-x64
                               (env ORGINVENTORY_BINARY_URL; mac dinh: build tu source neu co)
  --velociraptor-package-url <url|path>  URL/path goi .deb hoac .rpm cua Velociraptor
                               (env VELOCIRAPTOR_PACKAGE_URL; mac dinh:
                                $PORTAL_URL/download/velociraptor-linux-amd64.deb)
  --data-dir <path>            Thu muc du lieu agent (mac dinh /var/lib/orginventory)
  --skip-orginventory          Chi cai Velociraptor
  --skip-velociraptor          Chi cai OrgInventory
  -h, --help                   Huong dan nay

Vi du:
  sudo bash install-both.sh --token t_xxx --endpoint https://agent.gov.vn \
      --velociraptor-package-url https://portal.gov.vn/download/velociraptor-linux-amd64.deb
EOF
}

# ── Tham so (env hoac CLI) ───────────────────────────────────────────────
TOKEN="${ORGINVENTORY_TOKEN:-}"
ENDPOINT="${ORGINVENTORY_ENDPOINT:-}"
PORTAL_URL="${ORGINVENTORY_PORTAL_URL:-}"
AGENT_BINARY_URL="${ORGINVENTORY_BINARY_URL:-}"
VR_PKG_URL="${VELOCIRAPTOR_PACKAGE_URL:-}"
DATA_DIR="${ORGINVENTORY_DATA_DIR:-/var/lib/orginventory}"
INSTALL_DIR="/opt/orginventory"
SKIP_OI=0
SKIP_VR=0

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
        -h|--help) usage; exit 0 ;;
        *) echo "[LOI] Tham so khong hop le: $1" >&2; usage; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==========================================================================="
echo "  CAI DAT DONG THOI 2 AGENT (Linux)"
echo "    1. OrgInventory Agent (kiem ke)  -> systemd: orginventory-agent"
echo "    2. Velociraptor Client (DFIR)    -> systemd: velociraptor_client"
echo "==========================================================================="
[[ -n "$ENDPOINT" ]] && echo "  Endpoint: $ENDPOINT"
[[ -n "$PORTAL_URL" ]] && echo "  Portal  : $PORTAL_URL"
echo ""

# ── Kiem tra root ────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "[LOI] Can chay voi quyen root: sudo bash $0 ..." >&2
    exit 1
fi

# ── 1. OrgInventory Agent ────────────────────────────────────────────────
install_orginventory() {
    echo "[1/3] Cai dat OrgInventory Agent ..."

    if [[ -z "$TOKEN" ]] || [[ -z "$ENDPOINT" ]]; then
        echo "[LOI] Can cung cap --token va --endpoint (hoac env ORGINVENTORY_TOKEN / ORGINVENTORY_ENDPOINT)." >&2
        exit 1
    fi

    # Lay binary (mac dinh: tai tu portal /download/agent-linux-x64 neu co --portal-url)
    local bin_src=""
    if [[ -z "$AGENT_BINARY_URL" && -n "$PORTAL_URL" ]]; then
        AGENT_BINARY_URL="$PORTAL_URL/download/agent-linux-x64"
    fi
    if [[ -n "$AGENT_BINARY_URL" ]]; then
        if [[ "$AGENT_BINARY_URL" == http* ]]; then
            echo "      Tai binary tu $AGENT_BINARY_URL ..."
            curl -fsSL "$AGENT_BINARY_URL" -o /tmp/OrgInventoryAgent.bin
            bin_src=/tmp/OrgInventoryAgent.bin
        else
            bin_src="$AGENT_BINARY_URL"
        fi
    elif [[ -x "$SCRIPT_DIR/publish/linux-x64/OrgInventoryAgent" ]]; then
        bin_src="$SCRIPT_DIR/publish/linux-x64/OrgInventoryAgent"
    elif [[ -d "$SCRIPT_DIR/src/OrgInventoryAgent" ]] && command -v dotnet >/dev/null 2>&1; then
        echo "      Build binary linux-x64 (dotnet publish) ..."
        dotnet publish "$SCRIPT_DIR/src/OrgInventoryAgent" -c Release -r linux-x64 \
            --self-contained -p:PublishSingleFile=true -p:DebugType=none \
            -o /tmp/oi-build >/dev/null
        bin_src=/tmp/oi-build/OrgInventoryAgent
    else
        echo "[LOI] Khong tim thay binary OrgInventoryAgent. Cung cap --agent-binary-url, hoac:" >&2
        echo "      dotnet publish src/OrgInventoryAgent -c Release -r linux-x64 --self-contained -p:PublishSingleFile=true -p:DebugType=none -o publish/linux-x64" >&2
        exit 1
    fi
    [[ -x "$bin_src" ]] || chmod +x "$bin_src"

    mkdir -p "$INSTALL_DIR" "$DATA_DIR"
    install -m 0755 "$bin_src" "$INSTALL_DIR/OrgInventoryAgent"

    # User chay dich vu (idempotent)
    if ! id -u orginventory >/dev/null 2>&1; then
        useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin orginventory
    fi
    chown -R orginventory:orginventory "$DATA_DIR"

    # Smoke test enroll (--once: enroll -> heartbeat -> inventory, timeout 120s)
    local enrolled=0
    echo "      Thu enroll lan dau (--once, toi da 120s) ..."
    if sudo -u orginventory timeout 120 "$INSTALL_DIR/OrgInventoryAgent" \
        --data-dir "$DATA_DIR" --endpoint "$ENDPOINT" --enroll-token "$TOKEN" --once \
        >/tmp/oi-once.log 2>&1; then
        enrolled=1
        echo "      [OK] Enroll thanh cong ngay khi cai dat!"
    else
        echo "      [WARN] Enroll chua thanh cong (may offline?). Service se tu retry."
        tail -n 5 /tmp/oi-once.log 2>/dev/null | sed 's/^/      /' || true
    fi

    # Unit file: giu --enroll-token chi khi chua enroll duoc (de service retry)
    local token_args=""
    if [[ $enrolled -ne 1 ]]; then
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
    systemctl enable --now orginventory-agent
    echo "      [OK] Service orginventory-agent dang chay."
}

# ── 2. Velociraptor Client ───────────────────────────────────────────────
install_velociraptor() {
    echo "[2/3] Cai dat Velociraptor Client ..."

    if [[ -z "$VR_PKG_URL" ]]; then
        if [[ -n "$PORTAL_URL" ]]; then
            VR_PKG_URL="$PORTAL_URL/download/velociraptor-linux-amd64.deb"
        else
            echo "[LOI] Can cung cap --velociraptor-package-url (hoac --portal-url, env VELOCIRAPTOR_PACKAGE_URL)." >&2
            exit 1
        fi
    fi

    local pkg=""
    if [[ "$VR_PKG_URL" == http* ]]; then
        echo "      Tai package tu $VR_PKG_URL ..."
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
            echo "[LOI] Khong nhan dien dinh dang goi ($pkg). Can .deb hoac .rpm." >&2
            exit 1
            ;;
    esac

    systemctl enable --now velociraptor_client 2>/dev/null || true
    echo "      [OK] Service velociraptor_client da enable."
}

# ── 3. Verify ────────────────────────────────────────────────────────────
verify() {
    echo "[3/3] Kiem tra dich vu ..."
    if [[ $SKIP_OI -ne 1 ]]; then
        if systemctl is-active --quiet orginventory-agent; then
            echo "      [OK] orginventory-agent: active (running)"
        else
            echo "      [LOI] orginventory-agent: $(systemctl is-active orginventory-agent)"
        fi
    fi
    if [[ $SKIP_VR -ne 1 ]]; then
        if systemctl is-active --quiet velociraptor_client; then
            echo "      [OK] velociraptor_client: active (running)"
        else
            echo "      [LOI] velociraptor_client: $(systemctl is-active velociraptor_client)"
        fi
    fi
}

[[ $SKIP_OI -eq 1 ]] || install_orginventory
[[ $SKIP_VR -eq 1 ]] || install_velociraptor
verify

echo ""
echo "=========================================================="
echo "  CA 2 AGENT DA DUOC CAI DAT!"
echo "=========================================================="
echo "  - OrgInventory: systemctl status orginventory-agent   (data: $DATA_DIR)"
echo "  - Velociraptor: systemctl status velociraptor_client"
echo "  - Verify enroll: GUI https://<velociraptor-host>:8889 -> Clients (~30s)"
echo "  - Mapping sang portal /dfir sau toi da ~5 phut"
echo ""
