@echo off
setlocal
rem The console's code page as it was, put back before this ends: setlocal does not restore it, and a window the person
rem ran this from would stay in 65001. (chcp prints "Active code page: 437" in the console's language; the number is
rem after the colon, and some languages end it with a full stop.)
set "OLDCP="
for /f "tokens=2 delims=:." %%C in ('"%SystemRoot%\System32\chcp.com"') do set "OLDCP=%%C"
if defined OLDCP set "OLDCP=%OLDCP: =%"
"%SystemRoot%\System32\chcp.com" 65001 >nul
title Codex Auto Resume - uninstall
rem -Silent (winget, a script): nothing waits for a key. It is passed on to install.ps1 with the rest.
set "SILENT="
for %%A in (%*) do if /i "%%~A"=="-Silent" set "SILENT=1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" -Uninstall %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not defined SILENT pause
if defined OLDCP "%SystemRoot%\System32\chcp.com" %OLDCP% >nul
exit /b %EXIT_CODE%
