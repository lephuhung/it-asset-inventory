<#
.SYNOPSIS
  Tao chung chi Code Signing noi bo (self-signed) cho Phong ANM & PCTP su dung CNC,
  cai vao Trusted Root & Trusted Publishers tren may tram, va ky so Authenticode cho MSI / EXE.

.DESCRIPTION
  Giup ngan chan hoan toan cac canh bao False Positive tu Windows Defender / SmartScreen
  trong mang noi bo khi chua co chung chi Code Signing thuong mai (DigiCert/Sectigo).

.EXAMPLE
  .\create-codesign-cert.ps1 -SignFile "OrgInventoryAgent.msi"
#>
[CmdletBinding()]
param(
    [string]$SignFile = ""
)

# 1. Kiem tra chung chi da ton tai trong Cert:\CurrentUser\My chua
$certName = "CN=OrgInventory Code Signing - Cong an tinh Ha Tinh"
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $certName -and $_.NotAfter -gt (Get-Date) } | Select-Object -First 1

if (-not $cert) {
    Write-Host "Tao chung chi Code Signing noi bo moi..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate `
        -Subject $certName `
        -Type CodeSigningCert `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -NotAfter (Get-Date).AddYears(5) `
        -HashAlgorithm "SHA256" `
        -KeyLength 2048

    Write-Host "Da tao chung chi: $($cert.Thumbprint)" -ForegroundColor Green
    
    # Cai dat vao Trusted Root Certification Authorities va Trusted Publishers (CurrentUser)
    $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
    $rootStore.Open("ReadWrite")
    $rootStore.Add($cert)
    $rootStore.Close()

    $pubStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPublisher", "CurrentUser")
    $pubStore.Open("ReadWrite")
    $pubStore.Add($cert)
    $pubStore.Close()
    Write-Host "Da them vao Trusted Root va Trusted Publisher (CurrentUser)." -ForegroundColor Green
} else {
    Write-Host "Tim thay chung chi Code Signing: $($cert.Thumbprint)" -ForegroundColor Green
}

# 2. Ky file neu duoc chi dinh
if ($SignFile -and (Test-Path $SignFile)) {
    Write-Host "Dang ky Authenticode cho: $SignFile..." -ForegroundColor Cyan
    try {
        Set-AuthenticodeSignature -FilePath $SignFile -Certificate $cert -HashAlgorithm "SHA256"
        Write-Host "Ky thanh cong!" -ForegroundColor Green
    } catch {
        Write-Host "Loi khi ky: $_" -ForegroundColor Red
    }
}

return $cert.Thumbprint
