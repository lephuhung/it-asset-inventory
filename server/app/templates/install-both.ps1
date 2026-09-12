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

    - Neu OrgInventory chua cai (HOAC server co ban moi hon) -> chay MSI
    - Neu OrgInventory da cai, da la ban moi nhat -> chi UPDATE config.json
      (endpoints; GIU identity) + restart service — KHONG re-enroll ngam dinh
    - Tuong tu cho Velociraptor -> chi UPDATE client.config.yaml

    ForceReinstall (optional): go + cai lai MSI (chi dung khi MSI bi loi)
    Reenroll (optional): XOA identity (enrolled/machineId/thumbprint) + nap token moi
      -> agent enroll lai. CHI dung khi can re-bind may (cert mat vinh vien, doi org...).

  CONTRACT CHUNG (Windows + Linux, giong install.sh):
    Update endpoint/config KHONG DUOC lam mat identity. Khi agent da cai:
      - endpoints LUON duoc update.
      - enrolled / machineId / clientCertThumbprint GIU NGUYEN (khong re-enroll,
        khong dot token da dung -> tranh 401 loop).
      - token chi duoc nap khi may CHUA enroll (hoac config dang ReenrollRequired
        cho token moi). Chi -Reenroll moi rotate identity.

  Luong xu ly:
    [1] Kiem tra quyen Administrator
    [2] Detect trang thai 2 agent (Installed? Service Running?)
    [3] OrgInventory: neu chua cai -> cai MSI; neu da cai -> update config.json (giu identity)
    [4] Velociraptor: neu chua cai -> cai MSI; neu da cai -> update client.config.yaml
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
    [switch]$ForceReinstall,  # GO MSI + cai lai (chi dung khi MSI loi) — KHONG doi identity
    [switch]$Reenroll         # EXPLICIT re-enroll: xoa identity + nap token moi
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Msg) { Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "      [OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "      [WARN] $Msg" -ForegroundColor Yellow }
function Write-Fail([string]$Msg) { Write-Host "      [FAIL] $Msg" -ForegroundColor Red }
function Write-Info([string]$Msg) { Write-Host "      [INFO] $Msg" -ForegroundColor Gray }

function Get-MsiProductCode([string]$NamePattern) {
    # Tra ve { ProductCode, DisplayVersion } cua san pham MSI khop DisplayName — doc
    # registry Uninstall key. KHONG dung Get-WmiObject Win32_Product: query do
    # revalidate (co khi repair) TAT CA cac san pham MSI tren may va rat cham.
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($p in $paths) {
        $item = Get-ItemProperty $p -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like $NamePattern -and $_.PSChildName -match '^\{[0-9A-Fa-f\-]+\}$' } |
            Select-Object -First 1
        if ($item) {
            return [pscustomobject]@{
                ProductCode    = $item.PSChildName
                DisplayVersion = $item.DisplayVersion
            }
        }
    }
    return $null
}

function Test-VersionNewer([string]$Current, [string]$Available) {
    # So sánh semantic version 3 số (1.2.0). Trả true nếu Available > Current.
    # Dữ liệu thiếu/không parse được → false (giữ nguyên trạng thái, an toàn).
    if (-not $Current -or -not $Available) { return $false }
    try {
        $c = [version]$Current
        $a = [version]$Available
        return ($a -gt $c)
    } catch {
        return $false
    }
}

function Get-AgentVersionManifest {
    # Manifest phiên bản từ server (/download/agent-version) — null khi không fetch được
    # (server cũ chưa có endpoint, mạng lỗi...) → script giữ hành vi cũ, không nâng cấp.
    try {
        return Invoke-RestMethod -Uri "$PortalUrl/download/agent-version" -UseBasicParsing -TimeoutSec 30
    } catch {
        Write-Info "Khong doc duoc manifest phien ban ($PortalUrl/download/agent-version) — bo qua buoc kiem tra nang cap."
        return $null
    }
}

