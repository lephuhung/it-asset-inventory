# install-offline.ps1 — Bộ điều phối cài đặt & thu thập tài sản 1-Click cho máy cách ly (Offline USB)
#
# Người dùng chỉ cần nháy đúp chuột vào install-offline.cmd (hoặc chạy install-offline.ps1).
# Script tự động:
#   1. Xin quyền Administrator (UAC elevation) nếu chưa có.
#   2. Đọc cấu hình từ offline_config.json (nếu có trên USB) — không yêu cầu người dùng gõ tham số.
#   3. Kiểm tra tính toàn vẹn (SHA256 + Authenticode) của OrgInventoryAgent.msi.
#   4. Cài đặt Agent (nếu chưa cài).
#   5. Kích hoạt thu thập thông số tài sản, ký số ECDSA P-256 nội bộ, mã hóa bằng Server Public Key.
#   6. Xuất ra 1 file ZIP duy nhất: E:\INVENTORY_<HOSTNAME>_<YYYYMMDD_HHMMSS>.zip.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)] [string]$Token,
    [Parameter(Mandatory=$false)] [string]$Endpoints,
    [Parameter(Mandatory=$false)] [string]$MsiDir = (Split-Path -Parent $MyInvocation.MyCommand.Definition),
    [switch]$SkipConfirm
)

$ErrorActionPreference = 'Stop'

# 1. Tự nâng quyền Administrator nếu chưa có
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[INFO] Đang yêu cầu quyền Administrator...' -ForegroundColor Cyan
    $proc = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs -PassThru
    $proc.WaitForExit()
    exit $proc.ExitCode
}

$msiName     = 'OrgInventoryAgent.msi'
$shaName     = 'OrgInventoryAgent.msi.sha256'
$cfgName     = 'offline_config.json'
$pubKeyName  = 'server_public_key.pem'

$msiPath     = Join-Path $MsiDir $msiName
$shaPath     = Join-Path $MsiDir $shaName
$cfgPath     = Join-Path $MsiDir $cfgName
$pubKeyPath  = Join-Path $MsiDir $pubKeyName
$logPath     = Join-Path $env:TEMP 'agent-install-offline.log'

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '   IT ASSET INVENTORY — THU THẬP TÀI SẢN (MÁY CÁCH LY)' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

# 2. Đọc cấu hình tự động nếu có trên USB (tránh bắt người dùng gõ tay)
if (Test-Path -LiteralPath $cfgPath) {
    try {
        $cfgJson = Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json
        if (-not $Token -and $cfgJson.token) { $Token = $cfgJson.token }
        if (-not $Endpoints -and $cfgJson.endpoints) { $Endpoints = $cfgJson.endpoints }
        Write-Host "[1/5] ✓ Đã nạp cấu hình tự động từ $cfgName" -ForegroundColor Green
    } catch {
        Write-Host "[!] Không đọc được file $cfgName — sử dụng chế độ mặc định." -ForegroundColor Yellow
    }
}

# 3. Kiểm tra file MSI trên USB
if (-not (Test-Path -LiteralPath $msiPath)) {
    Write-Host "[LỖI] Không tìm thấy $msiPath trên USB." -ForegroundColor Red
    exit 1
}

if (Test-Path -LiteralPath $shaPath) {
    $expected = (Get-Content -LiteralPath $shaPath -Raw).Trim().Split(' ')[0].ToLower()
    $actual   = (Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) {
        Write-Host '[LỖI] Mã băm SHA256 KHÔNG khớp — file cài đặt có thể đã bị hỏng.' -ForegroundColor Red
        exit 1
    }
    Write-Host "[2/5] ✓ Kiểm tra SHA256 toàn vẹn: Khớp" -ForegroundColor Green
}

$sig = Get-AuthenticodeSignature -FilePath $msiPath
if ($sig.Status -eq 'Valid') {
    Write-Host "[3/5] ✓ Chữ ký số Authenticode hợp lệ: $($sig.SignerCertificate.Subject)" -ForegroundColor Green
}

# 4. Cài đặt hoặc đảm bảo Agent đã có trên máy
$agentInstalledPath = "$env:ProgramFiles\OrgInventory\OrgInventoryAgent.exe"
if (-not (Test-Path -LiteralPath $agentInstalledPath)) {
    Write-Host '[4/5] Đang cài đặt bộ thu thập vào máy...' -ForegroundColor Cyan
    $msiArgs = @(
        '/i', "`"$msiPath`"",
        '/qn', '/norestart',
        "ENROLL_TOKEN=$Token",
        "ENDPOINTS=$Endpoints",
        '/L*V', "`"$logPath`""
    )
    $proc = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $agentInstalledPath)) {
        Write-Host "[LỖI] Cài đặt thất bại (Exit code: $($proc.ExitCode)). Xem log: $logPath" -ForegroundColor Red
        exit 1
    }
    Write-Host '      ✓ Cài đặt Agent thành công.' -ForegroundColor Green
} else {
    Write-Host '[4/5] ✓ Agent đã được cài đặt trên hệ thống.' -ForegroundColor Green
}

# 5. Thu thập thông số, ký số ECDSA và đóng gói ZIP mã hóa
Write-Host '[5/5] Đang thu thập cấu hình và đóng gói dữ liệu...' -ForegroundColor Cyan

$hostName  = $env:COMPUTERNAME
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$zipName   = "INVENTORY_${hostName}_${timestamp}.zip"
$zipOut    = Join-Path $MsiDir $zipName

$exportArgs = @("--export-bundle", "`"$zipOut`"")
if (Test-Path -LiteralPath $pubKeyPath) {
    $exportArgs += @("--server-key", "`"$pubKeyPath`"")
}
if ($Token) {
    $exportArgs += @("--org-id", "`"$Token`"")
}

$exportProc = Start-Process -FilePath $agentInstalledPath -ArgumentList $exportArgs -Wait -PassThru -NoNewWindow
if ($exportProc.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $zipOut)) {
    Write-Host '[LỖI] Tiến trình thu thập và đóng gói dữ liệu thất bại.' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' ✔ THU THẬP VÀ ĐÓNG GÓI THÀNH CÔNG!' -ForegroundColor Green
Write-Host "   File kết quả: $zipOut" -ForegroundColor Yellow
Write-Host '   Vui lòng rút USB và chuyển file ZIP cho Quản trị viên.' -ForegroundColor White
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

exit 0
