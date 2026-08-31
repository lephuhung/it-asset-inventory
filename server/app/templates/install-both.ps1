<#
.SYNOPSIS
  Cai dat CUNG LUC 2 agent bang 1 lenh:
    1) OrgInventory Agent  - kiem ke tai san CNTT & ATTT
    2) Velociraptor Client - DFIR

.DESCRIPTION
  Lenh 1-cham (one-liner) - chay tu server /download/install-both.ps1:
    powershell -NoProfile -ExecutionPolicy Bypass -Command '$env:ORGINVENTORY_TOKEN="t_xxx";$env:ORGINVENTORY_PORTAL_URL="https://portal.gov.vn";irm https://portal.gov.vn/download/install-both.ps1|iex'

  Hoac chay truc tiep (param hoac env):
    .\install-both.ps1 -Token t_xxx -PortalUrl https://portal.gov.vn -Endpoint https://agent.gov.vn

  PHILOSOPHY: KHONG GO MSI neu khong can thiet.

    - Neu OrgInventory chua cai → cai MSI moi
    - Neu OrgInventory da cai → chi UPDATE config.json (token, endpoints) + restart service
      (Agent doc truc tiep config.json → khong can go MSI de doi token)
    - Tuong tu cho Velociraptor → chi UPDATE client.config.yaml

    ForceReinstall (optional): go + cai lai MSI (chi dung khi MSI bi loi)

  Luong xu ly:
    [1] Kiem tra quyen Administrator
    [2] Detect trang thai 2 agent (Installed? Service Running?)
    [3] OrgInventory: neu chua cai → cai MSI; neu da cai → update config.json
    [4] Velociraptor: neu chua cai → cai MSI; neu da cai → update client.config.yaml
    [5] Verify ca 2 service Running + enrollment status
#>
[CmdletBinding()]
param(
    [string]$Token = $env:ORGINVENTORY_TOKEN,
    [string]$PortalUrl = $env:ORGINVENTORY_PORTAL_URL,
    [string]$Endpoint = $env:ORGINVENTORY_ENDPOINT,
    [string]$OrgInventoryMsiUrl = $env:ORGINVENTORY_MSI_URL,
    [string]$VelociraptorMsiUrl = $env:VELOCIRAPTOR_MSI_URL,
    [string]$VelociraptorConfigUrl = $env:VELOCIRAPTOR_CONFIG_URL,
    [string]$VelociraptorConfigOnlyZipUrl = $env:VELOCIRAPTOR_CONFIG_ONLY_ZIP_URL,
    [switch]$SkipOrgInventory,
    [switch]$SkipVelociraptor,
    [switch]$ForceReinstall  # GO MSI + cai lai (chi dung khi MSI loi)
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Msg) { Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "      [OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "      [WARN] $Msg" -ForegroundColor Yellow }
function Write-Fail([string]$Msg) { Write-Host "      [FAIL] $Msg" -ForegroundColor Red }
function Write-Info([string]$Msg) { Write-Host "      [INFO] $Msg" -ForegroundColor Gray }

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
if (-not $VelociraptorConfigOnlyZipUrl) { $VelociraptorConfigOnlyZipUrl = "$PortalUrl/download/velociraptor-config-only.zip" }

Write-Host ""
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "  CAI DAT DONG THOI 2 AGENT (Smart Update)" -ForegroundColor Cyan
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
    Write-Fail "Can chay PowerShell voi quyen Administrator."
    exit 1
}

# ── 2. Detect trang thai 2 agent ────────────────────────────────────────
Write-Step "[1/5] Kiem tra trang thai agent hien tai..."

$oiInstalled = $false
$oiSvc = $null
if (-not $SkipOrgInventory) {
    $oiExisting = Get-WmiObject -Class Win32_Product -Filter "Name='OrgInventory Agent'" -ErrorAction SilentlyContinue
    if ($oiExisting) {
        $oiInstalled = $true
        $oiSvc = Get-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
        Write-Info "OrgInventory Agent da cai (v$($oiExisting.Version))"
        if ($oiSvc) {
            Write-Info "  Service: $($oiSvc.Status)"
        } else {
            Write-Warn "  Service khong chay (se khoi dong lai)"
        }
    } else {
        Write-Info "OrgInventory Agent chua duoc cai"
    }
}

