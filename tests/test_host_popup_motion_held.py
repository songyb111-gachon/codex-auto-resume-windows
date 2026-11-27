"""The real popup's frames held and let go, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twin of tests/test_popup_motion_held.py's WindowTests: the original's body through `super()`, the popup the host's
PopupWindow with its own real windows (tests/rustdiff/hostcardwindow.py, HostProbe.cs `popup_live`), far off every screen,
never activated, destroyed by the original's own `finally`, through gui_lock.sh (the main session's word of 2026-11-28).
What changed, and only that:

* `tray_popup.Popup` is a HostCardPopup for the test's body: made from its control layer, strings and `held`; its
  `create` is the host's (made already), its model the reference's, whose read outcome is sent as the core's snapshot;
* the test's own SendMessageW to the window (a tick, from outside) is made for real, the host's popup asked first with
  the test's `held` and clock of that moment (the host cannot call back into the test) and read again after it;
* `pump` runs the host's messages for the same time.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402

if os.name == "nt":
    import hostcardwindow  # noqa: E402
    import test_popup_motion_held as original  # noqa: E402  (a module name: its classes are not collected here)
    BASE, GATE_BASE, ICON_BASE = original.WindowTests, original.GateTests, original.IconReadingTests
else:
    BASE = GATE_BASE = ICON_BASE = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class _HostPopupClass:
    """tray_popup.Popup as the test's body makes one: a HostCardPopup, its `create` a no-op (the host made its windows)."""

    def __init__(self, made):
        self.made = made

    def __call__(self, control=None, strings=None, held=None, **extra):
        window = hostcardwindow.HostCardPopup(control=None, strings=strings, held=held, log=extra.get("log"))
        window.control = control
        window.create = lambda: None
        self.made.append(window)
        return window

    def __getattr__(self, name):
        return getattr(original.tray_popup.Popup, name)


