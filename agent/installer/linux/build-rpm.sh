#!/bin/bash
# Build RPM cho OrgInventory Agent Linux.
#   ./build-rpm.sh [RID] [OUT]
#     RID: linux-x64 (mặc định) | linux-arm64
#
# RPM target arch PHẢI theo RID (linux-x64→x86_64, linux-arm64→aarch64) —
# không dùng arch build host. Cần rpmbuild + systemd-rpm-macros trên host.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RID="${1:-linux-x64}"
OUT="${2:-dist}"

case "$RID" in
    linux-x64)   RPM_ARCH="x86_64" ;;
    linux-arm64) RPM_ARCH="aarch64" ;;
    *) echo "RID không hỗ trợ: $RID (chỉ linux-x64 | linux-arm64)" >&2; exit 1 ;;
esac

VERSION="$(sed -n 's/^Version: *//p' "$HERE/rpm/orginventory.spec" | head -n1)"
[[ -n "$VERSION" ]] || { echo "Không đọc được Version từ rpm/orginventory.spec" >&2; exit 1; }

mkdir -p "$OUT"
BUILDDIR="$OUT/build-$RID"
rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR/orginventory/opt" "$BUILDDIR/orginventory/systemd"

dotnet publish "$HERE/../../linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -o "$BUILDDIR/orginventory/opt/orginventory" -p:ApplicationIcon=

# VERSION cạnh binary — install.sh dùng để so sánh manifest auto-upgrade
printf '%s\n' "$VERSION" > "$BUILDDIR/orginventory/opt/orginventory/VERSION"

cp "$HERE/systemd/orginventory-agent.service" "$BUILDDIR/orginventory/systemd/"

rpmbuild --define "_topdir $OUT/rpm" --define "_builddir $BUILDDIR" \
  --target "$RPM_ARCH" \
  -bb "$HERE/rpm/orginventory.spec"
echo "Built RPM (arch: $RPM_ARCH, RID: $RID) in $OUT/rpm/RPMS/"
