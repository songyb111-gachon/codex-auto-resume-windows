"""The icon's demo event on the C# host (S6.4c, P6-DESIGN 3.4 "window").

Twin of tests/test_diagnostics_tools.py DemoTrayTests: the icon draws the demo only when its event was signalled since the
last look, and an icon asked for no demo makes no event. Here of gui/TrayIcon.cs, through the host's probe
(tests/rustdiff/HostProbe.cs `icon_demo`): a TrayIcon with no window, its event a handle the test stands in for, signalled
look by look as the Python test's Event is, LookForDemo once per look; and OpenDemo of an icon named for no demo.

Nothing is shown: the probe records the window calls instead of making them and makes no window and no event.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402


@unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
class DemoTrayOnHostTests(unittest.TestCase):
    def test_the_icon_draws_it_only_when_its_event_was_signalled(self):
        found = surfacehost.SERVE.ask("icon_demo", event="Local\\CodexAutoResume-demo-example",
                                      signalled=[False, True, False], looks=3)
        self.assertEqual(found["asked"], 1)
        self.assertTrue(found["no_demo_no_event"], "no demo asked for: no event made")


if __name__ == "__main__":
    unittest.main()
