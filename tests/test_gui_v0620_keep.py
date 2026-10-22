r"""KeepOnScreen measures the window's frame from its style (v0.6.18, the parked "KeepOnScreen at 200%").

It took the frame as Width less ClientSize.Width. Windows holds a form's Width to the largest window the screen allows
(SystemInformation.MaxWindowTrackSize) while ClientSize keeps what was asked, so on a small screen at 200% or more
that frame read negative and the clamp - the work area less the frame - let the window grow past the screen, its
footer out of reach. The Advanced tab's HoldTabs read the frame the same way and was fixed with SizeFromClientSize;
KeepOnScreen now is too.

The built half asks the real compiled window for a client area wider and taller than Windows lets a window be, so its
Width is held while its ClientSize is not, and calls KeepOnScreen: the window it leaves fits the work area of the
screen it opens on. With the old reading it does not (checked by putting it back). Nothing is shown.
"""
from __future__ import annotations

import os
import unittest

import guiscan
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe


def code_only(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


class SourceTests(unittest.TestCase):
    def test_the_frame_is_what_the_style_adds(self):
        keep = code_only(guiscan.member_body("SettingsForm", "KeepOnScreen"))
        self.assertIn("Size frame = SizeFromClientSize(Size.Empty);", keep)
        self.assertNotIn("Width - ClientSize.Width", keep)
        self.assertNotIn("Height - ClientSize.Height", keep)


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box C# compiler and Windows PowerShell")
class BuiltTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        import tempfile
        from pathlib import Path
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_asked_size_was_held_by_windows(self):
        """Otherwise the old reading is not negative and this proves nothing."""
        self.assertLess(self.answer["heldFrame"], 0, "Width less ClientSize.Width must read negative here")

    def test_the_window_it_leaves_fits_the_screen(self):
        width, height = self.answer["outer"]
        work_width, work_height = self.answer["work"]
        floor = self.answer["floor"]
        self.assertLessEqual(width, max(work_width, floor + self.answer["frame"][0]))
        self.assertLessEqual(height, max(work_height, floor + self.answer["frame"][1]))

    def test_the_client_area_is_the_work_area_less_the_real_frame(self):
        client_width, client_height = self.answer["client"]
        work_width, work_height = self.answer["work"]
        frame_width, frame_height = self.answer["frame"]
        floor = self.answer["floor"]
        self.assertEqual(client_width, max(floor, work_width - frame_width))
        self.assertEqual(client_height, max(floor, work_height - frame_height))


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$utf8 = New-Object Text.UTF8Encoding $false
$english = $J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK 'strings-en.json'), $utf8)))
$nowhere = [string](Join-Path $env:CAR_WORK 'nowhere')
$once = $BT.GetConstructors($flags)[0].Invoke([object[]]@($nowhere))
$bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($nowhere, $once))
$three = @($F.GetConstructors($flags) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($window, $true)
$fromClient = [Windows.Forms.Control].GetMethod('SizeFromClientSize', $flags, $null, [type[]]@([Drawing.Size]), $null)
# Wider and taller than Windows lets a window be: Windows holds Width and Height, ClientSize keeps what was asked.
$track = [Windows.Forms.SystemInformation]::MaxWindowTrackSize
$window.MinimumSize = [Drawing.Size]::Empty
$window.ClientSize = [Drawing.Size]::new($track.Width + 600, $track.Height + 600)
$held = $window.Width - $window.ClientSize.Width
# The screen KeepOnScreen measures for a window built with a catalog, which opens on none: the one Screen.FromControl
# answers for it as it is when KeepOnScreen looks.
$work = [Windows.Forms.Screen]::FromControl($window).WorkingArea
$null = $F.GetMethod('KeepOnScreen', $flags).Invoke($window, @())
$frame = $fromClient.Invoke($window, [object[]]@([Drawing.Size]::Empty))
$px = @($F.GetMethods($flags) | Where-Object { $_.Name -eq 'Px' -and $_.GetParameters().Count -eq 1 })[0]
$out = @{ heldFrame = $held; work = @($work.Width, $work.Height); frame = @($frame.Width, $frame.Height)
          client = @($window.ClientSize.Width, $window.ClientSize.Height)
          outer = @(($window.ClientSize.Width + $frame.Width), ($window.ClientSize.Height + $frame.Height))
          floor = [int]$px.Invoke($window, [object[]]@([int]340)) }
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
"""


if __name__ == "__main__":
    unittest.main()
