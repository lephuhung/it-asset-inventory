@echo off
:: IT Asset Inventory — Launcher 1-Click cho may cach ly (Offline USB)
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ===================================================================
echo   HE THONG IT ASSET INVENTORY - BO THU THAP TAI SAN (OFFLINE)
echo ===================================================================
echo.
echo Dang khoi chay tien trinh thu thap va dong goi du lieu...

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-offline.ps1"
set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE% equ 0 (
    echo ===================================================================
    echo [OK] DA HOAN TAT THU THAP DU LIEU!
    echo Vui long rut USB va chuyen file ZIP cho Quan tri vien he thong.
    echo ===================================================================
) else (
    echo ===================================================================
    echo [LOI] Co loi xay ra trong qua trinh thuc hien (Exit Code: %EXIT_CODE%).
    echo Vui long kiem tra lai quyen Administrator hoac lien he Quan tri vien.
    echo ===================================================================
)

echo.
echo Nhan phim bat ky de thoat...
pause >nul
