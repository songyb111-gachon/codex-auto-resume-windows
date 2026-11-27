"""The icon's tick in the overflow flyout, on the C# host (S6.4c, P6-DESIGN 3.4 "window").

Twin of tests/test_tray_overflow_open.py OpenFlyoutTickTests: the Python icon's tick, run over a FakeUser32, moves an icon
somebody sees in the open flyout and holds it still in a closed one or under Reduce motion. Here the same tests - their own
bodies, through `super()` - are run with `tick` answered by gui/TrayIcon.cs: the host's probe (tests/rustdiff/HostProbe.cs
`icon_tick`) makes a TrayIcon with no window, answers its placement, flyout, motion and rect questions as the test patches
them, calls Observe and SyncMotion, and reports its state, whether it may move and the timers its SetTimer/KillTimer calls
leave. The icon's own question, Overflowed, is asked the same way (`icon_overflowed`).

Nothing is shown: the probe records every window call instead of making it (SurfaceScreen.Probe) and makes no window.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402
import test_tray_overflow_open as original  # noqa: E402  (a module name: its classes are not collected here)


@unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
class OpenFlyoutTickOnHostTests(original.OpenFlyoutTickTests):
    def tick(self, *, flyout_open, reduced=False, state_snapshot=None):
        found = surfacehost.SERVE.ask("icon_tick", flyout_open=flyout_open, reduced=reduced,
                                      snapshot=state_snapshot or {"enabled": True})
        icon = types.SimpleNamespace(_icon_state=found["state"], _motion_allowed=found["allowed"])
        fake = types.SimpleNamespace(timers={int(ident): ms for ident, ms in found["timers"].items()})
        return icon, fake

    def test_an_icon_in_the_open_flyout_moves_and_its_frame_timer_runs(self):
        super().test_an_icon_in_the_open_flyout_moves_and_its_frame_timer_runs()

    def test_every_moving_state_moves_in_the_open_flyout(self):
        super().test_every_moving_state_moves_in_the_open_flyout()

    def test_the_closed_flyout_still_holds_it_still(self):
        super().test_the_closed_flyout_still_holds_it_still()

    def test_reduce_motion_or_windows_animations_off_hold_it_still_in_the_open_flyout(self):
        super().test_reduce_motion_or_windows_animations_off_hold_it_still_in_the_open_flyout()

    def test_the_icon_asks_whether_the_flyout_is_open(self):
        """The tick itself asks: an icon in the flyout is held still only while the flyout is closed, and an icon on the
        taskbar never asks about the flyout (the original's two cases, of gui/TrayIcon.cs Overflowed)."""
        found = surfacehost.SERVE.ask("icon_overflowed", placed=True, open=True)
        self.assertFalse(found["answer"])
        self.assertEqual(found["asked"], 1)
        found = surfacehost.SERVE.ask("icon_overflowed", placed=False, open=False)
        self.assertFalse(found["answer"])
        self.assertEqual(found["asked"], 0, "an icon on the taskbar never asks about the flyout")
        # and the flyout closed is the one case it holds the icon still for
        self.assertTrue(surfacehost.SERVE.ask("icon_overflowed", placed=True, open=False)["answer"])


if __name__ == "__main__":
    unittest.main()
