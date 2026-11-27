"""The drawn menu's fade, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twins of tests/test_menu_opening_motion.py's FadeTests, ReducedFadeTests and ContrastFadeTests: the originals' bodies
through `super()`, the menu the host's MenuWindow (HostProbe.cs `menu_fade`), every step of the test one step of a
history the probe runs again from the start for each question. As the originals drive the reference's menu with Windows
replaced and the clock the test's own, the host's menu runs in SurfaceScreen's probe mode - its window the number 900, as
the test's, every call it makes of Windows recorded and none made - with its clock the test's `now`. What changed, and
only that:

* `self.menu` is a HostMenuFade: its `_appear`, `close`, `_handle` (the fade's WM_TIMER), `visible`, `_alpha`, `_below`
  and `_fade` the host's; its plan the host renderer's of the same entries at 1.5, at (300, 200);
* `self.user32.calls` are the host's recorded calls in the reference's words (SetTimer, KillTimer, ShowWindow,
  SetWindowLongW), `self.user32.style` the extended style the host set;
* `self.blits` are the host's own blits (each UpdateLayeredWindow's alpha, and its place's drop below the origin);
* `self.renders` counts the steps in which the host drew its picture again (it is drawn once before the first step and
  marked; a step that draws it again changes the mark).

WindowOnHostTests (S6.4d6) twins WindowTests, the real menu window: `popup.Menu` makes tests/rustdiff/hostlive.py's
HostLiveMenu - ONE host MenuWindow made by its own Create and kept on a thread of the probe's own (HostProbe.cs `menu_live`),
shown by the test's own ShowWindow(SW_SHOWNOACTIVATE) at (-32000, -32000) and read by its own IsWindowVisible, exactly as
the original shows and reads the reference's (the main session's word of 2026-11-28; inside gui_lock.sh, never a dialog,
destroyed in the test's own cleanup). What changed, and only that: the test's `pump` runs the host's menu thread's messages
for the same time; its `recorded("opening")` / `recorded("closing")` lists are filled with the host's fade frames, each
read at the frame's own instant, in the reference's words.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
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
    import test_menu_opening_motion as original  # noqa: E402  (a module name: its classes are not collected here)
    FADE, REDUCED, CONTRAST = original.FadeTests, original.ReducedFadeTests, original.ContrastFadeTests
    WINDOW = original.WindowTests
else:
    FADE = REDUCED = CONTRAST = WINDOW = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
_ULW = re.compile(r"^UpdateLayeredWindow \S+ (-?\d+) (-?\d+) (\d+) (\d+) (\d+)$")


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _call(line):
    """A recorded call in the reference FakeUser32's words: (name, *its arguments after the window)."""
    parts = line.split()
    values = tuple(int(part) if re.fullmatch(r"-?\d+", part) else part for part in parts[2:])
    if parts[0] == "SetTimer":
        values += (None,)
    return (parts[0],) + values


class HostUser32:
    def __init__(self):
        self.calls, self.style = [], 0


class HostMenuFade:
    """The test's menu on the host: every step one step of a history run again from the start for each question."""

    def __init__(self, test, reduced, contrast):
        self.__dict__.update(_test=test, _history=[], _reduced=reduced, contrast=contrast, _seen=0, _last=None)

    def _go(self, step):
        test = self._test
        self._history.append(step)
        from test_tray_menu_drawn import EN, entries
        found = surfacehost.SERVE.ask("menu_fade", entries=_plain(entries()), strings=dict(EN), scale=1.5, origin=[300, 200],
                                      contrast=bool(self.contrast), reduced=bool(self._reduced), steps=self._history)
        origin_y = int(found["origin"][1])
        for line in found["records"][self._seen:]:
            blit = _ULW.match(line)
            if blit:
                test.blits.append((int(blit.group(5)), int(blit.group(2)) - origin_y))
            else:
                test.user32.calls.append(_call(line))
        self.__dict__["_seen"] = len(found["records"])
        test.user32.style = int(found["style"])
        last = found["steps"][-1]
        if last["drew"]:
            test.renders[0] += 1
        self.__dict__["_last"] = last

    def _now(self):
        return float(self._test.now[0])

    def _appear(self):
        self._go(["appear", self._now()])

    def close(self, quietly=False):
        self._go(["close", self._now(), bool(quietly)])

    def _handle(self, message, wparam, lparam):
        if message != original.menuwindow.WM_TIMER or wparam != original.menuwindow.FADE_TIMER:
            raise AssertionError("only the fade's timer is handed to the host's menu here")
        self._go(["timer", self._now()])
        return 0

    def __setattr__(self, name, value):
        if name == "visible":
            self._go(["visible", self._now(), bool(value)])
        else:
            self.__dict__[name] = value

    @property
    def visible(self):
        return self._last["visible"] if self._last else True

    @property
    def _alpha(self):
        return int(self._last["alpha"]) if self._last else 255

    @property
    def _below(self):
        return int(self._last["below"]) if self._last else 0

    @property
    def _fade(self):
        way = self._last["fade"] if self._last else None
        return None if way is None else (way,)


