<#
    Developer loop for the settings window: compile, deploy over the installed copy,
    relaunch and save a screenshot of the result.

    The screenshot is taken from a DPI-aware process. A DPI-unaware caller is handed
    virtualised screen coordinates, so GetWindowRect and CopyFromScreen disagree and the
    capture lands on some other part of the desktop entirely.

    This is a build tool, not part of the product: build/ is excluded from the release.

    It replaces the program files of the installation it is given and stops that installation's settings window, so it
    works on a COPY of an installation: -Target names it, and it refuses the real one - the profile's
    .codex-auto-resume, the folder CODEX_AUTO_RESUME_PLUGIN_HOME names, and any folder that holds or sits inside
    either - and says why (v0.6.23 audit, N13). Before this it deployed over the real installation, left an advanced installation's
    package out of step, ignored CODEX_AUTO_RESUME_PLUGIN_HOME and stopped every settings window on the PC.
#>
[CmdletBinding()]
param(
    [string]$Root  = (Split-Path -Parent $PSScriptRoot),
    [string]$Target = '',       # a scratch copy of an installation to deploy over (never the real one)
    [string]$Shot  = (Join-Path $env:TEMP 'codex-auto-resume-settings.png'),
    [int]$Width    = 0,        # optional: force a window width to test narrow layouts
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'

function Get-PreviewRefusal {
    <#
        Why $Target may not be deployed over, or $null when it may. Pure: it reads the two places the real installation
        can be (the profile's .codex-auto-resume and CODEX_AUTO_RESUME_PLUGIN_HOME) and compares paths; nothing is
        opened, stopped or written.
    #>
    param([string]$Target, [string]$Profile, [string]$Override)
    if ([string]::IsNullOrWhiteSpace($Target)) {
        return 'No -Target was given. This tool replaces the program files of the installation it is pointed at and stops its settings window, so it needs a scratch copy of an installation, named with -Target; it will not guess one, and never uses the real installation.'
    }
    $real = @()
    if (-not [string]::IsNullOrWhiteSpace($Profile)) { $real += (Join-Path $Profile '.codex-auto-resume') }
    if (-not [string]::IsNullOrWhiteSpace($Override)) { $real += $Override }
    try { $full = [IO.Path]::GetFullPath($Target).TrimEnd('\') }
    catch { return ('-Target cannot be read as a path: ' + $Target) }
    foreach ($place in $real) {
        try { $other = [IO.Path]::GetFullPath($place).TrimEnd('\') } catch { continue }
        if ($full -ieq $other -or $full.StartsWith($other + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $other.StartsWith($full + '\', [StringComparison]::OrdinalIgnoreCase)) {
            return ('-Target is, holds or sits inside the real installation (' + $other + '). This tool would stop its settings window and replace its program files, so it refuses; point -Target at a scratch copy of an installation.')
        }
    }
    return $null
}

# Before anything is built, stopped or copied.
$refusal = Get-PreviewRefusal -Target $Target -Profile $env:USERPROFILE -Override $env:CODEX_AUTO_RESUME_PLUGIN_HOME
if ($refusal) {
    Write-Host ('preview_gui: ' + $refusal)
    exit 2
}

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

$installed = [IO.Path]::GetFullPath($Target)
$target    = Join-Path $installed 'CodexAutoResumeSettings.exe'
if (-not (Test-Path -LiteralPath $installed)) { throw ('There is no installation at ' + $installed + '; -Target names a scratch copy of one.') }

# Only the settings window that runs from this very copy: another installation's, and the real one's, are not touched.
Get-Process -Name 'CodexAutoResumeSettings' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ($_.Path -ieq $target) } |
    ForEach-Object { $_.Kill(); [void]$_.WaitForExit(5000) }

# The image stays locked for a moment after the process exits, so retry the copy rather
# than racing it.
$copied = $false
for ($i = 0; $i -lt 20 -and -not $copied; $i++) {
    try { Copy-Item -LiteralPath (Join-Path $Root 'build\CodexAutoResumeSettings.exe') -Destination $target -Force -ErrorAction Stop
          $copied = $true }
    catch { Start-Sleep -Milliseconds 250 }
}
if (-not $copied) { throw 'Could not replace the installed settings window.' }

# Keep the deployed application source in step with the working tree, so the window is
# rendered from the schema being edited rather than the last released one: every module at
# every depth, and the bundled data (data\*.json). Replaced, not merged - a module the tree
# has deleted, or moved into a subpackage, must not linger in the deployed copy, where it
# would still import and would shadow the new one. The catalogs (locales\) are left as
# installed, as they always have been.
$package  = (Resolve-Path -LiteralPath (Join-Path $Root 'src\codex_auto_resume')).Path
$deployed = Join-Path $installed 'app\src\codex_auto_resume'
if (Test-Path -LiteralPath $deployed) {
    Get-ChildItem -LiteralPath $deployed -Recurse -File -Filter '*.py' | Remove-Item -Force
    Get-ChildItem -LiteralPath $deployed -Recurse -Directory -Filter '__pycache__' |
        Remove-Item -Recurse -Force
    $deployedData = Join-Path $deployed 'data'
    if (Test-Path -LiteralPath $deployedData) {
        Get-ChildItem -LiteralPath $deployedData -File -Filter '*.json' | Remove-Item -Force
    }
}
$packageData = Join-Path $package 'data'
Get-ChildItem -LiteralPath $package -Recurse -File |
    Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and
                   ($_.Extension -eq '.py' -or
                    ($_.Extension -eq '.json' -and $_.DirectoryName -eq $packageData)) } |
    ForEach-Object {
        $destination = Join-Path $deployed $_.FullName.Substring($package.Length).TrimStart('\')
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }

Start-Process $target
Start-Sleep -Seconds 4
$process = Get-Process -Name 'CodexAutoResumeSettings' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ($_.Path -ieq $target) } | Select-Object -First 1
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
