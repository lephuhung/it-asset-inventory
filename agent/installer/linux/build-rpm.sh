#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RID="${1:-linux-x64}"
OUT="${2:-dist}"
mkdir -p "$OUT"
BUILDDIR="$OUT/build-$RID"
rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR/orginventory/opt" "$BUILDDIR/orginventory/systemd"

dotnet publish "$HERE/../../linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -o "$BUILDDIR/orginventory/opt/orginventory" -p:ApplicationIcon=

dotnet publish "$HERE/../../src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -o "$BUILDDIR/orginventory/opt/orginventory"

cp "$HERE/systemd/"*.service "$HERE/systemd/"*.socket "$BUILDDIR/orginventory/systemd/"

rpmbuild --define "_topdir $OUT/rpm" --define "_builddir $BUILDDIR" \
  -bb "$HERE/rpm/orginventory.spec"
echo "Built RPM in $OUT/rpm/RPMS/"