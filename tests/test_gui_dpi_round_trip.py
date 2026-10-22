r"""A Dashboard dragged to a monitor of another scale and back keeps its size (v0.6.18 live acceptance, item B3).

Dragged from a 144-DPI monitor to a 96-DPI one, the window opened again at the new scale - as it should (R3) - but
1522x1052 came back as 800x467 (676x467 held to the 800 minimum) and, dragged back, as 1800x1052: the size was scaled
twice each way, 1.5 squared. Windows had already resized the per-monitor window to the new scale in the drag, and
the reopen scaled the size it read afterwards again. The reopen now scales the size the window had before the drag
(drawnSize, taken at WM_ENTERSIZEMOVE, or at WM_DPICHANGED when no drag moved it) - ReopenBounds - and the window
that opens is held to the bounds it was placed at once it is shown (KeepPlacedBounds), so nothing on the way to the
screen can scale it a second time either.

No second monitor is needed: the rule is a pure function, checked here with the numbers the acceptance measured; the
capture points are read in the source; and the hold is driven on the real compiled window, never shown.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

import guiscan
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe


def code_only(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


class SourceTests(unittest.TestCase):
    def test_the_size_is_taken_before_the_drag_can_scale_it(self):
        handler = code_only(guiscan.member_body("SettingsForm", "WndProc"))
        enter = handler.index("if (m.Msg == WM_ENTERSIZEMOVE)")
        self.assertIn("if (!scaleMoved) drawnSize = SizeAtDrawnScale();", handler[enter:])
        changed = handler[handler.index("if (m.Msg == WM_DPICHANGED)"):enter]
        self.assertIn("if (!scaleMoved && !sizing) drawnSize = SizeAtDrawnScale();", changed)
        self.assertLess(changed.index("drawnSize = SizeAtDrawnScale();"), changed.index("scaleMoved = true;"))

    def test_the_reopen_scales_that_size_and_not_the_one_after_the_move(self):
        reopen = code_only(guiscan.member_body("SettingsForm", "Reopen"))
        self.assertIn("if (reopenScale > 0) bounds = ReopenBounds(bounds, drawnSize, DisplayScale, reopenScale);", reopen)
        self.assertNotIn("ScaledBounds(bounds, DisplayScale, reopenScale)", reopen)

    def test_a_reopened_window_is_held_to_where_it_was_placed(self):
        window = guiscan.settings()
        self.assertLess(window.index("Bounds = PlaceOnScreen(request.Bounds"), window.index("placedBounds = Bounds;"))
        self.assertIn("KeepPlacedBounds();", window[window.index("Shown += delegate"):])


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box C# compiler and Windows PowerShell")
class BuiltTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_from_144_to_96_dpi_the_size_is_scaled_once(self):
        """1522x1052 at 1.5, which Windows had already made 1015x701 in the drag: 1015x701 at 1.0, where it stands."""
        self.assertEqual(self.answer["down"], [3900, 120, 1015, 701])

    def test_and_back_it_is_the_size_it_was(self):
        self.assertEqual(self.answer["back"], [200, 90, 1522, 1052])

    def test_what_the_old_rule_made_of_it(self):
        """The size after the move scaled again: 1.5 squared, the acceptance's 676x467 (held to 800 wide there)."""
        self.assertEqual(self.answer["twice"], [3900, 120, 677, 467])

    def test_with_no_size_taken_it_scales_the_one_it_has(self):
        self.assertEqual(self.answer["untaken"], [10, 20, 2044, 1440])

    def test_a_reopened_window_is_held_to_the_bounds_it_was_placed_at(self):
        held = self.answer["held"]
        self.assertEqual(held["after"], held["placed"], "a size changed on the way to the screen was kept")
        self.assertEqual(held["again"], held["moved"], "held once: a later move or resize is the person's")


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
function Box($r) { return @($r.X, $r.Y, $r.Width, $r.Height) }
$reopen = $F.GetMethod('ReopenBounds', $flags)
$scaled = $F.GetMethod('ScaledBounds', $flags)
$out = @{}
# Dragged from the 144-DPI primary to a 96-DPI monitor at x 3840: Windows has made the window 1015x701 in the drag.
$out.down = Box ($reopen.Invoke($null, [object[]]@([Drawing.Rectangle]::new(3900, 120, 1015, 701), [Drawing.Size]::new(1522, 1052), [double]1.5, [double]1.0)))
# And back: the window that opened at 96 DPI is 1015x701 before the drag, Windows makes it 1522x1052 on the way.
$out.back = Box ($reopen.Invoke($null, [object[]]@([Drawing.Rectangle]::new(200, 90, 1522, 1052), [Drawing.Size]::new(1015, 701), [double]1.0, [double]1.5)))
$out.twice = Box ($scaled.Invoke($null, [object[]]@([Drawing.Rectangle]::new(3900, 120, 1015, 701), [double]1.5, [double]1.0)))
$out.untaken = Box ($reopen.Invoke($null, [object[]]@([Drawing.Rectangle]::new(10, 20, 1022, 720), [Drawing.Size]::Empty, [double]1.0, [double]2.0)))

# The hold, on the real window: placed at one rectangle, changed on the way, put back once and only once.
$english = $J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK 'strings-en.json'), $utf8)))
$nowhere = [string](Join-Path $env:CAR_WORK 'nowhere')
$once = $BT.GetConstructors($flags)[0].Invoke([object[]]@($nowhere))
$bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($nowhere, $once))
$three = @($F.GetConstructors($flags) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($window, $true)
$window.MinimumSize = [Drawing.Size]::Empty
$placed = [Drawing.Rectangle]::new(100, 80, 1015, 701)
$window.Bounds = $placed
$F.GetField('placedBounds', $flags).SetValue($window, $placed)
$window.Bounds = [Drawing.Rectangle]::new(100, 80, 677, 467)
$keep = $F.GetMethod('KeepPlacedBounds', $flags)
$null = $keep.Invoke($window, @())
$after = $window.Bounds
$moved = [Drawing.Rectangle]::new(140, 90, 900, 600)
$window.Bounds = $moved
$null = $keep.Invoke($window, @())
$out.held = @{ placed = (Box $placed); after = (Box $after); moved = (Box $moved); again = (Box $window.Bounds) }
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
"""


if __name__ == "__main__":
    unittest.main()
