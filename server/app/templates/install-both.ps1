<#
.SYNOPSIS
  Cai dat CUNG LUC 2 agent bang 1 lenh:
    1) OrgInventory Agent  - kiem ke tai san CNTT & ATTT (MSI -> Windows Service "OrgInventoryAgent")
    2) Velociraptor Client - DFIR (MSI -> service "Velociraptor" / "Velociraptor Service")

.DESCRIPTION
  Lenh 1-cham (one-liner) - chay tu server /download/install-both.ps1:
    powershell -NoProfile -ExecutionPolicy Bypass -Command '$env:ORGINVENTORY_TOKEN="t_xxx";$env:ORGINVENTORY_PORTAL_URL="https://portal.gov.vn";irm https://portal.gov.vn/download/install-both.ps1|iex'
  (nho dung nhay DON cho -Command de PowerShell ngoai khong expand $env truoc)

  Hoac chay truc tiep file nay (param hoac env):
    .\install-both.ps1 -Token t_xxx -PortalUrl https://portal.gov.vn -Endpoint https://agent.gov.vn

  Luong xu ly:
    [1] Kiem tra quyen Administrator (tu dong nang quyen UAC neu chay tu file)
    [2] Exclusion Defender (chong false-positive)
    [3] Tai + verify OrgInventoryAgent.msi (SHA256 + chu ky Authenticode) -> msiexec /qn
    [4] Tai Velociraptor MSI + client.config.yaml -> msiexec /qn -> ghi de config -> restart service
    [5] Verify ca 2 service

.NOTES
  - Velociraptor MSI mac dinh la bản stock (placeholder config) -> script tu dong tai
    client.config.yaml tu server va ghi de len cau hinh MSI, giong install-velociraptor.bat.
    Neu admin da dung artifact Server.Utils.CreateMSI de tao MSI da nhung config san,
    chi can truyen -VelociraptorMsiUrl vao MSI do (bo qua -VelociraptorConfigUrl).
  - MSI chua ky chi duoc phep cai khi env ORGINV_ALLOW_UNSIGNED=1 (chi dung TEST).
#>
[CmdletBinding()]
param(
    [string]$Token = $env:ORGINVENTORY_TOKEN,
    [string]$PortalUrl = $env:ORGINVENTORY_PORTAL_URL,
    [string]$Endpoint = $env:ORGINVENTORY_ENDPOINT,
    [string]$OrgInventoryMsiUrl = $env:ORGINVENTORY_MSI_URL,
    [string]$VelociraptorMsiUrl = $env:VELOCIRAPTOR_MSI_URL,
    [string]$VelociraptorConfigUrl = $env:VELOCIRAPTOR_CONFIG_URL,
    [switch]$SkipOrgInventory,
    [switch]$SkipVelociraptor
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Msg) { Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "      [OK] $Msg" -ForegroundColor Green }
function Write-Fail([string]$Msg) { Write-Host "      [LOI] $Msg" -ForegroundColor Red }

# ── 0. Kiem tra tham so ────────────────────────────────────────────────
if ($null -eq $PortalUrl) { $PortalUrl = "" }
if ($null -eq $Endpoint)  { $Endpoint = "" }
$PortalUrl = $PortalUrl.Trim().TrimEnd('/')
$Endpoint  = $Endpoint.Trim().TrimEnd('/')

if (-not $PortalUrl -and -not $SkipOrgInventory) {
    Write-Fail "Thieu PortalUrl (param -PortalUrl hoac env ORGINVENTORY_PORTAL_URL)."
    exit 1
}
if (-not $Token -and -not $SkipOrgInventory) {
    Write-Fail "Thieu Enroll Token (param -Token hoac env ORGINVENTORY_TOKEN)."
    exit 1
}
if (-not $Endpoint) { $Endpoint = $PortalUrl }
if (-not $OrgInventoryMsiUrl)    { $OrgInventoryMsiUrl = "$PortalUrl/download/agent.msi" }
if (-not $VelociraptorMsiUrl)    { $VelociraptorMsiUrl = "$PortalUrl/download/velociraptor-windows-amd64.msi" }
if (-not $VelociraptorConfigUrl) { $VelociraptorConfigUrl = "$PortalUrl/download/velociraptor-client.config.yaml" }

