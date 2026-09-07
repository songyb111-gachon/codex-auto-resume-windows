<#
    Screenshot a window of this product, for the documentation.

    Two details make the difference between a usable screenshot and a misleading one,
    and both were learned by producing the misleading version first:

      * The capturing process must declare itself DPI aware. A DPI-unaware script is
        told a scaled-down window rectangle, allocates a bitmap that size, and gets back
        a picture of the top-left corner of the window with everything else cropped -
        which looks exactly like a window whose layout is broken.
      * PrintWindow with PW_RENDERFULLCONTENT captures the window's own pixels rather
        than the screen, so nothing that happens to be in front of it lands in the shot.

    Run: powershell -ExecutionPolicy Bypass -File build/capture_window.ps1 `
             -Exe <path to exe> -Out <path to png> [-Wait 6]
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Wait = 6
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace CaptureNative -Name Win -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
public struct RECT { public int L, T, R, B; }
'@

# PER_MONITOR_AWARE_V2. Ignored on Windows older than 1703, where the script would
# already have been given real coordinates.
[void][CaptureNative.Win]::SetProcessDpiAwarenessContext([IntPtr](-4))

$process = Start-Process $Exe -PassThru
try {
    Start-Sleep -Seconds $Wait
    $process.Refresh()
    $handle = $process.MainWindowHandle
    if ($handle -eq [IntPtr]::Zero) { throw 'The window did not appear.' }

    $rect = New-Object CaptureNative.Win+RECT
    [void][CaptureNative.Win]::GetWindowRect($handle, [ref]$rect)
    $width = $rect.R - $rect.L
    $height = $rect.B - $rect.T

    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    [void][CaptureNative.Win]::PrintWindow($handle, $dc, 2)
    $graphics.ReleaseHdc($dc)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    $bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    Write-Host ('captured ' + $width + 'x' + $height + ' to ' + $Out)
} finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
}
