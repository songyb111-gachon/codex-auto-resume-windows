r"""v0.6.20: a picture drawn at a pinned scale is the window's own size on any display.

The render mode (gui/WindowRender.cs, OpenForRender) builds the window as a form and takes it off every screen, and
Form.SetBoundsCore holds a form to the largest window the screen allows (SystemInformation.MaxWindowTrackSize) even
there, while ClientSize keeps what was asked. On a CI runner's 1024 by 768 screen the 1500 by 996 window was drawn
1044 by 788, so every picture the fidelity check drew there was that size (dev CI 41145110604; test_motion_fidelity had
been skipped on CI until the stills were pinned). While RenderPinned the window is now sized by Windows itself
(SetWindowPos), which holds no frameless window off the screen to that.

The test pins a scale at which the window is larger than the largest window this machine's screens allow, so it holds
the limit on any display: one page at rest, and the client area frames.json records is the window's opening size at
that scale. Run on its own: it compiles the window once (csc) and draws one frame.
"""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

import motion_window  # noqa: E402

OPENING = (1000, 664)    # SettingsForm.OpeningWidth / OpeningHeight, at 96 dpi
PER_MONITOR = -4         # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: the window's own awareness (its manifest)


def largest_window() -> tuple:
    """(width, height) of the largest window Windows lets a per-monitor-aware window be here (SM_CXMAXTRACK and
    SM_CYMAXTRACK, in physical pixels)."""
    user32 = ctypes.windll.user32
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    before = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR))
    try:
        return user32.GetSystemMetrics(59), user32.GetSystemMetrics(60)
    finally:
        if before:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(before))


def scale_beyond(largest: tuple) -> float:
    """A scale, in quarters, at which the window's opening size is larger than `largest` both ways."""
    needed = max(largest[0] / OPENING[0], largest[1] / OPENING[1]) + 0.25
    return math.ceil(needed * 4) / 4


@unittest.skipIf(os.name != "nt" or not motion_window.CSC.is_file(), "the window is built with Windows' C# compiler")
class PinnedSizeTests(unittest.TestCase):
    def test_a_window_larger_than_every_screen_is_drawn_at_its_own_size(self):
        import make_screenshots
        import motion_fidelity
        largest = largest_window()
        scale = scale_beyond(largest)
        locale = "en"
        overview = motion_fidelity.still_path("overview", locale)
        frame = make_screenshots.read_png(overview)
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            exe = motion_window.compile_window(work / "build")
            out = work / "render"
            job = {"out": str(out / "frames"), "theme": "light", "design": "soft",
                   "forms": {locale: {"answers": motion_window.answers(locale)}}, "scale": scale,
                   "outer": [frame[0], frame[1]],
                   "chrome": motion_window.chrome({"window": {"still": str(overview.relative_to(make_screenshots.ROOT))}}),
                   "frames": motion_fidelity.pages_at_rest(locale)[:1]}
            result = motion_window.render(exe, job, out)
        wanted = [int(round(OPENING[0] * scale)), int(round(OPENING[1] * scale))]
        self.assertGreater(wanted[0], largest[0])
        self.assertEqual(result["client"], wanted,
                         "at scale %s on a machine whose largest window is %dx%d" % (scale, largest[0], largest[1]))

    def test_the_scale_outgrows_a_ci_runner_and_a_large_monitor(self):
        self.assertEqual(scale_beyond((1044, 788)), 1.5)
        self.assertGreater(OPENING[0] * scale_beyond((3860, 2180)), 3860)


if __name__ == "__main__":
    unittest.main()