function Reset-OiIdentityForReenroll([string]$NewToken) {
    # Rotate identity EXPLICIT (-Reenroll): xoá enrolled/machineId/thumbprint trong
    # config.json + nạp token mới → agent enroll lại. Dùng sau khi MSI chạy xong
    # (Case 1) — MSI chỉ ghi registry bootstrap, config.json giữ identity cũ.
    $cfgPath = "$env:ProgramData\OrgInventory\config.json"
    $cfgDir = Split-Path $cfgPath
    if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null }
    $cfgObj = $null
    if (Test-Path $cfgPath) {
        try { $cfgObj = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch { }
    }
    $cfgDict = [ordered]@{}
    if ($cfgObj) {
        foreach ($prop in $cfgObj.PSObject.Properties) { $cfgDict[$prop.Name] = $prop.Value }
    }
    $cfgDict["token"] = $NewToken
    $cfgDict["enrolled"] = $false
    $cfgDict["machineId"] = $null
    $cfgDict["clientCertThumbprint"] = $null
    $cfgDict["certStoreLocation"] = $null
    $cfgDict["reenrollRequired"] = $false
    $cfgDict | ConvertTo-Json -Depth 5 | Set-Content -Path $cfgPath -Encoding UTF8 -Force
}

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
        $relaunchArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Token `"$Token`" -PortalUrl `"$PortalUrl`" -Endpoint `"$Endpoint`""
        if ($Reenroll) { $relaunchArgs += " -Reenroll" }
        Start-Process powershell.exe -Verb RunAs -ArgumentList $relaunchArgs
        exit 0
    }
    Write-Fail "Can chay PowerShell voi quyen Administrator."
    exit 1
}

# ── 2. Detect trang thai 2 agent ────────────────────────────────────────
Write-Step "[1/5] Kiem tra trang thai agent hien tai..."

