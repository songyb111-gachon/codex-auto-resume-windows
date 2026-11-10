"""v0.6.23: a window Windows refuses the foreground stands above the others all the same, and takes no focus.

The setup windows of the v0.6.22 live acceptance (F3, F9's reinstall, F10) opened behind other windows: started by no
person's click, they were refused the foreground and only their taskbar buttons flashed. HostApp.RaiseWithoutFocus, which
BringToFront calls where SetForegroundWindow says no, makes the window topmost for a moment and takes it back, never
activating it: whoever is typing elsewhere goes on typing there.

The built half compiles the real window, shows two windows far off every screen without activating them, the second above
the first, and asks HostApp to raise the first. Nothing is ever on screen; nothing of the real installation is read.
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
public static class Z {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr window, int command);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] public static extern IntPtr Style(IntPtr window, int index);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int cx, int cy, uint flags);
    public static bool Above(IntPtr upper, IntPtr lower) {
        for (IntPtr at = GetWindow(lower, 3); at != IntPtr.Zero; at = GetWindow(at, 3)) if (at == upper) return true;
        return false;
    }
}
'@
    $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
    $flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
    $raise = $assembly.GetType('CodexAutoResume.HostApp', $true).GetMethod('RaiseWithoutFocus', $flags)
    function Off-Screen {
        $form = New-Object Windows.Forms.Form
        $form.StartPosition = 'Manual'
        $form.ShowInTaskbar = $false
        $form.FormBorderStyle = 'None'
        $form.Bounds = New-Object Drawing.Rectangle -30000, -30000, 40, 40
        [void]$form.Handle
        [void][Z]::ShowWindow($form.Handle, 4)     # SW_SHOWNOACTIVATE
        return $form
    }
    $first = Off-Screen
    $second = Off-Screen
    # Behind `second`, whatever order Windows gave them (0x13: no size, no move, no activation).
    [void][Z]::SetWindowPos($first.Handle, $second.Handle, 0, 0, 0, 0, 0x13)
    $out = @{ belowBefore = [Z]::Above($second.Handle, $first.Handle) }
    $front = [Z]::GetForegroundWindow()
    [void]$raise.Invoke($null, [object[]]@($first.Handle))
    $out.above = [Z]::Above($first.Handle, $second.Handle)
    $out.frontKept = ([Z]::GetForegroundWindow() -eq $front)
    $out.topmostLeft = (([Z]::Style($first.Handle, -20).ToInt64() -band 0x8) -ne 0)    # GWL_EXSTYLE, WS_EX_TOPMOST
    $first.Dispose(); $second.Dispose()
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json $out -Compress), (New-Object Text.UTF8Encoding $false))
    exit 0
} catch {
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'probe.failed'), $_.Exception.ToString())
    exit 3
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "the window is compiled with the in-box C# compiler")
class RaiseWithoutFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        work = Path(cls.folder.name).resolve()
        cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(compile_window(work)))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_it_stands_above_the_window_it_was_under(self):
        """Fails with the raise made a no-op: the first window stays under the second."""
        self.assertTrue(self.answer["belowBefore"])
        self.assertTrue(self.answer["above"])

    def test_the_foreground_stays_where_it_was_and_it_does_not_stay_topmost(self):
        self.assertTrue(self.answer["frontKept"], "someone typing elsewhere keeps the keyboard")
        self.assertFalse(self.answer["topmostLeft"], "only for the moment it is raised")


if __name__ == "__main__":
    unittest.main()
