#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="${1:-dist}"
mkdir -p "$DIST"

for RID in linux-x64 linux-arm64; do
    dotnet publish "$HERE/../../linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
      -c Release -r "$RID" --self-contained true \
      -p:PublishSingleFile=true \
      -p:EnableCompressionInSingleFile=false \
      -p:IncludeNativeLibrariesForSelfExtract=false \
      -o "$DIST/$RID" -p:ApplicationIcon=

    dotnet publish "$HERE/../../src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj" \
      -c Release -r "$RID" --self-contained true \
      -p:PublishSingleFile=true \
      -p:EnableCompressionInSingleFile=false \
      -o "$DIST/$RID"
done

echo "Built in $DIST/{linux-x64,linux-arm64}/"