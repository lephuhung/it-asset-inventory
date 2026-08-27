@echo off
chcp 65001 >nul
title Cài đặt OrgInventory Agent

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-agent.ps1" %*

pause
