"""v0.6.23 (second round, F1): the popup's light, scene, glides and sweep hold still under battery saver and a locked session.

Standard H13. The icon has held its own motion for both since v0.6.5 (ui/tray/motion.py icon_motion_allowed); the popup asked
only Reduce motion and High Contrast, so on battery saver its light breathed and its day scene moved thirty times a second.
It now adds the icon's own reading (`held`, ui/tray/clicks.py _popup_held) to its frame gate, asked on each opening and on
its one-second tick. The battery and the lock are the test's own answers; nothing reads this machine's power or session.

Part window test (WindowTests opens a real popup far off every screen, without activating it): run on its own, through
gui_lock.sh.
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

from codex_auto_resume.ui import popup as tray_popup  # noqa: E402
from codex_auto_resume.ui.popup import window as popup_window  # noqa: E402
from codex_auto_resume.ui.tray import clicks as tray_clicks  # noqa: E402
from codex_auto_resume.ui.tray.animation import AnimationMixin  # noqa: E402
# Imported here, not first inside a frame's wait: under load its first import took seconds in the middle of a fade, and
# no timer of the window could come while it ran (2026-11-13, half the cores spinning). The module, not its classes.
import test_tray_popup  # noqa: E402,F401


class FakeUser32:
    def __init__(self):
        self.set, self.killed = 0, 0

    def SetTimer(self, *unused):
        self.set += 1

    def KillTimer(self, *unused):
        self.killed += 1


def stand_in(*, still=False, reduced=False, light="monitoring", scene=None):
    made = tray_popup.Popup.__new__(tray_popup.Popup)
    made.visible, made._reduced, made._still, made._glides, made.hwnd, made._frame_running = True, reduced, still, {}, 1, False
    made._state_since = time.monotonic()
    made._vm = {"light": light, "scene": scene}
    return made


def synced(made):
    user32 = FakeUser32()
    with mock.patch.object(popup_window, "_dll", return_value=user32):
        made._sync_frames()
    return user32


class GateTests(unittest.TestCase):
    def test_the_breathing_light_runs_the_frame_timer_and_battery_saver_or_a_lock_stops_it(self):
        self.assertEqual(synced(stand_in()).set, 1, "a breathing light runs the frame timer")
        self.assertEqual(synced(stand_in(still=True)).set, 0, "held: no frame timer")

    def test_the_day_scene_holds_still(self):
        self.assertEqual(synced(stand_in(light="paused", scene="seollal")).set, 1)
        self.assertEqual(synced(stand_in(light="paused", scene="seollal", still=True)).set, 0)

    def test_a_running_timer_is_stopped_once_it_is_held(self):
        made = stand_in()
        synced(made)
        self.assertTrue(made._frame_running)
        made._still = True
        user32 = synced(made)
        self.assertEqual(user32.killed, 1)
        self.assertFalse(made._frame_running)

    def test_the_light_is_drawn_still_while_held(self):
        made = stand_in(still=True)
        made._state_since = time.monotonic() - 1.3
        self.assertEqual(made.frame(), tray_popup.halo("monitoring", 0, 0, reduced=True, design=made._design))

    def test_a_switch_s_change_does_not_glide_while_held(self):
        made = stand_in(still=True)
        made._switches = {("check", "a"): True}
        plan = {"items": [{"kind": "switch", "target": ("check", "a"), "checked": False}]}
        made._follow_switches(plan)
        self.assertEqual(made._glides, {})
        made._still, made._switches = False, {("check", "a"): True}
        made._follow_switches(plan)
        self.assertIn(("check", "a"), made._glides)

    def test_the_seventh_press_shows_no_sweep_while_held(self):
        made = stand_in(still=True)
        made._contrast, made._painted_plan = False, None
        made._sync_frames, made._update = (lambda: None), (lambda: None)
        made._presses = mock.Mock(press=lambda now: True)
        made._title_press(1000.0)
        self.assertIsNone(made._sweep_since)

    def test_it_asks_on_each_opening_and_a_question_that_fails_holds_nothing(self):
        made = stand_in()
        made.held = lambda: True
        self.assertTrue(made._ask_still())
        made.held = mock.Mock(side_effect=OSError)
        self.assertFalse(made._ask_still())
        made.held = None
        self.assertFalse(made._ask_still())
        source = Path(popup_window.__file__).read_text(encoding="utf-8")
        self.assertIn("self._still = self._ask_still()", source.split("def _read_look", 1)[1].split("def ", 1)[0])
        messages = Path(popup_window.__file__).with_name("messages.py").read_text(encoding="utf-8")
        tick = messages.split("elif wparam == TIMER_TICK:", 1)[1].split("elif", 1)[0]
        self.assertIn("self._still = self._ask_still()", tick, "and again every second while it is open")


class IconReadingTests(unittest.TestCase):
    def icon(self, locked=False, away=False):
        made = AnimationMixin.__new__(AnimationMixin)
        made._session_locked, made._session_away = locked, away
        return made

    def test_the_icon_hands_the_popup_its_own_reading(self):
        from codex_auto_resume.ui.tray import animation
        with mock.patch.object(animation, "battery_saver", return_value=False):
            self.assertFalse(self.icon()._popup_held())
            self.assertTrue(self.icon(locked=True)._popup_held())
            self.assertTrue(self.icon(away=True)._popup_held())
        with mock.patch.object(animation, "battery_saver", return_value=True):
            self.assertTrue(self.icon()._popup_held())

    def test_the_popup_is_made_with_it(self):
        self.assertIn("held=self._popup_held", Path(tray_clicks.__file__).read_text(encoding="utf-8"))
        self.assertIn("icon_motion_allowed(battery_saver=battery_saver()",
                      Path(sys.modules[AnimationMixin.__module__].__file__).read_text(encoding="utf-8"))


class WindowTests(unittest.TestCase):
    """Windows' animation setting is the test's own: GitHub's runners have it off, which holds every motion anyway."""

    def setUp(self):
        patcher = mock.patch.object(tray_popup.theme, "reduced_motion", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pump(self, seconds):
        from test_tray_popup import WindowsTests
        WindowsTests.pump(self, seconds)

    def test_the_real_popup_stops_its_frames_within_a_tick_and_starts_them_again(self):
        from test_tray_popup import EN, FakeControl, WindowsTests
        flag = {"held": False}
        window = tray_popup.Popup(control=FakeControl(WindowsTests.ROWS), strings=EN, held=lambda: flag["held"])
        window.create()
        user32 = ctypes.WinDLL("user32")
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        try:
            window.model.apply_outcome(("read",), tray_popup.perform(("read",), window.control), time.time())
            window.show(activate=False, origin=(-32000, -32000))
            deadline = time.monotonic() + 5                # its opening first, by the clock, however busy the runner
            while window._opening is not None and time.monotonic() < deadline:
                self.pump(0.02)
            self.assertIsNone(window._opening)
            self.assertTrue(window._frame_running, "the light breathes")
            self.assertEqual(window._frame_ms, tray_popup.FRAME_MS, "on the light's own frames")
            flag["held"] = True
            user32.SendMessageW(window.hwnd, tray_popup.WM_TIMER, tray_popup.TIMER_TICK, 0)
            self.assertTrue(window._still)
            self.assertFalse(window._frame_running, "battery saver or a lock: no frame timer")
            flag["held"] = False
            user32.SendMessageW(window.hwnd, tray_popup.WM_TIMER, tray_popup.TIMER_TICK, 0)
            self.assertTrue(window._frame_running, "and it moves again by itself")
            window.hide()
            flag["held"] = True
            window.show(activate=False, origin=(-32000, -32000))
            self.assertIsNone(window._opening, "opened while held, it is simply there")
            self.pump(0.1)
            self.assertFalse(window._frame_running, "opened while held, it starts still")
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
