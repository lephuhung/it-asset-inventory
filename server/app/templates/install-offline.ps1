# install-offline.ps1 — wrapper cài agent trên máy cách ly (KHÔNG cần mạng ra server).
#
# Yêu cầu:
#   - PowerShell 5.1+ (Windows 10/11)
#   - Quyền Administrator
#   - USB chứa 3 file trong cùng thư mục:
#       1. OrgInventoryAgent.msi          (do admin build trên Windows + ký Authenticode)
#       2. OrgInventoryAgent.msi.sha256   (do build script sinh ra, cùng thư mục với MSI)
#       3. install-offline.ps1            (file này)
#   - Có sẵn:
#       $token      Enroll token (do admin cấp qua /api/tokens)
#       $endpoints  URL server agent, ví dụ "https://agent.example.gov.vn"
#                   (Phase 1 chỉ dùng URL chính; backup endpoint đặt trong config sau)
#
# Ví dụ:
#   .\install-offline.ps1 -Token "t_Ab3xK9mQ2vR8nL4p" -Endpoints "https://agent.example.gov.vn"
#
# Hoặc nhập tương tác nếu không truyền -Token / -Endpoints.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)] [string]$Token,
    [Parameter(Mandatory=$false)] [string]$Endpoints,
    [Parameter(Mandatory=$false)] [string]$MsiDir = (Split-Path -Parent $MyInvocation.MyCommand.Definition),
    [switch]$SkipConfirm  # Bỏ qua bước xác nhận tuân thủ (cho CI / triển khai silent)
)

$ErrorActionPreference = 'Stop'
$msiName  = 'OrgInventoryAgent.msi'
$shaName  = 'OrgInventoryAgent.msi.sha256'
$msiPath  = Join-Path $MsiDir $msiName
$shaPath  = Join-Path $MsiDir $shaName
$logPath  = Join-Path $env:TEMP 'agent-install-offline.log'

Write-Host ''
Write-Host '=== IT ASSET INVENTORY — CÀI ĐẶT AGENT (OFFLINE / MÁY CÁCH LY) ===' -ForegroundColor Cyan
Write-Host ''

# 1. Quyền Admin
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[LỖI] Cần chạy PowerShell với quyền Administrator.' -ForegroundColor Red
    Write-Host '       Chuột phải PowerShell → "Run as administrator", rồi chạy lại.' -ForegroundColor Yellow
    exit 1
}

# 2. Kiểm tra file trên USB
if (-not (Test-Path -LiteralPath $msiPath)) {
    Write-Host "[LỖI] Không thấy $msiPath. Kiểm tra USB + đường dẫn -MsiDir." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $shaPath)) {
    Write-Host "[CẢNH BÁO] Không thấy $shaPath — bỏ qua kiểm tra SHA256 (khuyến nghị: copy cả .sha256)." -ForegroundColor Yellow
} else {
    $expected = (Get-Content -LiteralPath $shaPath -Raw).Trim().Split(' ')[0].ToLower()
    $actual   = (Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) {
        Write-Host '[LỖI] SHA256 KHÔNG khớp — file có thể đã bị hỏng trên USB.' -ForegroundColor Red
        Write-Host "       Mong đợi: $expected" -ForegroundColor Red
        Write-Host "       Thực tế:  $actual" -ForegroundColor Red
        exit 1
    }
    Write-Host "[1/4] ✓ SHA256 khớp: $actual" -ForegroundColor Green
}

# 3. Verify Authenticode
Write-Host '[2/4] Xác thực chữ ký số (Authenticode) ...' -ForegroundColor Cyan
$sig = Get-AuthenticodeSignature -FilePath $msiPath
if ($sig.Status -ne 'Valid') {
    Write-Host "[LỖI] Chữ ký Authenticode không hợp lệ (Status: $($sig.Status)). Đã dừng cài đặt." -ForegroundColor Red
    exit 1
}
Write-Host "      ✓ Chữ ký hợp lệ: $($sig.SignerCertificate.Subject)" -ForegroundColor Green

