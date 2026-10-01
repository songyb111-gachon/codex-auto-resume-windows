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

    It waits for the window to say it is ready rather than for a fixed time. The window is given
    the name of an event (CODEX_AR_STILL_READY, which nothing else sets) and sets it once the page
    it opened on is drawn from the bridge's answers and holds still (SettingsForm.WatchForStill);
    -Wait is the longest that may take. Until v0.6.11 it was simply how long every picture waited,
    fifteen seconds each, whatever the window was doing. A window that does not say so in time is
    photographed as it was then, as before, and the output says it was not ready.

    Several may run at once, each with its own window: PrintWindow draws a window that is covered.
    (build/make_screenshots.py opens one at a time, or as many as its --windows says: WINDOWS_AT_ONCE.)
    The one thing they share is which window is active, and a window that closes hands activation
    to another - which would paint that one's caption active in the middle of its capture. So the
    moment of capture, from the inactive caption to the window being closed, is taken one at a
    time, under a lock every capture on this machine shares.

    Run: powershell -ExecutionPolicy Bypass -File build/capture_window.ps1 `
             -Exe <path to exe> -Out <path to png> [-Wait 6] [-Arguments '--page=pending']
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Out,
    # The longest, in seconds, the window may take to say it is ready to be photographed.
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
[DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
[DllImport("user32.dll")] public static extern bool GetWindowInfo(IntPtr h, ref WINDOWINFO info);
public struct RECT { public int L, T, R, B; }
public struct POINT { public int X, Y; }
public struct WINDOWINFO {
    public uint cbSize; public RECT rcWindow; public RECT rcClient; public uint dwStyle; public uint dwExStyle;
    public uint dwWindowStatus; public uint cxWindowBorders; public uint cyWindowBorders;
    public ushort atomWindowType; public ushort wCreatorVersion;
}
// Whether the window's frame is drawn active (WS_ACTIVECAPTION): what the last WM_NCACTIVATE it
// was sent - by this script or by Windows - left it as.
public static bool CaptionActive(IntPtr h) {
    var info = new WINDOWINFO();
    info.cbSize = (uint)Marshal.SizeOf(typeof(WINDOWINFO));
    return GetWindowInfo(h, ref info) && (info.dwWindowStatus & 1) != 0;
}
'@

# PER_MONITOR_AWARE_V2. Ignored on Windows older than 1703, where the script would
# already have been given real coordinates.
[void][CaptureNative.Win]::SetProcessDpiAwarenessContext([IntPtr](-4))

$turn = $null
$held = $false
$process = $null
$ready = $null
try {
    # Every status light is held at the brightest moment of its breath (Soft.StillLightMs), so the
    # same window photographed twice comes out the same. Without it a picture changed whenever it
    # was taken, and the difference looked like a change to the source.
    $env:CODEX_AR_STILL_LIGHT = '0'
    # The event the window sets once it may be photographed (Soft.StillReady), named for this capture alone.
    $readyName = 'Local\CodexAutoResume.Still.' + [guid]::NewGuid().ToString('N')
    $ready = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::ManualReset, $readyName)
    $env:CODEX_AR_STILL_READY = $readyName
    try {
        if ($Arguments) {
            $process = Start-Process $Exe -ArgumentList $Arguments -PassThru
        } else {
            $process = Start-Process $Exe -PassThru
        }
    } finally {
        Remove-Item Env:\CODEX_AR_STILL_LIGHT -ErrorAction SilentlyContinue
        Remove-Item Env:\CODEX_AR_STILL_READY -ErrorAction SilentlyContinue
    }

    $waited = [System.Diagnostics.Stopwatch]::StartNew()
    $said = $ready.WaitOne([Math]::Max(0, $Wait) * 1000)
    $waited.Stop()
    $process.Refresh()
    $handle = $process.MainWindowHandle
    # A window still being made when the wait ran out has no handle yet: it is given two minutes more to
    # appear at all, where until v0.6.11 the capture failed at once.
    $appearing = [System.Diagnostics.Stopwatch]::StartNew()
    while ($handle -eq [IntPtr]::Zero -and -not $process.HasExited -and $appearing.Elapsed.TotalSeconds -lt 120) {
        Start-Sleep -Milliseconds 200
        $process.Refresh()
        $handle = $process.MainWindowHandle
    }
    if ($handle -eq [IntPtr]::Zero) { throw 'The window did not appear.' }

    # A window that is still busy when the wait runs out answers nothing until it is done, and the capture
    # below would wait for it holding every other capture's turn: it waits for the window here instead.
    # WM_NULL, which a window answers by doing nothing, returns once the window reads its messages again.
    [void][CaptureNative.Win]::SendMessage($handle, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)

    # One capture at a time from here until its window is closed (see the top of this file).
    $turn = New-Object System.Threading.Mutex($false, 'Local\CodexAutoResume.Capture')
    try { $held = $turn.WaitOne() } catch [System.Threading.AbandonedMutexException] { $held = $true }

    # Paint everything now, synchronously, before looking. A child that had been invalidated
    # but not yet repainted was captured as its erased background: the Korean screenshot
    # published with v0.5.7 shows no status dot. RDW_INVALIDATE | RDW_ERASE |
    # RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME makes the capture independent of when the
    # window last got round to painting.
    # The caption is Windows', and it is drawn light when the window is active and grey when it
    # is not - so a picture taken while this window happened to hold the foreground came out
    # different from one taken while it did not, for a reason that has nothing to do with the
    # source. Every picture is taken of an inactive window: WM_NCACTIVATE(FALSE) paints the
    # frame as the window looks when somebody is working elsewhere, which is also how a
    # screenshot in a document is read.
    # That holds only for a window that is not in fact the foreground window: the redraw below
    # paints the frame of the foreground window active again, whatever it was told. Which window
    # has the foreground was never the capture's to decide - a window takes it as it opens once
    # nobody has typed for a while, and is handed it when the window in front of it closes - and a
    # Japanese Overview captured beside other windows came out active (v0.6.11). So the window a
    # capture starts never takes it (SettingsForm.ShowWithoutActivation, WS_EX_NOACTIVATE), and the
    # caption is read back once the picture is taken: still active, and it is taken again; still
    # active five times over, and the capture fails rather than keep a picture of an active window.
    $attempt = 0
    while ($true) {
        [void][CaptureNative.Win]::SendMessage($handle, 0x0086, [IntPtr]::Zero, [IntPtr]::Zero)
        # The focus ring and the access-key underlines are Windows' keyboard cues, and a new window
        # takes their state from how the last input reached the machine - so the Settings picture
        # carried a ring round the Overview tab in some releases and not in others, with nothing in
        # the source moved. Every picture is taken with the cues hidden, as a window looks to a person
        # using the mouse: WM_CHANGEUISTATE(UIS_SET, UISF_HIDEFOCUS | UISF_HIDEACCEL) on the top-level
        # window, which passes it to every child as WM_UPDATEUISTATE, and the redraw below paints it.
        [void][CaptureNative.Win]::SendMessage($handle, 0x0127, [IntPtr](0x00030001), [IntPtr]::Zero)
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
        if (-not [CaptureNative.Win]::CaptionActive($handle)) { break }
        $graphics.Dispose()
        $bitmap.Dispose()
        $attempt++
        if ($attempt -ge 5) { throw 'The window was made active during each of five captures.' }
    }

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
    # And the corners Windows rounds. They are DWM's, not the window's, so they are not in
    # what PrintWindow hands back either - a screenshot of a Windows 11 window with square
    # corners is a screenshot of a window nobody has. They are cut here instead, to the
    # system's own radius for a resizable window at this window's DPI, and the four corners
    # are left transparent so the page behind the picture shows through them.
    $dpi = [CaptureNative.Win]::GetDpiForWindow($handle)
    if ($dpi -le 0) { $dpi = 96 }
    $radius = [int][Math]::Round(8.0 * $dpi / 96.0)
    if ($radius -gt 0 -and $cut.Width -gt 2 * $radius -and $cut.Height -gt 2 * $radius) {
        $rounded = New-Object System.Drawing.Bitmap $cut.Width, $cut.Height, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $paint = [System.Drawing.Graphics]::FromImage($rounded)
        $paint.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $paint.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $path = New-Object System.Drawing.Drawing2D.GraphicsPath
        $d = 2 * $radius
        $path.AddArc(0, 0, $d, $d, 180, 90)
        $path.AddArc($cut.Width - $d, 0, $d, $d, 270, 90)
        $path.AddArc($cut.Width - $d, $cut.Height - $d, $d, $d, 0, 90)
        $path.AddArc(0, $cut.Height - $d, $d, $d, 90, 90)
        $path.CloseFigure()
        # Filled through the picture rather than clipped to it: a clip has hard edges, and a
        # corner made of stair steps is the thing this is here to avoid.
        $brush = New-Object System.Drawing.TextureBrush $cut
        $paint.FillPath($brush, $path)
        $brush.Dispose(); $path.Dispose(); $paint.Dispose()
        if (-not [object]::ReferenceEquals($cut, $bitmap)) { $cut.Dispose() }
        $cut = $rounded
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    $cut.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $readiness = if ($said) { 'ready after ' + [Math]::Round($waited.Elapsed.TotalSeconds, 1) + ' s' }
                 else { 'not ready after ' + $Wait + ' s' }
    if ($attempt -gt 0) { $readiness += ', taken again ' + $attempt + ' time(s): it was made active' }
    Write-Host ('captured ' + $cut.Width + 'x' + $cut.Height + ' to ' + $Out + ' (' + $readiness + ')')
    if (-not [object]::ReferenceEquals($cut, $bitmap)) { $cut.Dispose() }
    $graphics.Dispose()
    $bitmap.Dispose()
} finally {
    if ($process -ne $null -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        # Gone before the next capture takes its turn, and whatever it hands activation to with it.
        [void]$process.WaitForExit(5000)
    }
    if ($held) { $turn.ReleaseMutex() }
    if ($turn -ne $null) { $turn.Dispose() }
    if ($ready -ne $null) { $ready.Dispose() }
}
