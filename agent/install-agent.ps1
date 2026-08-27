<#
.SYNOPSIS
  Script cai dat tu dong OrgInventory Agent tren Windows.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Token = $env:ORGINVENTORY_TOKEN,
    [Parameter(Mandatory=$false)]
    [string]$Endpoint = $env:ORGINVENTORY_ENDPOINT,
    [switch]$TestOnce
)

$ErrorActionPreference = "Stop"

if (-not $Endpoint) {
    Write-Host "[!] Chua chi dinh dia chi may chu (-Endpoint hoac env ORGINVENTORY_ENDPOINT)." -ForegroundColor Yellow
    $Endpoint = Read-Host "Nhap dia chi may chu (VD: https://agent.example.gov.vn hoac http://localhost:8000)"
    if (-not $Endpoint) {
        throw "Can cung cap dia chi may chu de Agent ket noi."
    }
}
$Endpoint = $Endpoint.Trim().TrimEnd('/')

if (-not $Token -and -not $TestOnce) {
    Write-Host "[!] Chua chi dinh Enroll Token (-Token hoac env ORGINVENTORY_TOKEN)." -ForegroundColor Yellow
    $Token = Read-Host "Nhap Enroll Token duoc cap tu Portal"
    if (-not $Token) {
        throw "Can cung cap Enroll Token de kich hoat Agent."
    }
}
if ($Token) { $Token = $Token.Trim() }

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       IT ASSET INVENTORY - CAI DAT AGENT WINDOWS         " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  May chu dich : " -NoNewline; Write-Host "$Endpoint" -ForegroundColor Yellow
Write-Host "  Enroll Token : " -NoNewline; Write-Host "$($Token.Substring(0, [Math]::Min(8, $Token.Length)))..." -ForegroundColor Yellow
Write-Host ""

# 1. Kiem tra quyen Administrator
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin -and -not $TestOnce) {
    Write-Host "[CANH BAO] Can quyen Administrator de cai dat Windows Service." -ForegroundColor Yellow
    Write-Host "Dang yeu cau nang quyen (UAC)..." -ForegroundColor Cyan
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Token `"$Token`" -Endpoint `"$Endpoint`""
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MsiPath = Join-Path $ScriptDir "installer\OrgInventoryAgent.msi"
$ExePath = Join-Path $ScriptDir "publish\win-x64\OrgInventoryAgent.exe"
$LogDir = Join-Path $env:ProgramData "OrgInventory\logs"
$LogFile = Join-Path $LogDir "agent.log"
$InstallLog = Join-Path $env:TEMP "OrgInventoryAgent-install.log"

# Che do chay thu nghiem (TestOnce)
if ($TestOnce) {
    Write-Host "==> Chay thu nghiem Agent (Console mode)..." -ForegroundColor Magenta
    if (-not (Test-Path $ExePath)) {
        throw "Khong tim thay file thuc thi tai: $ExePath"
    }
    & $ExePath --endpoint $Endpoint --enroll-token $Token --once
    exit $LASTEXITCODE
}

# 2. Kiem tra file MSI bo cai
Write-Host "[1/4] Kiem tra goi cai dat..." -ForegroundColor Cyan
if (-not (Test-Path $MsiPath)) {
    throw "Khong tim thay file bo cai MSI tai: $MsiPath"
}
Write-Host "      [OK] Da tim thay: $MsiPath" -ForegroundColor Green

# 3. Tien hanh cai dat silent qua msiexec
Write-Host "[2/4] Dang cai dat OrgInventory Agent vao he thong..." -ForegroundColor Cyan
$msiArgs = @(
    "/i", "`"$MsiPath`"",
    "/qn",
    "/norestart",
    "ENROLL_TOKEN=`"$Token`"",
    "ENDPOINTS=`"$Endpoint`"",
    "/L*V", "`"$InstallLog`""
)

$process = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru

if ($process.ExitCode -ne 0) {
    Write-Host "[LOI] Cai dat that bai voi ma loi: $($process.ExitCode)" -ForegroundColor Red
    Write-Host "      Xem chi tiet nhat ky tai: $InstallLog" -ForegroundColor Yellow
    exit $process.ExitCode
}
Write-Host "      [OK] Cai dat MSI thanh cong!" -ForegroundColor Green

# 4. Kiem tra dich vu Windows Service
Write-Host "[3/4] Kiem tra dich vu Windows Service..." -ForegroundColor Cyan
Start-Sleep -Seconds 2
$service = Get-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue

if ($service) {
    Write-Host "      [OK] Dich vu: $($service.DisplayName) (Status: $($service.Status))" -ForegroundColor Green
    if ($service.Status -ne "Running") {
        Write-Host "      Khoi dong dich vu..." -ForegroundColor Yellow
        Start-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "[CANH BAO] Khong tim thay service OrgInventoryAgent trong SCM." -ForegroundColor Yellow
}

# 5. Hoan tat
Write-Host "[4/4] Hoan tat qua trinh cai dat!" -ForegroundColor Cyan
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  AGENT DA DUOC CAI DAT VA HOAT DONG THANH CONG!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  - Du lieu agent luu tai : $env:ProgramData\OrgInventory" -ForegroundColor White
Write-Host "  - File nhat ky (Log)    : $LogFile" -ForegroundColor White
Write-Host "  - Chu ky gui Heartbeat  : Dong bo tu dong tu may chu (mac dinh 30s)" -ForegroundColor Gray
Write-Host "  - May chu ket noi       : $Endpoint" -ForegroundColor Cyan
Write-Host ""
Write-Host "Theo doi log ket noi real-time bang lenh:" -ForegroundColor Yellow
Write-Host "Get-Content '$LogFile' -Wait -Tail 30" -ForegroundColor White
Write-Host ""