# 4. Thông báo tuân thủ (mục 7.4 tài liệu gốc)
if (-not $SkipConfirm) {
    Write-Host '' -ForegroundColor White
    Write-Host 'Dữ liệu agent thu thập (chỉ đọc):' -ForegroundColor White
    Write-Host '  - Cấu hình máy: OS, CPU, RAM, ổ cứng, GPU, mainboard, BIOS' -ForegroundColor Gray
    Write-Host '  - Mạng: hostname, IP, MAC (phát hiện dual-homed)' -ForegroundColor Gray
    Write-Host '  - Phần mềm đã cài, trạng thái Antivirus / Windows Update' -ForegroundColor Gray
    Write-Host '  - User đang đăng nhập, trạng thái online/offline' -ForegroundColor Gray
    Write-Host 'KHÔNG thu thập: nội dung liên lạc, lịch sử web, phím gõ, ảnh màn hình.' -ForegroundColor Green
    Write-Host '' -ForegroundColor White
    Write-Host 'Nhấn Enter để tiếp tục (Ctrl+C để hủy).' -ForegroundColor Yellow
    Read-Host
}

# 5. Hỏi token + endpoints nếu chưa truyền
if (-not $Token) {
    $Token = Read-Host 'Nhập enroll token (do admin cấp, dạng t_xxxxxxxx)'
}
if (-not $Endpoints) {
    $Endpoints = Read-Host 'Nhập URL server agent (vd https://agent.example.gov.vn)'
}

# 6. Cài silent
Write-Host '[3/4] Cài đặt agent (silent) ...' -ForegroundColor Cyan
$args = @(
    '/i', "`"$msiPath`"",
    '/qn', '/norestart',
    "ENROLL_TOKEN=$Token",
    "ENDPOINTS=$Endpoints",
    '/L*V', "`"$logPath`""
)
$proc = Start-Process msiexec.exe -ArgumentList $args -Wait -PassThru -NoNewWindow

if ($proc.ExitCode -ne 0) {
    Write-Host "[LỖI] Cài đặt thất bại (exit code: $($proc.ExitCode)). Log: $logPath" -ForegroundColor Red
    exit 1
}

# 7. Hoàn tất + hướng dẫn bước tiếp theo cho máy cách ly
Write-Host '[4/4] Hoàn tất.' -ForegroundColor Cyan
Write-Host ''
Write-Host '✔ Cài đặt thành công!' -ForegroundColor Green
Write-Host ''
Write-Host '=== BƯỚC TIẾP THEO CHO MÁY CÁCH LY ===' -ForegroundColor Yellow
Write-Host 'Agent KHÔNG gửi được lên server (không có mạng). Để hoàn tất enroll + lấy cert:'
Write-Host ''
Write-Host '  1. Trên máy cách ly, mở PowerShell Admin → chạy:' -ForegroundColor White
Write-Host '       "C:\Program Files\OrgInventory\OrgInventoryAgent.exe" --enroll-offline E:\usb\enroll.json' -ForegroundColor Cyan
Write-Host '     (E: là ký tự USB — thay nếu khác)' -ForegroundColor Gray
Write-Host ''
Write-Host '  2. Cắm USB sang máy admin có mạng, POST file enroll.json lên server:' -ForegroundColor White
Write-Host '       POST /api/offline/enroll   (xem docs/RUNBOOK.md mục 6.2)' -ForegroundColor Cyan
Write-Host ''
Write-Host '  3. Copy file cert.json ngược về máy cách ly, cài cert:' -ForegroundColor White
Write-Host '       "C:\Program Files\OrgInventory\OrgInventoryAgent.exe" --install-cert E:\usb\cert.json' -ForegroundColor Cyan
Write-Host ''
Write-Host '  4. Sau khi cài cert, agent bắt đầu ghi inventory vào cache cục bộ.' -ForegroundColor White
Write-Host '     Định kỳ (tuần/tháng) chạy:' -ForegroundColor White
Write-Host '       "C:\Program Files\OrgInventory\OrgInventoryAgent.exe" --export-inventory E:\usb\inv-YYYYMMDD.json' -ForegroundColor Cyan
Write-Host '     Rồi POST file đó qua /api/offline/import (xem docs/RUNBOOK.md mục 6.4).' -ForegroundColor White
Write-Host ''
exit 0
