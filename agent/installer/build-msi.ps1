<#
.SYNOPSIS
  Build MSI cho OrgInventory Agent (WiX Toolset v4+). CHI CHAY DUOC TREN WINDOWS.

.DESCRIPTION
  1. Kiem tra dotnet + WiX (wix). Neu thieu WiX -> cai qua `dotnet tool install --global wix`.
  2. Publish agent self-contained single-file cho win-x64.
  3. `wix build` -> OrgInventoryAgent.msi + file .sha256.
  4. Tuy chon: ky Authenticode (signtool) neu truyen -Sign -CertificateThumbprint.

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
# WiX >= 6.0 doi phai accept OSMF EULA moi build duoc -> pin ve 5.x da verify
$WixVersion = "5.0.2"

Write-Host "== OrgInventory Agent MSI build ==" -ForegroundColor Cyan

# Setup DOTNET_ROOT & PATH if user-local dotnet install
if ([string]::IsNullOrWhiteSpace($env:DOTNET_ROOT) -and (Test-Path "$env:USERPROFILE\.dotnet")) {
    $env:DOTNET_ROOT = "$env:USERPROFILE\.dotnet"
}
if (-not [string]::IsNullOrWhiteSpace($env:DOTNET_ROOT)) {
    $env:PATH = "$env:DOTNET_ROOT;$env:DOTNET_ROOT\tools;$env:PATH"
}

# 1. dotnet
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw "Thieu dotnet SDK 8 - cai tu https://dotnet.microsoft.com/download"
}

# 2. WiX (dotnet global tool `wix`), pin $WixVersion
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    Write-Host "Chua co WiX -> cai: dotnet tool install --global wix --version $WixVersion" -ForegroundColor Yellow
    dotnet tool install --global wix --version $WixVersion
    if ($LASTEXITCODE -ne 0) { throw "Cai WiX that bai" }
    $env:Path = "$env:USERPROFILE\.dotnet\tools;" + $env:Path
}
$wixVersion = & wix --version
$wixMajor = [int](($wixVersion -split '\.')[0])
if ($wixMajor -ge 6) {
    Write-Host "WiX $wixVersion can OSMF EULA -> downgrade ve $WixVersion" -ForegroundColor Yellow
    dotnet tool update --global wix --version $WixVersion
    if ($LASTEXITCODE -ne 0) { throw "Downgrade WiX that bai" }
    $wixVersion = & wix --version
}
Write-Host "WiX: $wixVersion"

# 3. Publish agent (self-contained single-file, co icon/metadata)
Write-Host "Publish agent ($Runtime, self-contained single-file)..."
dotnet publish $Project -c $Configuration -r $Runtime --self-contained true -o $PublishDir
if ($LASTEXITCODE -ne 0) { throw "dotnet publish that bai" }
$AgentExe = Join-Path $PublishDir "OrgInventoryAgent.exe"
if (-not (Test-Path $AgentExe)) { throw "Khong thay $AgentExe sau khi publish" }
# e_sqlite3.dll native phai nam canh exe (publish tat self-extract de tranh AV FP)
$SqliteDll = Join-Path $PublishDir "e_sqlite3.dll"
if (-not (Test-Path $SqliteDll)) { throw "Khong thay $SqliteDll sau khi publish - OfflineCache can SQLite native lib" }

# 3b. WiX Util extension (util:ServiceConfig cho restart-on-failure)
if (-not (& wix extension list 2>$null | Select-String -Quiet "WixToolset.Util")) {
    Write-Host "Cai WixToolset.Util.wixext..."
    & wix extension add WixToolset.Util.wixext
    if ($LASTEXITCODE -ne 0) { throw "Cai WiX Util extension that bai" }
}

# 4. Build MSI
Write-Host "Build MSI..."
& wix build $Wxs -ext WixToolset.Util.wixext -d AgentExe=$AgentExe -d AgentSqliteDll=$SqliteDll -o $Msi -arch x64
if ($LASTEXITCODE -ne 0) { throw "wix build that bai" }

# 5. Ky Authenticode (neu co)
if ($Sign) {
    if (-not (Get-Command signtool -ErrorAction SilentlyContinue)) {
        throw "Thieu signtool (Windows SDK)."
    }
    $signArgs = @("sign", "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256")
    if ($CertificateThumbprint) { $signArgs += @("/sha1", $CertificateThumbprint) }
    $signArgs += $Msi
    & signtool @signArgs
    if ($LASTEXITCODE -ne 0) { throw "Ky MSI that bai" }
    Write-Host "Da ky Authenticode: $Msi" -ForegroundColor Green
} else {
    Write-Host "Chua ky MSI (dung -Sign -CertificateThumbprint de ky)." -ForegroundColor Yellow
}

# 6. SHA256
$hash = (Get-FileHash $Msi -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path $Sha -Value $hash -NoNewline
Write-Host "SHA256: $hash"
Write-Host "MSI : $Msi" -ForegroundColor Green
Write-Host "Build MSI thanh cong." -ForegroundColor Green
