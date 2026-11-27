"""The popup's window is its card, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twins of tests/test_popup_card_window.py's CardWindowTests: the originals' bodies through `super()`, the popup the host's
PopupWindow made by its own Create - the card and its shadow, real top-level layered windows, kept by the host
(tests/rustdiff/hostcardwindow.py, HostProbe.cs `popup_live`) - and read by the originals' own user32 calls, a window's
handle being the same in every process. What changed, and only that:

* `make` makes a HostCardPopup from the test's control layer, strings and log;
* `recorded` records the host popup's calls from then on instead of patching the reference's `layers.update` (the host's
  record of each UpdateLayeredWindowIndirect, in the same (hwnd, keywords)); while recording the host makes none of them;
* `pump` runs the host's messages (and, while recording, what it posted itself and its timers) for the same time;
* a click and a screen reader: the reader is the host's - its children and accLocation through the client object the
  host's window hands a reader (`access.PopupAccessible` patched to HostAccessible for that test only);
* refused: the reference's `layers.update` patched to fail is, on the host, Windows refusing the upload (its shadow window
  made no layered window, so UpdateLayeredWindowIndirect fails and PopupWindow.Plain runs as the reference's does).

The windows are the originals' windows: far off every screen at (-32000, -32000), shown without activation, destroyed in
the test's teardown, run through gui_lock.sh (the main session's word of 2026-11-28); nothing is captured.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402

if os.name == "nt":
    import hostcardwindow  # noqa: E402
    import test_popup_card_window as original  # noqa: E402  (a module name: its classes are not collected here)
    BASE = original.CardWindowTests
else:
    BASE = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


@ON_HOST
class CardWindowOnHostTests(BASE):  # noqa: F821 (BASE is deleted below, so the original is not collected twice)
    def setUp(self):
        super().setUp()
        self.made, self.calls = [], None

    def make(self, **extra):
        from test_tray_popup import EN, FakeControl, WindowsTests
        window = hostcardwindow.HostCardPopup(control=FakeControl(WindowsTests.ROWS), strings=EN, log=extra.get("log"),
                                              calls=self.calls)
        self.made.append(window)
        self.addCleanup(window.destroy)
        return window

    def pump(self, seconds=0.05):
        for window in self.made:
            window.pump(seconds)

    def recorded(self):
        if self.calls is None:
            self.calls = []
            for window in self.made:
                window.record(self.calls)
        return self.calls

    def test_a_click_and_a_screen_reader_find_what_is_drawn_there(self):
        with mock.patch.object(original.access, "PopupAccessible", hostcardwindow.HostAccessible):
            super().test_a_click_and_a_screen_reader_find_what_is_drawn_there()


del BASE


if __name__ == "__main__":
    unittest.main()
