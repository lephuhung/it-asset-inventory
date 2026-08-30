#!/bin/bash
# Usage: curl -fsSL https://<host>/i/<token> | sudo bash
set -euo pipefail
TOKEN="${ORGINV_TOKEN:-}"
HOST="${ORGINV_HOST:-}"
if [[ -z "$TOKEN" || -z "$HOST" ]]; then
    echo "Thiếu ORGINV_TOKEN hoặc ORGINV_HOST. Lệnh dự kiến:" >&2
    echo "  curl -fsSL https://<host>/i/<token> | sudo bash" >&2
    exit 1
fi
if [[ $EUID -ne 0 ]]; then
    echo "Cần quyền root. Chạy lại với sudo." >&2
    exit 2
fi

. /etc/os-release
PKG_EXT="deb"
case "${ID:-}" in
    rhel|rocky|almalinux|centos|fedora) PKG_EXT="rpm" ;;
esac
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) RID="linux-x64" ;;
    aarch64) RID="linux-arm64" ;;
    *) echo "Không hỗ trợ kiến trúc $ARCH" >&2; exit 3 ;;
esac

URL="https://${HOST}/download/linux/${TOKEN}/orginventory-agent-1.1.0-${RID}.${PKG_EXT}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Đang tải $URL ..."
curl -fsSL -o "$TMP/pkg.${PKG_EXT}" "$URL"

curl -fsSL -o "$TMP/pkg.sha256" "https://${HOST}/download/linux/${TOKEN}/pkg.sha256"
EXPECTED="$(awk '{print $1}' "$TMP/pkg.sha256")"
ACTUAL="$(sha256sum "$TMP/pkg.${PKG_EXT}" | awk '{print $1}')"
if [[ "$EXPECTED" != "$ACTUAL" ]]; then
    echo "SHA256 mismatch" >&2
    exit 4
fi

if [[ "$PKG_EXT" == "deb" ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$TMP/pkg.deb"
else
    dnf install -y "$TMP/pkg.rpm"
fi

mkdir -p /etc/orginventory
cat > /etc/orginventory/config.json <<EOF
{
  "endpoints": ["https://${HOST}"],
  "enroll_token": "${TOKEN}",
  "data_dir": "/var/lib/orginventory"
}
EOF
chmod 0640 /etc/orginventory/config.json
chown root:orginventory /etc/orginventory/config.json

systemctl enable --now orginventory-agent.service
echo "✔ Cài đặt thành công. Agent đang enroll..."