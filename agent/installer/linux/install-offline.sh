#!/bin/bash
# Offline install (USB bundle) — tương tự flow Windows.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Cần root." >&2; exit 1; fi

USB_MOUNT="${1:-/media/usb}"
PKG="$(ls "$USB_MOUNT"/orginventory-agent-*.deb 2>/dev/null || ls "$USB_MOUNT"/orginventory-agent-*.rpm 2>/dev/null || true)"
if [[ -z "$PKG" ]]; then
    echo "Không tìm thấy package trên $USB_MOUNT" >&2; exit 2
fi

if [[ -f "$USB_MOUNT/orginventory-agent.sha256" ]]; then
    EXPECTED="$(awk '{print $1}' "$USB_MOUNT/orginventory-agent.sha256")"
    ACTUAL="$(sha256sum "$PKG" | awk '{print $1}')"
    [[ "$EXPECTED" == "$ACTUAL" ]] || { echo "SHA256 mismatch"; exit 3; }
fi

case "$PKG" in
    *.deb) DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG" ;;
    *.rpm) dnf install -y "$PKG" ;;
esac

echo "✔ Package đã cài. Chạy 'sudo systemctl enable --now orginventory-agent' sau khi enroll xong."