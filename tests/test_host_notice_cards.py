"""The notification cards clicked and held, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twins of tests/test_notice_click.py's CardTests and tests/test_notice_stay.py's CardTests: the originals' bodies through
`super()`, the card stack the host's CardStack (HostProbe.cs `card_stack`) and the card's motion the host's CardMotion
(`card_motion`). What changed, and only that:

* `notice_window.CardStack` is a HostCardStack: every call one step of a history the probe runs again from the start on a
  CardStack made by its own Create (its window a message-only one) in SurfaceScreen's probe mode - every card window made
  and never shown - with the test's clock, place and look; a notice reaches it as the core's `notice` event (its view as
  notice_card.view makes it); a card is a HostCard (its view's click and actions, its size, its plan's targets, its
  motion's phase, its body window by number); what the host posts (`notice_action {uri}`) goes to the test's `on_action`;
* `notice_card.CardMotion` is the host's (for the hold that waits for a click).
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402

if os.name == "nt":
    import test_notice_click as click_original  # noqa: E402  (module names: their classes are not collected here)
    import test_notice_stay as stay_original  # noqa: E402
    from test_host_card_focus import _plain, notice_event  # noqa: E402
    CLICK, STAY = click_original.CardTests, stay_original.CardTests
else:
    CLICK = STAY = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class _Motion:
    def __init__(self, card):
        self._card = card

    @property
    def phase(self):
        return self._card._state()["phase"]


class _Body:
    def __init__(self, index):
        self.hwnd = ("body", index)


class HostCard:
    def __init__(self, stack, index):
        self._stack, self._index = stack, index
        self.motion, self.body = _Motion(self), _Body(index)

    def _state(self):
        return self._stack._last["cards"][self._index]

    @property
    def vm(self):
        state = self._state()
        return {"click": state["click"], "actions": state["actions"]}

    @property
    def size(self):
        return tuple(int(n) for n in self._state()["size"])

    @property
    def plan(self):
        return {"targets": [(tuple(target), tuple(int(n) for n in rect)) for target, rect in self._state()["targets"]]}


class HostCardStack:
    def __init__(self, clock=None, locate=None, appearance=None, on_action=None, worker=None, **unused):
        self.clock, self.locate, self.appearance = clock or (lambda: 0.0), locate, appearance
        self.on_action = on_action or (lambda *unused: None)
        self.history, self.made, self.views, self._last, self.posted = [], None, [], None, 0

    def create(self):
        self.made = {"where": _plain(self.locate()), "appearance": _plain(self.appearance())}
        return self

    def _go(self, step):
        self.history.append(step)
        found = surfacehost.SERVE.ask("card_stack", steps=self.history, **self.made)
        self._last = found[-1]
        for name, fields in self._last["posted"][self.posted:]:
            if name != "notice_action":
                continue                                 # notice_complete: the core's own bookkeeping, no callback here
            self.on_action(fields["uri"])
        self.posted = len(self._last["posted"])
        while len(self.views) < len(self._last["cards"]):
            self.views.append(HostCard(self, len(self.views)))
        return self._last["returned"]

    def show(self, notice):
        index = self._go(["show", float(self.clock()), notice_event(notice)])
        return None if index is None else self.views[int(index)]

    def _handle(self, hwnd, message, wparam, lparam):
        return int(self._go(["message", float(self.clock()), int(hwnd[1]), int(message), int(wparam), int(lparam or 0)]))

    def _tick(self):
        self._go(["tick", float(self.clock())])

    def hold(self):
        return self._go(["hold", float(self.clock())])

    @property
    def cards(self):
        return [view for view in self.views if self._last["cards"][view._index]["living"]]

    def destroy(self):
        pass


class HostCardMotion:
    """notice_card.CardMotion over the host's: every call a step of one history, answered in order."""

    def __init__(self, now_ms, hold_ms=None, **unused):
        self._made = {"now": float(now_ms), "hold": "inf" if hold_ms is not None and math.isinf(hold_ms) else float(hold_ms)}
        self._steps = []

    def _ask(self, step):
        self._steps.append(step)
        return surfacehost.SERVE.ask("card_motion", steps=self._steps, **self._made)[-1]

    def frame(self, now):
        return types.SimpleNamespace(alpha=self._ask(["frame", float(now)]))

    @property
    def gone(self):
        return self._ask(["gone"])

    def wait_ms(self, now):
        return self._ask(["wait", float(now)])

    def pause(self, now, paused):
        self._ask(["pause", float(now), bool(paused)])

    def retire(self, now):
        self._ask(["retire", float(now)])


@ON_HOST
class CardClickOnHostTests(CLICK):  # noqa: F821
    def setUp(self):
        super().setUp()
        self.window = types.SimpleNamespace(CardStack=HostCardStack, WM_LBUTTONDOWN=self.window.WM_LBUTTONDOWN,
                                            WM_LBUTTONUP=self.window.WM_LBUTTONUP, WM_RBUTTONUP=self.window.WM_RBUTTONUP)

    def test_a_click_on_the_face_opens_where_the_notice_is_about_and_the_card_goes(self):
        super().test_a_click_on_the_face_opens_where_the_notice_is_about_and_the_card_goes()

    def test_a_button_still_does_only_what_it_says(self):
        super().test_a_button_still_does_only_what_it_says()

    def test_a_right_click_and_a_demo_s_face_open_nothing(self):
        super().test_a_right_click_and_a_demo_s_face_open_nothing()


@ON_HOST
class CardStayOnHostTests(STAY):  # noqa: F821
    def test_a_hold_until_clicked_never_runs_out_and_asks_for_no_timer(self):
        motion_module = types.SimpleNamespace(CardMotion=HostCardMotion, UNTIL_CLICKED=stay_original.notice_card.UNTIL_CLICKED,
                                              EXIT_MS=stay_original.notice_card.EXIT_MS)
        with mock.patch.object(stay_original, "notice_card", motion_module):
            super().test_a_hold_until_clicked_never_runs_out_and_asks_for_no_timer()

    def test_the_card_of_a_notice_that_stays_holds_until_it_is_clicked(self):
        from codex_auto_resume import notice_window
        with mock.patch.object(notice_window, "CardStack", HostCardStack):
            super().test_the_card_of_a_notice_that_stays_holds_until_it_is_clicked()


del CLICK, STAY


if __name__ == "__main__":
    unittest.main()
