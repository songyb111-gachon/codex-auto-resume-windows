@echo off
setlocal
rem The console's code page as it was, put back before this ends: setlocal does not restore it, and a window the person
rem ran this from would stay in 65001. (chcp prints "Active code page: 437" in the console's language; the number is
rem after the colon, and some languages end it with a full stop.)
set "OLDCP="
for /f "tokens=2 delims=:." %%C in ('"%SystemRoot%\System32\chcp.com"') do set "OLDCP=%%C"
if defined OLDCP set "OLDCP=%OLDCP: =%"
"%SystemRoot%\System32\chcp.com" 65001 >nul
title Codex Auto Resume - install
rem -Silent (winget, a script): nothing is asked and nothing waits for a key. Every line, and
rem every exit code, is as it is without it; it is passed on to install.ps1 with the rest.
rem -DesktopShortcut adds a shortcut on the Desktop, and -NoDesktopShortcut removes this installation's; with neither,
rem as winget runs it, the Desktop is left as it is.
set "SILENT="
for %%A in (%*) do if /i "%%~A"=="-Silent" set "SILENT=1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
rem 14: this archive is the other edition from the one installed. The installer has said what
rem changing it keeps and what it changes, and changes it only when asked - so this asks.
if "%EXIT_CODE%"=="14" if not defined SILENT goto ask
:finished
echo.
if not "%EXIT_CODE%"=="0" echo Installation did not finish. Read the messages above.
if not defined SILENT pause
if defined OLDCP "%SystemRoot%\System32\chcp.com" %OLDCP% >nul
exit /b %EXIT_CODE%

:ask
echo.
rem No unless the answer is yes: Enter, any other word and the end of input all keep the
rem edition that is installed. Quotes are taken out, so no answer can end the string early.
set "ANSWER=n"
set /p "ANSWER=Change the edition? [y/N] "
set "ANSWER=%ANSWER:"=%"
if /i "%ANSWER%"=="y" goto change
if /i "%ANSWER%"=="yes" goto change
echo Nothing was changed.
goto finished

:change
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" -AllowEditionChange %*
set "EXIT_CODE=%ERRORLEVEL%"
goto finished
