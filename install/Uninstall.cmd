@echo off
setlocal
chcp 65001 >nul
title Codex Auto Resume - uninstall
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" -Uninstall %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
