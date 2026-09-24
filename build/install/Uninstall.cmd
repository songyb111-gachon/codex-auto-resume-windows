@echo off
setlocal
"%SystemRoot%\System32\chcp.com" 65001 >nul
title Codex Auto Resume - uninstall
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" -Uninstall %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