$oiInstalled = $false
$oiSvc = $null
$oiProductCode = $null
$oiInstalledVersion = $null
if (-not $SkipOrgInventory) {
    $oiSvc = Get-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
    $oiInfo = Get-MsiProductCode "*OrgInventory*"
    $oiProductCode = if ($oiInfo) { $oiInfo.ProductCode } else { $null }
    $oiInstalledVersion = if ($oiInfo) { $oiInfo.DisplayVersion } else { $null }
    if ($oiSvc -or $oiProductCode -or (Test-Path "$env:ProgramFiles\OrgInventory\OrgInventoryAgent.exe")) {
        $oiInstalled = $true
        Write-Info "OrgInventory Agent da cai $(if ($oiInstalledVersion) { "v$oiInstalledVersion" })$(if ($oiProductCode) { " (MSI $oiProductCode)" })"
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
$vrProductCode = $null
if (-not $SkipVelociraptor) {
    $vrInfo = Get-MsiProductCode "*Velociraptor*"
    $vrProductCode = if ($vrInfo) { $vrInfo.ProductCode } else { $null }
    $vrSvc = Get-Service -Name "Velociraptor" -ErrorAction SilentlyContinue
    if (-not $vrSvc) { $vrSvc = Get-Service | Where-Object { $_.DisplayName -like "*Velociraptor*" } | Select-Object -First 1 }
    if ($vrProductCode -or $vrSvc -or (Test-Path "$env:ProgramFiles\Velociraptor\velociraptor.exe")) {
        $vrInstalled = $true
        Write-Info "Velociraptor da cai$(if ($vrProductCode) { " (MSI $vrProductCode)" })"
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

    # === Case 1: Chua cai HOAC co ban moi hon -> chay MSI ===
    $oiManifest = $null
    $oiUpgradeAvailable = $false
    if ($oiInstalled) {
        $oiManifest = Get-AgentVersionManifest
        if ($oiManifest -and $oiManifest.msi_version) {
            $oiUpgradeAvailable = Test-VersionNewer -Current $oiInstalledVersion -Available $oiManifest.msi_version
            if ($oiUpgradeAvailable) {
                Write-Info "Co phien ban moi: v$oiInstalledVersion -> v$($oiManifest.msi_version) — se nang cap bang MSI (giu nguyen enrollment)."
            }
        }
    }

    if (-not $oiInstalled -or $ForceReinstall -or $oiUpgradeAvailable) {
        if ($ForceReinstall -and $oiInstalled) {
            Write-Info "ForceReinstall = true -> go MSI cu truoc..."
            if ($oiProductCode) {
                Start-Process msiexec.exe -ArgumentList @('/x', "$oiProductCode", '/qn', '/norestart') -Wait
                Start-Sleep -Seconds 5
                Write-Ok "Da go OrgInventory Agent cu"
            } else {
                Write-Warn "Khong tim thay product code MSI cu — bo qua buoc go (msiexec /i se tu nang cap qua MajorUpgrade)"
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
                Write-Fail "SHA256 khong khop (server: $expected, file: $actual) - dung cai dat."
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
        else { Write-Warn "MSI khong ky Authenticode - bo qua vi ORGINV_ALLOW_UNSIGNED=1 (TEST mode)" }

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

        if ($Reenroll) {
            # -Reenroll + MSI (Case 1): MSI giữ config.json cũ (identity cũ) — phải
            # xoá identity + nạp token mới để agent enroll lại như admin yêu cầu.
            Write-Warn "-Reenroll: xoa identity trong config.json — agent se enroll lai voi token moi."
            Reset-OiIdentityForReenroll $Token
            Stop-Service -Name "OrgInventoryAgent" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            Start-Service -Name "OrgInventoryAgent" -ErrorAction SilentlyContinue
        }
    }

    # === Case 2: Da cai (khong co ban moi hon) -> UPDATE endpoint/config, GIU identity ===
    # Contract chung (Windows + Linux): update endpoint KHONG duoc lam mat identity.
    #   - endpoints: LUON update.
    #   - enrolled/machineId/clientCertThumbprint: GIU NGUYEN (khong re-enroll ngam dinh).
    #   - token: chi nap khi may CHUA enroll hoac dang ReenrollRequired cho token moi.
    #     Chi -Reenroll (explicit) moi rotate identity.
    else {
        Write-Info "OrgInventory Agent da cai -> UPDATE config.json (GIU identity, KHONG go MSI)"
        $cfgPath = "$env:ProgramData\OrgInventory\config.json"
        if (-not (Test-Path $cfgPath)) {
            # Tao moi neu chua co
            $cfgDir = Split-Path $cfgPath
            if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null }
        }

        # Đọc config cũ (nếu có)
        $cfgObj = $null
        if (Test-Path $cfgPath) {
            try { $cfgObj = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch { }
        }
        $oldEndpoints = if ($cfgObj -and $cfgObj.endpoints) { $cfgObj.endpoints -join ", " } else { "" }
        $wasEnrolled = [bool]($cfgObj -and $cfgObj.enrolled)
        $wasReenrollRequired = [bool]($cfgObj -and $cfgObj.reenrollRequired)
        Write-Info "Config cu: enrolled=$wasEnrolled, machineId=$(if ($cfgObj -and $cfgObj.machineId) { $cfgObj.machineId } else { '(chua co)' }), endpoints=$oldEndpoints"

        # Update config.json (bao toan cac truong cu)
        $cfgDict = [ordered]@{}
        if ($cfgObj) {
            foreach ($prop in $cfgObj.PSObject.Properties) {
                $cfgDict[$prop.Name] = $prop.Value
            }
        }
        $cfgDict["endpoints"] = @($Endpoint)
        $cfgDict["configVersion"] = 2

        if ($Reenroll) {
            # EXPLICIT re-enroll: rotate identity — agent se enroll lai voi token moi.
            if (-not $Token) {
                Write-Fail "-Reenroll can token moi (tham so -Token). Khong doi identity."
                exit 1
            }
            Write-Warn "-Reenroll: XOA identity (enrolled/machineId/thumbprint) + nap token moi — agent se enroll lai."
            $cfgDict["token"] = $Token
            $cfgDict["enrolled"] = $false
            $cfgDict["machineId"] = $null
            $cfgDict["clientCertThumbprint"] = $null
            $cfgDict["certStoreLocation"] = $null
            $cfgDict["reenrollRequired"] = $false
        } elseif ($wasEnrolled) {
            # Da enroll: giu identity, KHONG nap token (token cu da bi agent xoa sau
            # enroll — AG-P2-01; nap token DA DUNG vao config se gay 401 loop im lặng).
            if ($null -ne $cfgDict["token"]) { $cfgDict.Remove("token") }
            Write-Ok "Da enroll — giu nguyen identity, chi update endpoints=$Endpoint (khong re-enroll)."
        } else {
            # Chua enroll (cai lan truoc fail enroll, hoac ReenrollRequired cho token moi)
            # → nap token de agent tu enroll; server fuzzy-match se ghép lai may cu.
            $cfgDict["token"] = $Token
            if ($wasReenrollRequired) {
                Write-Info "Config dang ReenrollRequired — da nap token moi de agent enroll lai."
            }
        }

        $cfgJson = $cfgDict | ConvertTo-Json -Depth 5
        $cfgJson | Set-Content -Path $cfgPath -Encoding UTF8 -Force
        Write-Ok "Config da update: endpoints=$Endpoint (identity: $(if ($wasEnrolled -and -not $Reenroll) { 'giu nguyen' } elseif ($Reenroll) { 'da rotate (-Reenroll)' } else { 'cho enroll moi' }))."

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

    # === Case 1: Chua cai / co ban moi hon / -ForceReinstall -> cai MSI moi ===
    $vrUpgradeAvailable = $false
    if ($vrInstalled -and -not $ForceReinstall) {
        $vrManifest = Get-AgentVersionManifest
        if ($vrManifest -and $vrManifest.velociraptor_msi_version) {
            # Velociraptor MSI khong ghi UpgradeCode duoc theo doi qua registry rang —
            # chi so sanh khi doc duoc DisplayVersion; khong co thi khong nang cap.
            $vrInfo = Get-MsiProductCode "*Velociraptor*"
            if ($vrInfo -and $vrInfo.DisplayVersion) {
                $vrUpgradeAvailable = Test-VersionNewer -Current $vrInfo.DisplayVersion -Available $vrManifest.velociraptor_msi_version
                if ($vrUpgradeAvailable) {
                    Write-Info "Velociraptor co phien ban moi: v$($vrInfo.DisplayVersion) -> v$($vrManifest.velociraptor_msi_version)."
                }
            }
        }
    }

    if (-not $vrInstalled -or $ForceReinstall -or $vrUpgradeAvailable) {
        if ($ForceReinstall -and $vrInstalled) {
            Write-Info "ForceReinstall = true -> go MSI cu truoc..."
            if ($vrProductCode) {
                Start-Process msiexec.exe -ArgumentList @('/x', "$vrProductCode", '/qn', '/norestart') -Wait
                Start-Sleep -Seconds 3
                Write-Ok "Da go Velociraptor cu"
            } else {
                Write-Warn "Khong tim thay product code MSI Velociraptor cu — bo qua buoc go"
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

    # === Case 2: Da cai -> chi UPDATE client.config.yaml ===
    $vrDir = Join-Path $env:ProgramFiles "Velociraptor"
    $cfgDst = Join-Path $vrDir "client.config.yaml"
    if (-not (Test-Path $vrDir)) {
        Write-Fail "Khong thay thu muc $vrDir (Velociraptor MSI loi?)"
        exit 1
    }

    if ($vrInstalled -and -not $ForceReinstall) {
        Write-Info "Velociraptor da cai -> chi UPDATE client.config.yaml (KHONG go MSI)"
        $oldCfg = Get-Content $cfgDst -Raw -ErrorAction SilentlyContinue
        if ($oldCfg -match "server_urls:") {
            $oldUrls = ($oldCfg -split "`n" | Select-String -Pattern "server_urls:" -Context 0,2).ToString()
            Write-Info "Config cu co server_urls"
        }
    }

    # Smart Update: máy ĐÃ cài (không force, không nâng cấp) → dùng ZIP config-only (~2KB)
    $vrUseConfigOnly = ($vrInstalled -and -not $ForceReinstall -and -not $vrUpgradeAvailable)
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
    Write-Host "  Portal:    Tab Machines -> may moi sau ~1 phut" -ForegroundColor Gray
    Write-Host "  Velociraptor GUI: https://10.10.0.241:8889 -> tab Clients" -ForegroundColor Gray
    exit 0
} else {
    Write-Host "==========================================================" -ForegroundColor Yellow
    Write-Host "  CAI DAT HOAN TAT NHUNG CO LOI O 1 SO SERVICE" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Yellow
    Write-Host "  Kiem tra log va service de biet them chi tiet" -ForegroundColor Yellow
    exit 1
}
Write-Host ""