$vrInstalled = $false
$vrSvc = $null
if (-not $SkipVelociraptor) {
    $vrExisting = Get-WmiObject -Class Win32_Product -Filter "Name='Velociraptor Service Installer'" -ErrorAction SilentlyContinue
    if ($vrExisting) {
        $vrInstalled = $true
        $vrSvc = Get-Service -Name "Velociraptor" -ErrorAction SilentlyContinue
        if (-not $vrSvc) { $vrSvc = Get-Service | Where-Object { $_.DisplayName -like "*Velociraptor*" } | Select-Object -First 1 }
        Write-Info "Velociraptor da cai (v$($vrExisting.Version))"
        if ($vrSvc) {
            Write-Info "  Service: $($vrSvc.Status)"
        } else {
            Write-Warn "  Service khong chay (se khoi dong lai)"
        }
    } else {
        Write-Info "Velociraptor chua duoc cai"
    }
}

# ── 3. Exclusion Defender ──────────────────────────────────────────────
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
    Write-Info "Tai $Label tu $Url ..."
    Invoke-WebRequest -Uri $Url -OutFile $OutPath -UseBasicParsing -TimeoutSec 120
    Unblock-File -Path $OutPath -ErrorAction SilentlyContinue
    $size = [math]::Round((Get-Item $OutPath).Length / 1MB, 2)
    Write-Ok "$Label da tai ($size MB)"
}

# ── 4. OrgInventory Agent ──────────────────────────────────────────────
if (-not $SkipOrgInventory) {
    Write-Step "[2/5] Cai dat / cap nhat OrgInventory Agent..."

    # === Case 1: Chua cai → cai MSI moi ===
    if (-not $oiInstalled -or $ForceReinstall) {
        if ($ForceReinstall -and $oiInstalled) {
            Write-Info "ForceReinstall = true → go MSI cu truoc..."
            try {
                $oiExisting.Uninstall() | Out-Null
                Start-Sleep -Seconds 5
                Write-Ok "Đã gỡ OrgInventory Agent cũ"
            } catch {
                Write-Warn "Loi khi go: $($_.Exception.Message)"
            }
        }

        $msiPath = Join-Path $TmpDir "OrgInventoryAgent.msi"
        try { Download-File $OrgInventoryMsiUrl $msiPath "OrgInventoryAgent.msi" } catch {
            Write-Fail "Khong tai duoc MSI: $($_.Exception.Message)"; exit 1
        }

        # Verify SHA256
        try {
            $expected = (Invoke-WebRequest -Uri "$PortalUrl/download/agent.msi.sha256" -UseBasicParsing -TimeoutSec 30).Content.Trim().Split()[0]
            $actual = (Get-FileHash -Path $msiPath -Algorithm SHA256).Hash.ToLower()
            if ($expected.ToLower() -ne $actual) {
                Write-Fail "SHA256 khong khop (server: $expected, file: $actual) — dung cai dat."
                exit 1
            }
            Write-Ok "SHA256 khop"
        } catch {
            Write-Warn "Khong verify duoc SHA256: $($_.Exception.Message)"
        }

        # Verify chu ky Authenticode
        $sig = Get-AuthenticodeSignature -FilePath $msiPath
        $allowUnsigned = ($env:ORGINV_ALLOW_UNSIGNED -eq '1')
        if ($sig.Status -ne 'Valid' -and -not $allowUnsigned) {
            Write-Fail "Chu ky so khong hop le (Status: $($sig.Status))"
            Remove-Item $msiPath -Force -ErrorAction SilentlyContinue
            exit 1
        }
        if ($sig.Status -eq 'Valid') { Write-Ok "Chu ky hop le: $($sig.SignerCertificate.Subject)" }
        else { Write-Warn "MSI khong ky Authenticode — bo qua vi ORGINV_ALLOW_UNSIGNED=1 (TEST mode)" }

        # msiexec
        Write-Info "Chay msiexec /qn (silent install, ENROLL_TOKEN + ENDPOINTS)..."
        $argsList = @('/i', "`"$msiPath`"", '/qn', '/norestart', "ENROLL_TOKEN=$Token", "TOKEN=$Token", "ENDPOINTS=$Endpoint", '/L*V', "`"$InstallLog`"")
        $p = Start-Process msiexec.exe -ArgumentList $argsList -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            Write-Fail "msiexec that bai (exit=$($p.ExitCode)). Log: $InstallLog"
            Get-Content $InstallLog -Tail 30 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkYellow }
            exit $p.ExitCode
        }
        Write-Ok "MSI da cai dat thanh cong"
    }

    # === Case 2: Da cai → chi UPDATE config.json ===
    else {
        Write-Info "OrgInventory Agent da cai → chi UPDATE config.json (KHONG go MSI)"
        $cfgPath = "$env:ProgramData\OrgInventory\config.json"
        if (-not (Test-Path $cfgPath)) {
            # Tao moi neu chua co
            $cfgDir = Split-Path $cfgPath
            if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null }
        }

        # Đọc config cũ (nếu có)
        $cfg = @{}
        if (Test-Path $cfgPath) {
            try { $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch { $cfg = @{} }
        }
        $oldToken = $cfg.token
        $oldEndpoints = $cfg.endpoints
        Write-Info "Config cu: token=$($oldToken.Substring(0, [Math]::Min(8, $oldToken.Length)))..., endpoints=$oldEndpoints"

        # Update config.json
        $cfg.token = $Token
        $cfg.endpoints = @($Endpoint)
        $cfg.configVersion = 2  # Bump version de agent biet config da thay doi

        $cfgJson = $cfg | ConvertTo-Json -Depth 5
        $cfgJson | Set-Content -Path $cfgPath -Encoding UTF8 -Force
        Write-Ok "Config da update: token moi, endpoints=$Endpoint"

        # Restart service de agent doc config moi
        if (-not $oiSvc) {
            $oiSvc = Get-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
        }
        if ($oiSvc) {
            Write-Info "Restart service OrgInventoryAgent de doc config moi..."
            try {
                Stop-Service -Name "OrgInventoryAgent" -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
                Start-Service -Name "OrgInventoryAgent" -ErrorAction Stop
                Start-Sleep -Seconds 2
                $oiSvc.Refresh()
                Write-Ok "Service da restart: $($oiSvc.Status)"
            } catch {
                Write-Warn "Khong the restart service: $($_.Exception.Message)"
            }
        } else {
            Write-Fail "Khong tim thay service OrgInventoryAgent sau khi update config"
            exit 1
        }
    }
}