class HostFade:
    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        reduced = bool(original.menuwindow.look.reduced_motion())
        self.user32 = HostUser32()
        self.menu = HostMenuFade(self, reduced, self.menu.contrast)


@ON_HOST
class FadeOnHostTests(HostFade, FADE):  # noqa: F821
    def test_it_opens_faded_out_below_its_place_and_fades_and_rises_in_on_its_own_timer(self):
        super().test_it_opens_faded_out_below_its_place_and_fades_and_rises_in_on_its_own_timer()

    def test_closed_it_fades_out_in_the_press_time_untouchable_then_hides(self):
        super().test_closed_it_fades_out_in_the_press_time_untouchable_then_hides()

    def test_opened_again_while_it_fades_out_it_fades_in_again(self):
        super().test_opened_again_while_it_fades_out_it_fades_in_again()

    def test_a_refused_opening_is_hidden_at_once(self):
        super().test_a_refused_opening_is_hidden_at_once()


@ON_HOST
class ReducedFadeOnHostTests(HostFade, REDUCED):  # noqa: F821
    def test_it_opens_faded_out_below_its_place_and_fades_and_rises_in_on_its_own_timer(self):
        super().test_it_opens_faded_out_below_its_place_and_fades_and_rises_in_on_its_own_timer()

    def test_closed_it_fades_out_in_the_press_time_untouchable_then_hides(self):
        super().test_closed_it_fades_out_in_the_press_time_untouchable_then_hides()

    def test_opened_again_while_it_fades_out_it_fades_in_again(self):
        super().test_opened_again_while_it_fades_out_it_fades_in_again()


@ON_HOST
class ContrastFadeOnHostTests(HostFade, CONTRAST):  # noqa: F821
    pass


class PopupOnHost:
    """The reference popup package with its Menu the host's live one; everything else is the reference's."""

    def __init__(self, reference, make):
        self._reference, self.Menu = reference, make

    def __getattr__(self, name):
        return getattr(self._reference, name)


@ON_HOST
class WindowOnHostTests(WINDOW):  # noqa: F821
    def setUp(self):
        super().setUp()
        self._recorders, self._menus = {}, []

        def make(**keywords):
            menu = hostlive.HostLiveMenu(recorders=self._recorders, **keywords)
            self._menus.append(menu)
            return menu
        patcher = unittest.mock.patch.object(original, "popup", PopupOnHost(original.popup, make))
        patcher.start()
        self.addCleanup(patcher.stop)

    def pump(self, seconds):
        """The host's menu thread runs its messages for `seconds`, as the original's own thread runs the reference's."""
        for menu in self._menus:
            menu.pump(seconds)

    def recorded(self, name):
        """The host's fade frames as motion.opening / motion.closing answered them, in the reference's words."""
        seen = []
        self._recorders[name] = seen
        return seen

    def test_the_real_menu_fades_in_on_its_timer_and_fades_out_and_hides(self):
        super().test_the_real_menu_fades_in_on_its_timer_and_fades_out_and_hides()


del FADE, REDUCED, CONTRAST, WINDOW


if __name__ == "__main__":
    unittest.main()
