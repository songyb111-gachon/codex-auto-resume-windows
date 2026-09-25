@echo off
setlocal
"%SystemRoot%\System32\chcp.com" 65001 >nul
title Codex Auto Resume - install
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Installation did not finish. Read the messages above.
pause
exit /b %EXIT_CODE%