# ── 5. Velociraptor Client ─────────────────────────────────────────────
if (-not $SkipVelociraptor) {
    Write-Step "[3/5] Cai dat / cap nhat Velociraptor Client..."

    # === Case 1: Chua cai → cai MSI moi ===
    if (-not $vrInstalled -or $ForceReinstall) {
        if ($ForceReinstall -and $vrInstalled) {
            Write-Info "ForceReinstall = true → go MSI cu truoc..."
            try {
                $vrExisting.Uninstall() | Out-Null
                Start-Sleep -Seconds 3
                Write-Ok "Đã g� Velociraptor cũ"
            } catch {
                Write-Warn "Loi khi go: $($_.Exception.Message)"
            }
        }

        $vrMsi = Join-Path $TmpDir "velociraptor-windows-amd64.msi"
        try { Download-File $VelociraptorMsiUrl $vrMsi "Velociraptor MSI" } catch {
            Write-Fail "Khong tai duoc MSI: $($_.Exception.Message)"; exit 1
        }

        # msiexec
        Write-Info "Chay msiexec /qn..."
        $argsList = @('/i', "`"$vrMsi`"", '/qn', '/norestart', '/L*V', "`"$InstallLog`"")
        $p = Start-Process msiexec.exe -ArgumentList $argsList -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            Write-Fail "msiexec that bai (exit=$($p.ExitCode)). Log: $InstallLog"
            exit $p.ExitCode
        }
        Write-Ok "MSI da cai dat thanh cong"
    }

    # === Case 2: Da cai → chi UPDATE client.config.yaml ===
    $vrDir = Join-Path $env:ProgramFiles "Velociraptor"
    $cfgDst = Join-Path $vrDir "client.config.yaml"
    if (-not (Test-Path $vrDir)) {
        Write-Fail "Khong thay thu muc $vrDir (Velociraptor MSI loi?)"
        exit 1
    }

    if ($vrInstalled -and -not $ForceReinstall) {
        Write-Info "Velociraptor da cai → chi UPDATE client.config.yaml (KHONG go MSI)"
        $oldCfg = Get-Content $cfgDst -Raw -ErrorAction SilentlyContinue
        if ($oldCfg -match "server_urls:") {
            $oldUrls = ($oldCfg -split "`n" | Select-String -Pattern "server_urls:" -Context 0,2).ToString()
            Write-Info "Config cu co server_urls"
        }
    }

    # Smart Update: dùng ZIP config-only (~2KB) thay vì URL riêng
    if ($vrUseConfigOnly) {
        $vrZip = Join-Path $TmpDir "velociraptor-config.zip"
        try { Download-File $VelociraptorConfigOnlyZipUrl $vrZip "Velociraptor config (2KB)" } catch {
            # Fallback URL riêng nếu ZIP fail
            Write-Warn "Config-only ZIP fail, fallback download URL rieng"
            $vrCfg = Join-Path $TmpDir "client.config.yaml"
            try { Download-File $VelociraptorConfigUrl $vrCfg "client.config.yaml" } catch {
                Write-Fail "Khong tai duoc config: $($_.Exception.Message)"; exit 1
            }
            Copy-Item -Path $vrCfg -Destination $cfgDst -Force
            Write-Ok "Config da ghi de: $cfgDst"
            $vrZip = $null
        }
        if ($vrZip -and (Test-Path $vrZip)) {
            # Extract client.config.yaml từ ZIP
            $shell = New-Object -ComObject Shell.Application
            $zipNs = $shell.NameSpace((Resolve-Path $vrZip).Path)
            $cfgItem = $zipNs.Items() | Where-Object { $_.Name -eq "client.config.yaml" }
            if ($cfgItem) {
                $extractDir = Join-Path $TmpDir "extracted"
                New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
                $zipNs.CopyHere($cfgItem, 0x14)  # 0x14 = silent + overwrite
                $extractedCfg = Join-Path $extractDir "client.config.yaml"
                if (Test-Path $extractedCfg) {
                    Copy-Item -Path $extractedCfg -Destination $cfgDst -Force
                    Write-Ok "Config (tu ZIP) da ghi de: $cfgDst"
                } else {
                    Write-Fail "Khong extract duoc client.config.yaml tu ZIP"
                    exit 1
                }
            } else {
                Write-Fail "ZIP khong chua client.config.yaml"
                exit 1
            }
        }
    } else {
        # First install: dùng URL riêng
        $vrCfg = Join-Path $TmpDir "client.config.yaml"
        try { Download-File $VelociraptorConfigUrl $vrCfg "client.config.yaml" } catch {
            Write-Fail "Khong tai duoc config: $($_.Exception.Message)"; exit 1
        }
        Copy-Item -Path $vrCfg -Destination $cfgDst -Force
        Write-Ok "Config da ghi de: $cfgDst"
    }

    # Restart service de Velociraptor doc config moi (server_urls)
    if (-not $vrSvc) {
        $vrSvc = Get-Service -Name "Velociraptor" -ErrorAction SilentlyContinue
        if (-not $vrSvc) { $vrSvc = Get-Service | Where-Object { $_.DisplayName -like "*Velociraptor*" } | Select-Object -First 1 }
    }
    if ($vrSvc) {
        Write-Info "Restart service Velociraptor de doc config moi..."
        try {
            Stop-Service -Name $vrSvc.Name -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            Start-Service -Name $vrSvc.Name -ErrorAction Stop
            Start-Sleep -Seconds 3
            $vrSvc.Refresh()
            Write-Ok "Service da restart: $($vrSvc.Status)"
        } catch {
            Write-Warn "Khong the restart service: $($_.Exception.Message)"
        }
    } else {
        Write-Fail "Khong tim thay service Velociraptor"
        exit 1
    }
}

