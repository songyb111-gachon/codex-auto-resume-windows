<#
    Developer loop for the settings window: compile, deploy over the installed copy,
    relaunch and save a screenshot of the result.

    The screenshot is taken from a DPI-aware process. A DPI-unaware caller is handed
    virtualised screen coordinates, so GetWindowRect and CopyFromScreen disagree and the
    capture lands on some other part of the desktop entirely.

    This is a build tool, not part of the product: build/ is excluded from the release.
#>
[CmdletBinding()]
param(
    [string]$Root  = (Split-Path -Parent $PSScriptRoot),
    [string]$Shot  = (Join-Path $env:TEMP 'codex-auto-resume-settings.png'),
    [int]$Width    = 0,        # optional: force a window width to test narrow layouts
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class PreviewWin {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int t, bool repaint);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
[void][PreviewWin]::SetProcessDPIAware()
Add-Type -AssemblyName System.Drawing

if (-not $NoBuild) { & (Join-Path $PSScriptRoot 'make_gui.ps1') -Root $Root }

$installed = Join-Path $env:USERPROFILE '.codex-auto-resume'
$target    = Join-Path $installed 'CodexAutoResumeSettings.exe'
if (-not (Test-Path $installed)) { throw 'Codex Auto Resume is not installed; run the installer first.' }

Get-Process -Name 'CodexAutoResumeSettings' -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Kill(); [void]$_.WaitForExit(5000) }

# The image stays locked for a moment after the process exits, so retry the copy rather
# than racing it.
$copied = $false
for ($i = 0; $i -lt 20 -and -not $copied; $i++) {
    try { Copy-Item (Join-Path $Root 'build\CodexAutoResumeSettings.exe') $target -Force -ErrorAction Stop
          $copied = $true }
    catch { Start-Sleep -Milliseconds 250 }
}
if (-not $copied) { throw 'Could not replace the installed settings window.' }

# Keep the deployed application source in step with the working tree, so the window is
# rendered from the schema being edited rather than the last released one.
Copy-Item (Join-Path $Root 'src\codex_auto_resume\*.py') `
          (Join-Path $installed 'app\src\codex_auto_resume') -Force

Start-Process $target
Start-Sleep -Seconds 4
$process = Get-Process -Name 'CodexAutoResumeSettings' -ErrorAction SilentlyContinue
if (-not $process) { throw 'The settings window did not start.' }

$rect = New-Object PreviewWin+RECT
[void][PreviewWin]::GetWindowRect($process.MainWindowHandle, [ref]$rect)
if ($Width -gt 0) {
    [void][PreviewWin]::MoveWindow($process.MainWindowHandle, $rect.L, $rect.T,
                                   $Width, ($rect.B - $rect.T), $true)
}
[void][PreviewWin]::SetForegroundWindow($process.MainWindowHandle)
Start-Sleep -Milliseconds 900
[void][PreviewWin]::GetWindowRect($process.MainWindowHandle, [ref]$rect)

$w = $rect.R - $rect.L
$h = $rect.B - $rect.T
$bitmap = New-Object System.Drawing.Bitmap $w, $h
$canvas = [System.Drawing.Graphics]::FromImage($bitmap)
$canvas.CopyFromScreen($rect.L, $rect.T, 0, 0, (New-Object System.Drawing.Size $w, $h))
$bitmap.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
$canvas.Dispose(); $bitmap.Dispose()

Write-Host ('captured ' + $Shot + ' (' + $w + 'x' + $h + ')')
