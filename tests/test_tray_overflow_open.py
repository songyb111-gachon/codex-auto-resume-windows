"""The notification-area icon moves in the overflow flyout while the flyout is open (v0.6.18).

Rule 2 of v0.6.5's motion holds an icon Windows keeps in the overflow flyout still, "because nobody sees it there",
and since v0.6.5 the tick asked only Windows' own setting for the icon (IconPlacement). New icons land in the flyout,
the installed watcher's among them, and the owner looks at it by opening the flyout - where it stood still in every
state: "트레이 아이콘이 또 가만히 있는거 같아". Somebody sees it there while the flyout is open, so it moves then,
and is held still again once the flyout is closed. Reduce motion and Windows' animation setting still hold it still.

Everything here is faked: never this desktop's flyout, registry, shell or timers.
"""
from __future__ import annotations

import ctypes as C
import types
import unittest
import unittest.mock

from codex_auto_resume import tray_place as place
from codex_auto_resume.ui import popup, tray
from codex_auto_resume.ui.tray import animation


class FakeUser32:
    """Timers on a window that does not exist, recorded instead of set."""

    def __init__(self):
        self.timers = {}

    def SetTimer(self, hwnd, ident, interval, proc):
        self.timers[ident] = interval
        return ident

    def KillTimer(self, hwnd, ident):
        self.timers.pop(ident, None)
        return True


class OpenFlyoutTickTests(unittest.TestCase):
    """The one-second tick, for an icon Windows keeps in the overflow flyout."""

    def tick(self, *, flyout_open, reduced=False, state_snapshot=None):
        icon = tray.Tray(strings={})
        icon._hwnd = 12345
        icon._frames = object.__new__(tray.IconFrames)
        icon._placement = types.SimpleNamespace(overflowed=lambda: True)     # in the flyout, never this registry
        fake = FakeUser32()
        # create=True: before the fix the tick never asks, and the test fails on what it asserts, not on a name.
        with unittest.mock.patch.object(popup, "reduced_motion", lambda: reduced), \
                unittest.mock.patch.object(popup, "high_contrast", lambda: False), \
                unittest.mock.patch.object(animation, "battery_saver", lambda: False), \
                unittest.mock.patch.object(popup, "icon_rect", lambda hwnd, uid=1: (0, 0, 16, 16)), \
                unittest.mock.patch.object(animation, "overflow_open", lambda: flyout_open, create=True), \
                unittest.mock.patch.object(animation, "_dll", lambda name: fake):
            icon._observe(state_snapshot or {"enabled": True})
            icon._sync_motion()
        return icon, fake

    def test_an_icon_in_the_open_flyout_moves_and_its_frame_timer_runs(self):
        """The owner's case: the watcher's icon in the flyout, the flyout open, the icon watching."""
        icon, fake = self.tick(flyout_open=True)
        self.assertEqual(icon._icon_state, "watching")
        self.assertTrue(icon._motion_allowed, "an icon somebody sees in the open flyout must move")
        self.assertIn(tray.TIMER_FRAME, fake.timers)

    def test_every_moving_state_moves_in_the_open_flyout(self):
        for snapshot, state in (({"enabled": True}, "watching"), ({"enabled": True, "running": 1}, "recovering")):
            with self.subTest(state):
                icon, fake = self.tick(flyout_open=True, state_snapshot=snapshot)
                self.assertEqual(icon._icon_state, state)
                self.assertTrue(icon._motion_allowed)
                self.assertIn(tray.TIMER_FRAME, fake.timers)

    def test_the_closed_flyout_still_holds_it_still(self):
        icon, fake = self.tick(flyout_open=False)
        self.assertFalse(icon._motion_allowed)
        self.assertNotIn(tray.TIMER_FRAME, fake.timers)

    def test_reduce_motion_or_windows_animations_off_hold_it_still_in_the_open_flyout(self):
        """popup.reduced_motion is the product's Reduce motion or Windows' "Show animations" off."""
        icon, fake = self.tick(flyout_open=True, reduced=True)
        self.assertFalse(icon._motion_allowed)
        self.assertNotIn(tray.TIMER_FRAME, fake.timers)

    def test_the_icon_asks_whether_the_flyout_is_open(self):
        """The tick itself asks: an icon in the flyout is held still only while overflow_open says it is closed."""
        icon = tray.Tray(strings={})
        icon._placement = types.SimpleNamespace(overflowed=lambda: True)
        asked = []
        with unittest.mock.patch.object(animation, "overflow_open", lambda: asked.append(1) or True, create=True):
            self.assertFalse(icon._overflowed())
        self.assertEqual(asked, [1])
        icon._placement = types.SimpleNamespace(overflowed=lambda: False)
        with unittest.mock.patch.object(animation, "overflow_open", lambda: asked.append(2) or False, create=True):
            self.assertFalse(icon._overflowed())
        self.assertEqual(asked, [1], "an icon on the taskbar never asks about the flyout")