@ON_HOST
class WindowOnHostTests(BASE):  # noqa: F821 (BASE is deleted below, so the original is not collected twice)
    def setUp(self):
        super().setUp()
        self.made = []
        real = ctypes.WinDLL

        def windll(name, *args, **kwargs):
            library = real(name, *args, **kwargs)
            if name.lower() != "user32":
                return library
            made = self.made
            send = library.SendMessageW

            def SendMessageW(hwnd, message, wparam, lparam):
                for window in made:
                    if window.hwnd == hwnd:
                        window.sync()
                send.argtypes = SendMessageW.argtypes
                answer = send(hwnd, message, wparam, lparam)
                for window in made:
                    if window.hwnd == hwnd:
                        window.sync()
                return answer
            SendMessageW.argtypes = None
            return types.SimpleNamespace(SendMessageW=SendMessageW)
        for target, name, value in ((original.tray_popup, "Popup", _HostPopupClass(self.made)),
                                    (original, "ctypes", types.SimpleNamespace(WinDLL=windll, c_void_p=ctypes.c_void_p,
                                                                               c_uint=ctypes.c_uint, c_size_t=ctypes.c_size_t,
                                                                               c_ssize_t=ctypes.c_ssize_t))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pump(self, seconds):
        for window in self.made:
            window.pump(seconds)

    # the inherited tests, named here so the ledger can find each twin
    def test_the_real_popup_stops_its_frames_within_a_tick_and_starts_them_again(self):
        super().test_the_real_popup_stops_its_frames_within_a_tick_and_starts_them_again()


class HostGate:
    """The test's stand-in popup (stand_in) on the host: every assignment a step of one history, run again from the start
    on a PopupWindow with no window for each question (HostProbe.cs popup_gate)."""

    FIELDS = {"_still": "still", "_reduced": "reduced", "_contrast": "contrast", "visible": "visible",
              "_frame_running": "frame_running"}

    def __init__(self, *, still=False, reduced=False, light="monitoring", scene=None):
        self.__dict__.update(_history=[["set", "visible", True], ["set", "reduced", reduced], ["set", "still", still],
                                       ["set", "glides", None], ["set", "frame_running", False], ["set", "state_age", 0.0],
                                       ["set", "light", light], ["set", "scene", scene]],
                             _last=None, _seventh=False)

    def __setattr__(self, name, value):
        history = self._history
        if name in self.FIELDS:
            history.append(["set", self.FIELDS[name], bool(value)])
        elif name == "_state_since":
            history.append(["set", "state_age", time.monotonic() - value])
        elif name == "_switches":
            history.append(["set", "switches", [[list(target), bool(on)] for target, on in value.items()]])
        elif name == "_painted_plan":
            history.append(["set", "painted_plan", None])
        elif name == "_presses":
            self.__dict__["_seventh"] = bool(value.press(0))        # the stand-in press answers yes: the next is the seventh
        elif name == "held":
            if value is None:
                kind = "none"
            else:
                try:
                    kind = "true" if value() else "false"
                except Exception:
                    kind = "raise"
            history.append(["set", "held", kind])
        self.__dict__[name] = value

    def _ask(self, step):
        self._history.append(step)
        self.__dict__["_last"] = surfacehost.SERVE.ask("popup_gate", steps=self._history)[-1]
        return self._last

    @property
    def _frame_running(self):
        return self._last["frame_running"] if self._last else False

    @property
    def _glides(self):
        return {tuple(target): True for target in (self._last["glides"] if self._last else [])}

    @property
    def _sweep_since(self):
        return self._last["sweep_since"] if self._last else None

    @property
    def _design(self):
        return original.tray_popup.window.design_setting()

    def synced(self):
        found = self._ask(["sync"])
        return types.SimpleNamespace(set=int(found["set"]), killed=int(found["killed"]))

    def frame(self):
        return self._ask(["frame"])["answer"]

    def _follow_switches(self, plan):
        self._ask(["follow", [{"kind": item["kind"], "target": list(item["target"]), "checked": bool(item["checked"])}
                              for item in plan["items"]]])

    def _title_press(self, now):
        if self._seventh:
            self._history.append(["set", "presses", float(now)])
        self._ask(["title_press", float(now)])

    def _ask_still(self):
        return self._ask(["ask_still"])["answer"]


@ON_HOST
class GateOnHostTests(GATE_BASE):  # noqa: F821
    """GateTests: the originals' bodies through super(), stand_in a HostGate and synced the host's SyncFrames (its frame
    timer's SetTimer and KillTimer counted from the host's record, as the reference's FakeUser32 counts them)."""

    def setUp(self):
        super().setUp()
        for name, value in (("stand_in", lambda **kw: HostGate(**kw)), ("synced", lambda made: made.synced())):
            patcher = mock.patch.object(original, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_breathing_light_runs_the_frame_timer_and_battery_saver_or_a_lock_stops_it(self):
        super().test_the_breathing_light_runs_the_frame_timer_and_battery_saver_or_a_lock_stops_it()

    def test_the_day_scene_holds_still(self):
        super().test_the_day_scene_holds_still()

    def test_a_running_timer_is_stopped_once_it_is_held(self):
        super().test_a_running_timer_is_stopped_once_it_is_held()

    def test_the_light_is_drawn_still_while_held(self):
        super().test_the_light_is_drawn_still_while_held()

    def test_a_switch_s_change_does_not_glide_while_held(self):
        super().test_a_switch_s_change_does_not_glide_while_held()

    def test_the_seventh_press_shows_no_sweep_while_held(self):
        super().test_the_seventh_press_shows_no_sweep_while_held()

    def test_it_asks_on_each_opening_and_a_question_that_fails_holds_nothing(self):
        super().test_it_asks_on_each_opening_and_a_question_that_fails_holds_nothing()
        # and the host's own: asked in ReadLook, and again on the one-second tick
        window = (ROOT / "gui" / "PopupWindow.cs").read_text(encoding="utf-8")
        read_look = window.split("internal void ReadLook()", 1)[1].split("\n        }\n", 1)[0]
        self.assertIn("Still = AskStill();", read_look)
        messages = (ROOT / "gui" / "PopupMessages.cs").read_text(encoding="utf-8")
        tick = messages.split("else if (wparam == TimerTick)", 1)[1].split("else if", 1)[0]
        self.assertIn("Still = AskStillNow();", tick, "and again every second while it is open")


class HostIconReading:
    """AnimationMixin as IconReadingTests makes one: its session flags, and _popup_held the host icon's PopupHeld with
    battery saver answering as the test's patched animation.battery_saver."""

    def _popup_held(self):
        from codex_auto_resume.ui.tray import animation
        return surfacehost.SERVE.ask("icon_held", locked=bool(getattr(self, "_session_locked", False)),
                                     away=bool(getattr(self, "_session_away", False)), saver=bool(animation.battery_saver()))


@ON_HOST
class IconReadingOnHostTests(ICON_BASE):  # noqa: F821
    def test_the_icon_hands_the_popup_its_own_reading(self):
        with mock.patch.object(original, "AnimationMixin", HostIconReading):
            super().test_the_icon_hands_the_popup_its_own_reading()

    def test_the_popup_is_made_with_it(self):
        super().test_the_popup_is_made_with_it()
        # and the host's own: the icon makes its popup with its reading, and the reading is battery saver and the session
        icon = (ROOT / "gui" / "TrayIcon.cs").read_text(encoding="utf-8")
        self.assertIn("new PopupWindow(strings, locale, letters, Days, PopupHeld)", icon)
        held = icon.split("internal bool PopupHeld()", 1)[1].split("\n        }\n", 1)[0]
        self.assertIn("TrayMotion.MotionAllowed(batterySaver: AskBatterySaver(), locked: SessionLocked || SessionAway)", held)


del BASE, GATE_BASE, ICON_BASE


if __name__ == "__main__":
    unittest.main()
