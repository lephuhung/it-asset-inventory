#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RID="${1:-linux-x64}"
OUT="${2:-dist}"
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

cp "$HERE/systemd/orginventory-agent.service" "$PKGROOT/lib/systemd/system/"

cp "$HERE/debian/control" "$PKGROOT/DEBIAN/"
[ -f "$HERE/debian/conffiles" ] && cp "$HERE/debian/conffiles" "$PKGROOT/DEBIAN/"
cp "$HERE/debian/postinst" "$PKGROOT/DEBIAN/"
cp "$HERE/debian/prerm" "$PKGROOT/DEBIAN/"
chmod 0755 "$PKGROOT/DEBIAN/postinst" "$PKGROOT/DEBIAN/prerm"

ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
PKG="$OUT/orginventory-agent_1.1.0_${ARCH}.deb"
dpkg-deb --build "$PKGROOT" "$PKG"
echo "Built $PKG"