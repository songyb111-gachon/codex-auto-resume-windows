"""The notification-area icon started, updated and stopped for real, on the C# host (S6.4d6, P6-DESIGN 3.4 "window").

Twin of tests/test_tray.py LiveIconTests: the original's body through `super()`, with `tray.Tray` tests/rustdiff/hostlive.py's
HostLiveTray - the host's TrayIcon started for real on a thread of the probe's own (HostProbe.cs `icon_live`): its hidden
window made by its own Create, the icon added to the notification area from the test's .ico (Shell_NotifyIconW NIM_ADD),
the one-second tick that writes the tooltip, and the thread's message loop until the window's WM_DESTROY ends it. The main
session's word of 2026-11-28: the twin shows what the original shows - a real tray icon - exactly as the original does,
removed in the test's own teardown (the original's `finally: icon.stop()`; and here any icon still up when the test ends),
inside gui_lock.sh, never a dialog, no focus or foreground change. What changed, and only that: `start`, `update`, `stop`,
`_last_tip` and `_thread.is_alive()` are the host's (`_last_tip` its TrayIcon.LastTip, the tooltip it last handed the
shell; the thread its icon's own).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402

if os.name == "nt":
    import hostlive  # noqa: E402
    import test_tray as original  # noqa: E402  (a module name: its classes are not collected here)
    LIVE = original.LiveIconTests
else:
    LIVE = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class TrayOnHost:
    """The reference tray package with its Tray the host's live icon; everything else is the reference's."""

    def __init__(self, reference):
        self._reference = reference
        self.Tray = hostlive.HostLiveTray

    def __getattr__(self, name):
        return getattr(self._reference, name)


@ON_HOST
class LiveIconOnHostTests(LIVE):  # noqa: F821
    def setUp(self):
        patcher = unittest.mock.patch.object(original, "tray", TrayOnHost(original.tray))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._no_icon_left)
        super().setUp()

    @staticmethod
    def _no_icon_left():
        for icon in list(hostlive.HostLiveTray.started):
            icon.stop()

    def test_the_icon_starts_updates_and_goes_away_cleanly(self):
        super().test_the_icon_starts_updates_and_goes_away_cleanly()


del LIVE


if __name__ == "__main__":
    unittest.main()
