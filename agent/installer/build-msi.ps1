<#
.SYNOPSIS
  Build MSI cho OrgInventory Agent (WiX Toolset v4+). CHỈ CHẠY ĐƯỢC TRÊN WINDOWS.

.DESCRIPTION
  1. Kiểm tra dotnet + WiX (wix). Nếu thiếu WiX → cài qua `dotnet tool install --global wix`.
  2. Publish agent self-contained single-file cho win-x64.
  3. `wix build` → OrgInventoryAgent.msi + file .sha256 (server publish dùng để verify tải về).
  4. Tùy chọn: ký Authenticode (signtool) nếu truyền -Sign -CertificateThumbprint.

.EXAMPLE
  .\build-msi.ps1
  .\build-msi.ps1 -CertificateThumbprint "<thumb EV code signing>"
#>
[CmdletBinding()]
param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [switch]$Sign,
    [string]$CertificateThumbprint = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Project = Join-Path $Root "src\OrgInventoryAgent\OrgInventoryAgent.csproj"
$PublishDir = Join-Path $Root "publish\$Runtime"
$Wxs = Join-Path $PSScriptRoot "Product.wxs"
$Msi = Join-Path $PSScriptRoot "OrgInventoryAgent.msi"
$Sha = "$Msi.sha256"

Write-Host "== OrgInventory Agent MSI build ==" -ForegroundColor Cyan

# 1. dotnet
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw "Thiếu dotnet SDK 8 — cài từ https://dotnet.microsoft.com/download"
}

# 2. WiX v4 (dotnet global tool `wix`)
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    Write-Host "Chưa có WiX → cài: dotnet tool install --global wix" -ForegroundColor Yellow
    dotnet tool install --global wix
    if ($LASTEXITCODE -ne 0) { throw "Cài WiX thất bại" }
    # refresh PATH
    $env:Path = "$env:USERPROFILE\.dotnet\tools;" + $env:Path
}
$wixVersion = & wix --version
Write-Host "WiX: $wixVersion"

# 3. Publish agent (self-contained single-file, có icon/metadata)
Write-Host "Publish agent ($Runtime, self-contained single-file)..."
dotnet publish $Project -c $Configuration -r $Runtime --self-contained true -o $PublishDir
if ($LASTEXITCODE -ne 0) { throw "dotnet publish thất bại" }
$AgentExe = Join-Path $PublishDir "OrgInventoryAgent.exe"
if (-not (Test-Path $AgentExe)) { throw "Không thấy $AgentExe sau khi publish" }

# 4. Build MSI
Write-Host "Build MSI..."
& wix build $Wxs -d AgentExe=$AgentExe -o $Msi -arch x64
if ($LASTEXITCODE -ne 0) { throw "wix build thất bại" }

# 5. Ký Authenticode (bắt buộc cho production — tránh AV false positive + SmartScreen)
if ($Sign) {
    if (-not (Get-Command signtool -ErrorAction SilentlyContinue)) {
        throw "Thiếu signtool (Windows SDK). Cài Windows SDK hoặc truyền đường dẫn."
    }
    $args = @("sign", "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256")
    if ($CertificateThumbprint) { $args += @("/sha1", $CertificateThumbprint) }
    $args += $Msi
    & signtool @args
    if ($LASTEXITCODE -ne 0) { throw "Ký MSI thất bại" }
    Write-Host "Đã ký Authenticode: $Msi" -ForegroundColor Green
} else {
    Write-Host "Chưa ký MSI (dùng -Sign -CertificateThumbprint ... để ký)." -ForegroundColor Yellow
}

# 6. SHA256 (server publish dùng cho verify tải về trong install.ps1)
$hash = (Get-FileHash $Msi -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path $Sha -Value $hash -NoNewline
Write-Host "SHA256: $hash"
Write-Host "MSI : $Msi" -ForegroundColor Green
Write-Host "Done."