class Function:
    """A DLL function: callable, and taking argtypes and restype as ctypes' do."""

    def __init__(self, body):
        self.body = body

    def __call__(self, *args):
        return self.body(*args)


class FakeWindows:
    """user32 and dwmapi as overflow_open asks them: [(class name, visible, cloaked)], one per window, in z-order."""

    def __init__(self, windows, *, fail=False):
        self.windows, self.fail = list(windows), fail
        self.FindWindowExW = Function(self._find)
        self.IsWindowVisible = Function(self._visible)
        self.DwmGetWindowAttribute = Function(self._attribute)

    def __call__(self, name):
        return self

    def _find(self, parent, after, klass, title):
        if self.fail:
            raise OSError("FindWindowExW")
        start = 0 if not after else after - 100 + 1
        for index in range(start, len(self.windows)):
            if self.windows[index][0] == klass:
                return 100 + index
        return 0

    def _visible(self, hwnd):
        return self.windows[hwnd - 100][1]

    def _attribute(self, hwnd, attribute, pointer, size):
        assert attribute == place.DWMWA_CLOAKED
        C.cast(pointer, C.POINTER(C.c_ulong))[0] = 1 if self.windows[hwnd - 100][2] else 0
        return 0


class OverflowOpenTests(unittest.TestCase):
    """Whether the flyout is open: its own window shown and not cloaked, on Windows 11 or 10."""

    def setUp(self):
        self.WIN11, self.WIN10 = place.OVERFLOW_WINDOWS

    def test_the_shown_flyout_is_open(self):
        self.assertTrue(place.overflow_open(FakeWindows([(self.WIN11, True, False)])))
        self.assertTrue(place.overflow_open(FakeWindows([(self.WIN10, True, False)])))

    def test_a_hidden_or_cloaked_flyout_is_closed(self):
        self.assertFalse(place.overflow_open(FakeWindows([(self.WIN11, False, False)])))
        self.assertFalse(place.overflow_open(FakeWindows([(self.WIN11, True, True)])))

    def test_any_taskbar_s_open_flyout_counts(self):
        """One flyout window per taskbar: a closed one first does not hide an open one after it."""
        self.assertTrue(place.overflow_open(FakeWindows([(self.WIN11, False, False), ("Other", True, False),
                                                         (self.WIN11, True, False)])))
        self.assertFalse(place.overflow_open(FakeWindows([(self.WIN11, False, False), ("Other", True, False),
                                                          (self.WIN11, True, True)])))

    def test_no_flyout_or_no_answer_is_closed(self):
        self.assertFalse(place.overflow_open(FakeWindows([])))
        self.assertFalse(place.overflow_open(FakeWindows([("Other", True, False)])))
        self.assertFalse(place.overflow_open(FakeWindows([(self.WIN11, True, False)], fail=True)))

    def test_the_two_class_names_are_windows_own(self):
        self.assertEqual(place.OVERFLOW_WINDOWS, ("TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow"))


if __name__ == "__main__":
    unittest.main()