Write-Host ""
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "  CAI DAT DONG THOI 2 AGENT" -ForegroundColor Cyan
Write-Host "    1. OrgInventory Agent (kiem ke)  -> service: OrgInventoryAgent" -ForegroundColor White
Write-Host "    2. Velociraptor Client (DFIR)    -> service: Velociraptor" -ForegroundColor White
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "  Portal : $PortalUrl" -ForegroundColor Yellow
if ($Token) { Write-Host "  Token  : $($Token.Substring(0, [Math]::Min(8, $Token.Length)))..." -ForegroundColor Yellow }
Write-Host ""

# ── 1. Quyen Administrator ─────────────────────────────────────────────
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    if ($PSCommandPath) {
        Write-Host "[CANH BAO] Can quyen Administrator - dang yeu cau nang quyen (UAC)..." -ForegroundColor Yellow
        Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Token `"$Token`" -PortalUrl `"$PortalUrl`" -Endpoint `"$Endpoint`"" 
        exit 0
    }
    Write-Host "[LOI] Can chay PowerShell voi quyen Administrator." -ForegroundColor Red
    Write-Host "      Chuot phai -> Run as administrator, hoac chay lai trong session da nang quyen." -ForegroundColor Yellow
    exit 1
}

# ── 2. Exclusion Defender (chong false-positive giong install.ps1) ─────
try {
    Add-MpPreference -ExclusionPath "$env:ProgramFiles\OrgInventory" -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionPath "$env:ProgramFiles\Velociraptor" -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionProcess "OrgInventoryAgent.exe" -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionProcess "velociraptor.exe" -ErrorAction SilentlyContinue
} catch { }

$TmpDir = Join-Path $env:TEMP "install-both"
New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null
$InstallLog = Join-Path $env:TEMP "install-both.log"

function Download-File([string]$Url, [string]$OutPath, [string]$Label) {
    Write-Host "      Tai $Label ..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $Url -OutFile $OutPath -UseBasicParsing -TimeoutSec 120
    Unblock-File -Path $OutPath -ErrorAction SilentlyContinue
    Write-Ok "$Label da tai ($((Get-Item $OutPath).Length / 1MB) MB)"
}

function Invoke-Msiexec([string]$MsiPath, [string[]]$Props, [string]$Label) {
    $argsList = @('/i', "`"$MsiPath`"", '/qn', '/norestart') + $Props + @('/L*V', "`"$InstallLog`"")
    $p = Start-Process msiexec.exe -ArgumentList $argsList -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Write-Fail "$Label that bai (exit code: $($p.ExitCode)). Xem log: $InstallLog"
        exit $p.ExitCode
    }
    Write-Ok "$Label da cai dat thanh cong"
}

