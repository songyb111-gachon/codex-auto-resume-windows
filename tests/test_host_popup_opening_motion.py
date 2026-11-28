"""The popup's opening and its buttons' faces, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twins of tests/test_popup_opening_motion.py's WindowTests: the originals' bodies through `super()`, the popup the host's
PopupWindow with its own real windows (tests/rustdiff/hostcardwindow.py, HostProbe.cs `popup_live`), far off every screen,
never activated, destroyed in the test's teardown, through gui_lock.sh (the main session's word of 2026-11-28). What
changed, and only that:

* `make` makes a HostCardPopup from the test's control layer, strings, `held` and log;
* `pump` runs the host's messages for the same time: its own frame timer's frames, each at its own instant of the test's
  clock (the host's clock is the test's time.monotonic, read as each question comes);
* `record_openings`: each frame of the opening as the host's motion.opening answered it - the elapsed time OpeningStep
  asked it at, the alpha and rise it took, whether it arrived - read around the host's own frame (the reference patches
  `messages.opening` to record its calls);
* the faces a frame draws: where the test wraps the renderer's `draw`, the host's render step answers the faces its draw
  was given (PopupWindow.FaceGlides at the frame's instant, as Render reads it first) and the wrapper is called with them;
* kept alive while its window exists: the reference holds the Python object in `_LIVING` for ctypes' window procedure; on
  the host the procedure Windows calls is the delegate the PopupWindow holds (its `proc`), so the twin checks that the
  window's procedure is that very delegate while its window exists, and that the window goes with the popup.

Not here: ArithmeticTests (3) and FaceDrawnTests (2), the drawing's (seat S6.4f's render serve).
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402

if os.name == "nt":
    import hostcardwindow  # noqa: E402
    import test_popup_opening_motion as original  # noqa: E402  (a module name: its classes are not collected here)
    BASE = original.WindowTests
else:
    BASE = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


@ON_HOST
class WindowOnHostTests(BASE):  # noqa: F821 (BASE is deleted below, so the original is not collected twice)
    def setUp(self):
        super().setUp()
        self.made, self.openings = [], None

    def make(self, **extra):
        from test_tray_popup import EN, FakeControl, WindowsTests
        window = hostcardwindow.HostCardPopup(control=FakeControl(WindowsTests.ROWS), strings=EN, log=extra.get("log"),
                                              held=extra.get("held"), openings=self.openings)
        self.made.append(window)
        self.addCleanup(window.destroy)
        return window

    def pump(self, seconds):
        for window in self.made:
            window.pump(seconds)

    def record_openings(self):
        if self.openings is None:
            self.openings = []
            for window in self.made:
                window.record_openings(self.openings)
        return self.openings

    def test_a_popup_is_kept_alive_while_its_window_exists(self):
        window = self.make()
        kept = window._kept()
        self.assertTrue(kept["held"] and kept["window"], "Windows may still call its window procedure")
        self.assertTrue(kept["its_own"], "the procedure Windows calls is the delegate the popup holds")
        hwnd = window.hwnd
        window.destroy()
        user32 = ctypes.WinDLL("user32")
        user32.IsWindow.argtypes, user32.IsWindow.restype = [ctypes.c_void_p], ctypes.c_int
        self.assertFalse(user32.IsWindow(hwnd), "and let go with its window")
        self.assertIsNone(window.hwnd)

    # the inherited tests, named here so the ledger can find each twin
    def test_it_fades_in_and_rises_frame_by_frame_and_ends_an_ordinary_window(self):
        super().test_it_fades_in_and_rises_frame_by_frame_and_ends_an_ordinary_window()

    def test_held_or_reduced_it_is_simply_there(self):
        super().test_held_or_reduced_it_is_simply_there()

    def test_closed_while_it_opens_it_leaves_nothing_behind(self):
        super().test_closed_while_it_opens_it_leaves_nothing_behind()

    def test_a_button_s_face_glides_to_the_pointer_and_to_a_press(self):
        super().test_a_button_s_face_glides_to_the_pointer_and_to_a_press()

    def test_held_a_face_changes_at_once(self):
        super().test_held_a_face_changes_at_once()


del BASE


if __name__ == "__main__":
    unittest.main()
