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
      * What it hands back is the window without its frame. The frame is Windows' to
        draw, not the window's, so the border down each side and along the bottom comes
        back unpainted - which in a fresh bitmap is black. Every window screenshot this
        script made carried that black edge (11 px a side at 100%, 16 at 150%) until
        v0.6.6. So the picture is cut to what was actually drawn, measured from the
        window's own client rectangle rather than guessed at: the caption is kept, and
        the sides and the bottom lose exactly the frame Windows did not give us.

    Run: powershell -ExecutionPolicy Bypass -File build/capture_window.ps1 `
             -Exe <path to exe> -Out <path to png> [-Wait 6] [-Arguments '--page=pending']
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Wait = 6,
    # Passed to the window as its command line - which page it opens on.
    [string]$Arguments = ''
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace CaptureNative -Name Win -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
[DllImport("user32.dll")] public static extern bool RedrawWindow(IntPtr h, IntPtr rect, IntPtr region, uint flags);
public struct RECT { public int L, T, R, B; }
public struct POINT { public int X, Y; }
'@

# PER_MONITOR_AWARE_V2. Ignored on Windows older than 1703, where the script would
# already have been given real coordinates.
[void][CaptureNative.Win]::SetProcessDpiAwarenessContext([IntPtr](-4))

if ($Arguments) {
    $process = Start-Process $Exe -ArgumentList $Arguments -PassThru
} else {
    $process = Start-Process $Exe -PassThru
}
try {
    Start-Sleep -Seconds $Wait
    $process.Refresh()
    $handle = $process.MainWindowHandle
    if ($handle -eq [IntPtr]::Zero) { throw 'The window did not appear.' }

    # Paint everything now, synchronously, before looking. A child that had been invalidated
    # but not yet repainted was captured as its erased background: the Korean screenshot
    # published with v0.5.7 shows no status dot. RDW_INVALIDATE | RDW_ERASE |
    # RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME makes the capture independent of when the
    # window last got round to painting.
    [void][CaptureNative.Win]::RedrawWindow($handle, [IntPtr]::Zero, [IntPtr]::Zero, 0x0001 -bor 0x0004 -bor 0x0080 -bor 0x0100 -bor 0x0400)
    Start-Sleep -Milliseconds 300

    $rect = New-Object CaptureNative.Win+RECT
    [void][CaptureNative.Win]::GetWindowRect($handle, [ref]$rect)
    $width = $rect.R - $rect.L
    $height = $rect.B - $rect.T

    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    [void][CaptureNative.Win]::PrintWindow($handle, $dc, 2)
    $graphics.ReleaseHdc($dc)

    # The frame Windows draws and PrintWindow does not: the client rectangle says where the
    # window's own pixels begin and end, so the black band each side and along the bottom is
    # cut off by measurement. The caption is above the client area and was drawn, so the top
    # is left alone. If any of this cannot be read the whole bitmap is saved, black and all,
    # rather than a picture cut to a guess.
    $client = New-Object CaptureNative.Win+RECT
    $origin = New-Object CaptureNative.Win+POINT
    $cut = $bitmap
    if ([CaptureNative.Win]::GetClientRect($handle, [ref]$client) -and
        [CaptureNative.Win]::ClientToScreen($handle, [ref]$origin)) {
        $left = $origin.X - $rect.L
        $right = $rect.R - ($origin.X + $client.R)
        $bottom = $rect.B - ($origin.Y + $client.B)
        if ($left -ge 0 -and $right -ge 0 -and $bottom -ge 0 -and
            ($width - $left - $right) -gt 0 -and ($height - $bottom) -gt 0) {
            $crop = New-Object System.Drawing.Rectangle $left, 0, ($width - $left - $right), ($height - $bottom)
            $cut = $bitmap.Clone($crop, $bitmap.PixelFormat)
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    $cut.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host ('captured ' + $cut.Width + 'x' + $cut.Height + ' to ' + $Out)
    if (-not [object]::ReferenceEquals($cut, $bitmap)) { $cut.Dispose() }
    $graphics.Dispose()
    $bitmap.Dispose()
} finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
}
