"""v0.6.23 (second round, F4): the icon's right-click menu and the popup's row menus fade and rise in, and fade out.

The window's menu of the same material has opened with a fade and a SPACING xs rise and closed with a press-time fade-out
since the first round (gui/SoftMenu.cs SoftMenuLayer, SoftLayerFade). The drawn menu (ui/popup/menuwindow.py) pushed alpha
255 once and was simply there and gone. Now a frame timer of its own lays the one picture down again at each step of the
fade (UpdateLayeredWindow with a constant alpha and a moved origin) - nothing is drawn again for a frame - and stops on
arrival; while it fades out nothing can touch it. Immediate with motion reduced and in High Contrast.

FadeTests drive the menu with Windows replaced and the clock the test's own. WindowTests make the real window far off every
screen, never activated (a submenu's way of showing), and count its frames: run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import brand  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import menuwindow, motion  # noqa: E402
from test_tray_menu_drawn import EN, entries, measure  # noqa: E402

TRANSITION, PRESS = brand.MOTION["transition_ms"], brand.MOTION["press_ms"]


class FakeUser32:
    def __init__(self):
        self.calls, self.style = [], 0

    def GetWindowLongW(self, hwnd, which):
        return self.style

    def SetWindowLongW(self, hwnd, which, style):
        self.calls.append(("SetWindowLongW", style))
        self.style = style
        return 1

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name,) + args[1:])
            return 1
        return call


class FadeTests(unittest.TestCase):
    def setUp(self, reduced=False, contrast=False):
        self.user32, self.now, self.blits, self.renders = FakeUser32(), [0.0], [], [0]
        for target, name, value in ((menuwindow, "_dll", lambda name: self.user32),
                                    (menuwindow, "_now_ms", lambda: self.now[0]),
                                    (menuwindow.look, "reduced_motion", lambda: reduced)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.menu = menuwindow.Menu()
        self.menu.hwnd, self.menu.contrast, self.menu.visible = 900, contrast, True
        self.menu._plan = popup.menu_layout(entries(), 1.5, measure)
        self.menu._origin = (300, 200)
        self.menu._blit = lambda: self.blits.append((self.menu._alpha, self.menu._below))
        self.menu.render = lambda: self.renders.__setitem__(0, self.renders[0] + 1)
        self.menu._tell = lambda event: None

    def frames(self, until):
        while self.menu._fade is not None and self.now[0] < until:
            self.now[0] += motion.GLIDE_FRAME_MS
            self.menu._handle(menuwindow.WM_TIMER, menuwindow.FADE_TIMER, 0)

    def timers(self, name):
        return [call for call in self.user32.calls if call[0] == name and call[1] == menuwindow.FADE_TIMER]

    def test_it_opens_faded_out_below_its_place_and_fades_and_rises_in_on_its_own_timer(self):
        self.menu._appear()
        rise = int(round(brand.SPACING["xs"] * 1.5))
        self.assertEqual((self.menu._alpha, self.menu._below), (0, rise))
        self.assertEqual(self.timers("SetTimer"), [("SetTimer", menuwindow.FADE_TIMER, motion.GLIDE_FRAME_MS, None)])
        self.frames(1000)
        alphas = [alpha for alpha, _ in self.blits]
        self.assertGreaterEqual(len(alphas), 8, "frame by frame")
        self.assertEqual(alphas, sorted(alphas))
        self.assertEqual([below for _, below in self.blits], sorted((below for _, below in self.blits), reverse=True))
        self.assertEqual(self.blits[-1], (255, 0), "whole and in place")
        self.assertIsNone(self.menu._fade)
        self.assertTrue(self.timers("KillTimer"), "the timer stops on arrival")
        self.assertEqual(self.renders[0], 0, "a frame of the fade draws nothing")

    def test_closed_it_fades_out_in_the_press_time_untouchable_then_hides(self):
        self.menu._appear()
        self.frames(1000)
        self.blits.clear()
        self.menu.close()
        self.assertFalse(self.menu.visible, "closed at once: nothing can be chosen any more")
        self.assertTrue(self.user32.style & menuwindow.WS_EX_TRANSPARENT, "a click goes through it")
        self.assertNotIn(("ShowWindow", menuwindow.SW_HIDE), self.user32.calls, "still on the screen, fading")
        closed_at = self.now[0]
        self.frames(closed_at + 1000)
        alphas = [alpha for alpha, _ in self.blits]
        self.assertGreaterEqual(len(alphas), 3)
        self.assertEqual(alphas, sorted(alphas, reverse=True))
        self.assertLessEqual(self.now[0] - closed_at, PRESS + motion.GLIDE_FRAME_MS, "in brand's press time")
        self.assertIn(("ShowWindow", menuwindow.SW_HIDE), self.user32.calls)
        self.assertFalse(self.user32.style & menuwindow.WS_EX_TRANSPARENT, "touchable again for the next opening")
        self.assertEqual(self.renders[0], 0)

    def test_opened_again_while_it_fades_out_it_fades_in_again(self):
        self.menu._appear()
        self.frames(1000)
        self.menu.close()
        self.now[0] += motion.GLIDE_FRAME_MS
        self.menu._handle(menuwindow.WM_TIMER, menuwindow.FADE_TIMER, 0)
        self.menu.visible = True
        self.menu._appear()
        self.assertEqual(self.menu._fade[0], "in")
        self.assertFalse(self.user32.style & menuwindow.WS_EX_TRANSPARENT)

    def test_a_refused_opening_is_hidden_at_once(self):
        self.menu._appear()
        self.frames(1000)
        self.menu.close(quietly=True)
        self.assertIn(("ShowWindow", menuwindow.SW_HIDE), self.user32.calls)
        self.assertIsNone(self.menu._fade)


class ReducedFadeTests(FadeTests):
    def setUp(self):
        super().setUp(reduced=True)

    def test_it_opens_faded_out_below_its_place_and_fades_and_rises_in_on_its_own_timer(self):
        self.menu._appear()
        self.assertEqual((self.menu._alpha, self.menu._below, self.menu._fade), (255, 0, None))
        self.assertEqual(self.timers("SetTimer"), [], "no timer at all")

    def test_closed_it_fades_out_in_the_press_time_untouchable_then_hides(self):
        self.menu._appear()
        self.menu.close()
        self.assertIn(("ShowWindow", menuwindow.SW_HIDE), self.user32.calls, "simply gone")
        self.assertEqual(self.timers("SetTimer"), [])

    def test_opened_again_while_it_fades_out_it_fades_in_again(self):
        self.menu._appear()
        self.menu.close()
        self.menu.visible = True
        self.menu._appear()
        self.assertIsNone(self.menu._fade, "nothing fades with motion reduced")


class ContrastFadeTests(ReducedFadeTests):
    def setUp(self):
        FadeTests.setUp(self, contrast=True)


class WindowTests(unittest.TestCase):
    def pump(self, seconds):
        from test_tray_popup import WindowsTests
        WindowsTests.pump(self, seconds)

    def test_the_real_menu_fades_in_on_its_timer_and_fades_out_and_hides(self):
        user32 = ctypes.WinDLL("user32")
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        menu = popup.Menu()
        menu.create()
        self.addCleanup(menu.destroy)
        menu.entries, menu.strings = entries(), dict(EN)
        menu._plan = menu._renderer.menu_layout(menu.entries, 1.0, "en")
        menu._origin = (-32000, -32000)
        alphas = []
        real = menu._blit

        def blit():
            alphas.append(menu._alpha)
            real()
        menu._blit = blit
        with mock.patch.object(menuwindow.look, "reduced_motion", return_value=False):
            menu._appear()
            menu._push()
            user32.ShowWindow(menu.hwnd, 4)                   # SW_SHOWNOACTIVATE, off every screen
            menu.visible = True
            self.pump(0.45)
            self.assertIsNone(menu._fade)
            self.assertGreaterEqual(len([alpha for alpha in alphas if 0 < alpha < 255]), 3, alphas)
            self.assertEqual(alphas[-1], 255)
            alphas.clear()
            menu.close()
            self.assertTrue(user32.IsWindowVisible(menu.hwnd), "fading out")
            self.pump(0.3)
            self.assertFalse(user32.IsWindowVisible(menu.hwnd), "and gone")
            self.assertEqual(alphas, sorted(alphas, reverse=True))
            self.assertIsNone(menu._fade)


if __name__ == "__main__":
    unittest.main()
