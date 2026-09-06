@echo off
setlocal
chcp 65001 >nul
title Codex Auto Resume - installer
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Installation did not finish. Read the messages above.
pause
exit /b %EXIT_CODE%