# ── 6. Verify cuoi cung ─────────────────────────────────────────────────
Write-Step "[4/5] Verify cuoi cung..."
Start-Sleep -Seconds 5

$allOk = $true
if (-not $SkipOrgInventory) {
    $oi = Get-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
    if ($oi -and $oi.Status -eq "Running") {
        Write-Ok "OrgInventoryAgent: $($oi.Status)"
    } else {
        Write-Fail "OrgInventoryAgent: $($oi.Status)"
        $allOk = $false
    }
}
if (-not $SkipVelociraptor) {
    $vr = Get-Service -Name "Velociraptor" -ErrorAction SilentlyContinue
    if (-not $vr) { $vr = Get-Service | Where-Object { $_.DisplayName -like "*Velociraptor*" } | Select-Object -First 1 }
    if ($vr -and $vr.Status -eq "Running") {
        Write-Ok "Velociraptor ($($vr.Name)): $($vr.Status)"
    } else {
        Write-Fail "Velociraptor: $($vr.Status)"
        $allOk = $false
    }
}

# ── 7. Hoan tat ────────────────────────────────────────────────────────
Write-Step "[5/5] Hoan tat"
Write-Host ""
if ($allOk) {
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "  TAT CA AGENT DANG CHAY THANH CONG!" -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  - OrgInventory: log: $env:ProgramData\OrgInventory\logs\agent.log" -ForegroundColor White
    Write-Host "  - Velociraptor:  log: $env:ProgramFiles\Velociraptor\logs\velociraptor.log" -ForegroundColor White
    Write-Host ""
    Write-Host "Verify enroll (~30s):" -ForegroundColor Yellow
    Write-Host "  Portal:    Tab Machines → may moi sau ~1 phut" -ForegroundColor Gray
    Write-Host "  Velociraptor GUI: https://10.10.0.241:8889 → tab Clients" -ForegroundColor Gray
    exit 0
} else {
    Write-Host "==========================================================" -ForegroundColor Yellow
    Write-Host "  CAI DAT HOAN TAT NHUNG CO LOI O 1 SO SERVICE" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Yellow
    Write-Host "  Kiem tra log va service de biet them chi tiet" -ForegroundColor Yellow
    exit 1
}
Write-Host ""
