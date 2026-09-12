#!/bin/bash
# Build DEB cho OrgInventory Agent Linux.
#   ./build-deb.sh [RID] [OUT]
#     RID: linux-x64 (mặc định) | linux-arm64
#
# Architecture của package PHẢI theo RID (linux-x64→amd64, linux-arm64→arm64) —
# KHÔNG lấy arch của build host. Cross-build arm64 trên host amd64 hợp lệ vì
# .deb chỉ là archive; control file được sinh với Architecture đúng theo RID.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RID="${1:-linux-x64}"
OUT="${2:-dist}"

case "$RID" in
    linux-x64)   DEB_ARCH="amd64" ;;
    linux-arm64) DEB_ARCH="arm64" ;;
    *) echo "RID không hỗ trợ: $RID (chỉ linux-x64 | linux-arm64)" >&2; exit 1 ;;
esac

VERSION="$(sed -n 's/^Version: *//p' "$HERE/debian/control" | head -n1)"
[[ -n "$VERSION" ]] || { echo "Không đọc được Version từ debian/control" >&2; exit 1; }

mkdir -p "$OUT"
PKGROOT="$OUT/pkgroot-$RID"
rm -rf "$PKGROOT"
mkdir -p "$PKGROOT/opt/orginventory" "$PKGROOT/etc/orginventory" "$PKGROOT/lib/systemd/system" "$PKGROOT/DEBIAN"

# Publish agent self-contained
dotnet publish "$HERE/../../linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -p:IncludeNativeLibrariesForSelfExtract=false \
  -o "$PKGROOT/opt/orginventory" -p:ApplicationIcon=

# Ghi VERSION cạnh binary — install.sh dùng để so sánh manifest auto-upgrade
printf '%s\n' "$VERSION" > "$PKGROOT/opt/orginventory/VERSION"

cp "$HERE/systemd/orginventory-agent.service" "$PKGROOT/lib/systemd/system/"

# Control được sinh theo RID — template giữ Architecture: amd64 làm mặc định
sed "s/^Architecture:.*/Architecture: ${DEB_ARCH}/" "$HERE/debian/control" > "$PKGROOT/DEBIAN/control"
[ -f "$HERE/debian/conffiles" ] && cp "$HERE/debian/conffiles" "$PKGROOT/DEBIAN/"
cp "$HERE/debian/postinst" "$PKGROOT/DEBIAN/"
cp "$HERE/debian/prerm" "$PKGROOT/DEBIAN/"
chmod 0755 "$PKGROOT/DEBIAN/postinst" "$PKGROOT/DEBIAN/prerm"

PKG="$OUT/orginventory-agent_${VERSION}_${DEB_ARCH}.deb"
dpkg-deb --build "$PKGROOT" "$PKG"
echo "Built $PKG (Architecture: $DEB_ARCH, RID: $RID)"
