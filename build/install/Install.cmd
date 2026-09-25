@echo off
setlocal
"%SystemRoot%\System32\chcp.com" 65001 >nul
title Codex Auto Resume - install
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
rem 14: this archive is the other edition from the one installed. The installer has said what
rem changing it keeps and what it changes, and changes it only when asked - so this asks.
if "%EXIT_CODE%"=="14" goto ask
:finished
echo.
if not "%EXIT_CODE%"=="0" echo Installation did not finish. Read the messages above.
pause
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
