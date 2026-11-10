"""A Dashboard left open past midnight: its taskbar and title-bar icons follow the date (v0.6.23), as the tray's do.

The built half compiles the real window, shows a form far off every screen without activating it, gives TaskbarMark a
date of the probe's own (DayArt.Clock), and reads the two icons Windows holds for the form. Nothing is ever on screen.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from test_gui_v0611_access import CSC, POWERSHELL, compile_window, run_probe

PROBE = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class W {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, int message, IntPtr which, IntPtr value);
    public static long Icon(IntPtr window, int which) { return SendMessage(window, 0x7F, (IntPtr)which, IntPtr.Zero).ToInt64(); }
}
'@
    $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
    $flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
    $art = $assembly.GetType('CodexAutoResume.DayArt', $true)
    $brand = $assembly.GetType('CodexAutoResume.Brand', $true)
    $look = $brand.GetMethod('DayLook', $flags)
    function Special([datetime]$day) {
        $call = [object[]]@([int]$day.Year, [int]$day.Month, [int]$day.Day, $null, $null, $null)
        return [bool]$look.Invoke($null, $call)
    }
    $script:special = $null; $script:plain = $null
    $day = [datetime]'2027-01-01'
    while ($day.Year -eq 2027 -and ($null -eq $script:special -or $null -eq $script:plain)) {
        if (Special $day) { if ($null -eq $script:special) { $script:special = $day } }
        elseif ($null -eq $script:plain) { $script:plain = $day }
        $day = $day.AddDays(1)
    }
    $art.GetField('On', $flags).SetValue($null, $true)
    $script:today = $script:plain
    $art.GetField('Clock', $flags).SetValue($null, [Func[datetime]]{ return $script:today })
    $form = New-Object Windows.Forms.Form
    $form.StartPosition = 'Manual'
    $form.Bounds = New-Object Drawing.Rectangle -30000, -30000, 200, 120
    $form.Icon = [Drawing.Icon]::ExtractAssociatedIcon($env:CAR_EXE)
    [void]$form.Handle
    [void][W]::ShowWindow($form.Handle, 4)
    $type = $assembly.GetType('CodexAutoResume.TaskbarMark', $true)
    $mark = $type.GetConstructors($flags)[0].Invoke([object[]]@($form.PSObject.BaseObject))
    $follow = $type.GetMethod('Follow', $flags); $sync = $type.GetMethod('Sync', $flags)
    [void]$follow.Invoke($mark, [object[]]@('watching'))
    # What the mark holds as the window's own icons, big and small: what Windows holds moves with the frames on show.
    function Own([string]$name) { return $type.GetField($name, $flags).GetValue($mark).ToInt64() }
    function Icons { return ,@((Own 'ownBig'), (Own 'ownSmall')) }
    $out = @{ ordinary = (Icons) }
    $script:today = $script:special
    [void]$sync.Invoke($mark, @())
    $out.special = (Icons)
    [void]$sync.Invoke($mark, @())
    $out.again = (Icons)
    $script:today = $script:plain.AddDays(1)
    if (Special $script:today) { $script:today = $script:plain }
    [void]$sync.Invoke($mark, @())
    $out.after = (Icons)
    $type.GetMethod('Dispose', $flags).Invoke($mark, @()) | Out-Null
    $form.Dispose()
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json $out -Compress -Depth 3), (New-Object Text.UTF8Encoding $false))
    exit 0
} catch {
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'probe.failed'), $_.Exception.ToString())
    exit 3
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "the window is compiled with the in-box C# compiler")
class DayIconsFollowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        work = Path(cls.folder.name).resolve()
        cls.failed = work / "probe.failed"
        try:
            cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(compile_window(work)))
        except AssertionError:
            cls.answer = {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        failed = self.failed.read_text(encoding="utf-8") if self.failed.is_file() else ""
        self.assertTrue(self.answer, failed[-3000:] or "the probe wrote no result")

    def test_past_midnight_into_a_special_day_both_icons_are_the_day_s(self):
        """Fails with FollowTheDay's call removed: the icons of the day the window opened on stay."""
        for which, name in enumerate(("big (the taskbar)", "small (the title bar)")):
            with self.subTest(name):
                self.assertNotEqual(self.answer["special"][which], self.answer["ordinary"][which])

    def test_the_same_day_changes_nothing(self):
        self.assertEqual(self.answer["again"], self.answer["special"])

    def test_past_the_next_midnight_the_window_s_own_icons_are_back(self):
        self.assertEqual(self.answer["after"], self.answer["ordinary"])


if __name__ == "__main__":
    unittest.main()