# ── 3. OrgInventory Agent ──────────────────────────────────────────────
if (-not $SkipOrgInventory) {
    Write-Step "[1/4] Cai dat OrgInventory Agent ..."
    $msiPath = Join-Path $TmpDir "OrgInventoryAgent.msi"
    try { Download-File $OrgInventoryMsiUrl $msiPath "OrgInventoryAgent.msi" } catch {
        Write-Fail "Khong tai duoc OrgInventory MSI: $($_.Exception.Message)"; exit 1
    }

    # Verify SHA256 tu server
    try {
        $expected = (Invoke-WebRequest -Uri "$PortalUrl/download/agent.msi.sha256" -UseBasicParsing -TimeoutSec 30).Content.Trim().Split()[0]
        $actual = (Get-FileHash -Path $msiPath -Algorithm SHA256).Hash.ToLower()
        if ($expected.ToLower() -ne $actual) {
            Write-Fail "SHA256 khong khop (server: $expected, file: $actual) — dung cai dat."
            exit 1
        }
        Write-Ok "SHA256 khop"
    } catch {
        Write-Host "      [WARN] Khong verify duoc SHA256: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    # Verify chu ky Authenticode (MSI chua ky chi khi ORGINV_ALLOW_UNSIGNED=1)
    $sig = Get-AuthenticodeSignature -FilePath $msiPath
    $allowUnsigned = ($env:ORGINV_ALLOW_UNSIGNED -eq '1')
    if ($sig.Status -ne 'Valid' -and -not $allowUnsigned) {
        Write-Fail "Chu ky so khong hop le (Status: $($sig.Status)). Da dung cai dat."
        Remove-Item $msiPath -Force -ErrorAction SilentlyContinue
        exit 1
    }
    if ($sig.Status -eq 'Valid') { Write-Ok "Chu ky hop le: $($sig.SignerCertificate.Subject)" }
    else { Write-Host "      [WARN] MSI khong ky Authenticode — bo qua vi ORGINV_ALLOW_UNSIGNED=1 (CHI DUNG TEST)" -ForegroundColor Yellow }

    Invoke-Msiexec $msiPath @("ENROLL_TOKEN=$Token", "TOKEN=$Token", "ENDPOINTS=$Endpoint") "OrgInventory Agent"
    Start-Sleep -Seconds 2
}

# ── 4. Velociraptor Client ─────────────────────────────────────────────
if (-not $SkipVelociraptor) {
    Write-Step "[2/4] Cai dat Velociraptor Client ..."
    $vrMsi = Join-Path $TmpDir "velociraptor-windows-amd64.msi"
    $vrCfg = Join-Path $TmpDir "client.config.yaml"
    try {
        Download-File $VelociraptorMsiUrl $vrMsi "Velociraptor MSI"
        Download-File $VelociraptorConfigUrl $vrCfg "client.config.yaml"
    } catch {
        Write-Fail "Khong tai duoc Velociraptor package: $($_.Exception.Message)"; exit 1
    }

    Invoke-Msiexec $vrMsi @() "Velociraptor Client"

    # Ghi de config (MSI stock dung placeholder config)
    $vrDir = Join-Path $env:ProgramFiles "Velociraptor"
    $cfgDst = Join-Path $vrDir "client.config.yaml"
    if (Test-Path $vrDir) {
        Copy-Item -Path $vrCfg -Destination $cfgDst -Force
        Write-Ok "Config da ghi de: $cfgDst"
    } else {
        Write-Host "      [WARN] Khong thay thu muc $vrDir — bo qua ghi de config" -ForegroundColor Yellow
    }

    # Restart service (service name "Velociraptor", display name "Velociraptor Service")
    $svc = Get-Service -Name "Velociraptor" -ErrorAction SilentlyContinue
    if (-not $svc) { $svc = Get-Service | Where-Object { $_.DisplayName -like "*Velociraptor*" } | Select-Object -First 1 }
    if ($svc) {
        Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-Service -Name $svc.Name -ErrorAction SilentlyContinue
        Write-Ok "Da khoi dong lai service: $($svc.Name)"
    } else {
        Write-Host "      [WARN] Khong tim thay service Velociraptor" -ForegroundColor Yellow
    }
}

# ── 5. Verify ──────────────────────────────────────────────────────────
Write-Step "[3/4] Kiem tra dich vu ..."
Start-Sleep -Seconds 2
if (-not $SkipOrgInventory) {
    $oi = Get-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
    if ($oi) { Write-Ok "OrgInventoryAgent: $($oi.Status)" } else { Write-Fail "Khong thay service OrgInventoryAgent" }
}
if (-not $SkipVelociraptor) {
    $vr = Get-Service -Name "Velociraptor" -ErrorAction SilentlyContinue
    if (-not $vr) { $vr = Get-Service | Where-Object { $_.DisplayName -like "*Velociraptor*" } | Select-Object -First 1 }
    if ($vr) { Write-Ok "Velociraptor ($($vr.Name)): $($vr.Status)" } else { Write-Fail "Khong thay service Velociraptor" }
}

# ── 6. Hoan tat ────────────────────────────────────────────────────────
Write-Step "[4/4] Hoan tat!"
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  CA 2 AGENT DA DUOC CAI DAT!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  - OrgInventory: service 'OrgInventoryAgent', log: $env:ProgramData\OrgInventory\logs\agent.log" -ForegroundColor White
Write-Host "  - Velociraptor: service 'Velociraptor',    log: $env:ProgramFiles\Velociraptor\logs\velociraptor.log" -ForegroundColor White
Write-Host "  - Verify enroll Velociraptor: mo GUI https://<velociraptor-host>:8889 -> tab Clients (~30s)" -ForegroundColor Gray
Write-Host "  - Mapping sang portal /dfir sau toi da ~5 phut" -ForegroundColor Gray
Write-Host ""
Write-Host "Theo doi log OrgInventory: Get-Content '$env:ProgramData\OrgInventory\logs\agent.log' -Wait -Tail 30" -ForegroundColor Yellow
Write-Host ""
