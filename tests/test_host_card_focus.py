"""Who has the keyboard around a card, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twins of tests/test_card_focus.py: the originals' bodies through `super()`, the card host the host's CardStack
(HostProbe.cs `card_focus`). What changed, and only that - the test module's `stack` and `win32` are the host's:

* `stack.CardStack` is a HostStack: every call one step of a history the probe runs again from the start on a CardStack
  whose Focus answers what the test's `focus` answered, in order, each asked of the test once when the host first asks it
  (a raise is the host's question failing); with `create` the stack is made by its own Create (its window a message-only
  one) in SurfaceScreen's probe mode - its card windows made and never shown - with the test's clock, place and look;
* `stack.focus_line`, `win32._plain` and `win32.focus_snapshot` are CardStack.FocusLine, its Plain and FocusSnapshot
  (the last reads this machine's front window, as the original does: read only).
"""
from __future__ import annotations

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
    import test_card_focus as original  # noqa: E402  (a module name: its classes are not collected here)
    LINE, SECOND = original.FocusLineTests, original.SecondLookTests
else:
    LINE = SECOND = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _letters(value, found):
    if isinstance(value, str):
        found.update(value)
    elif isinstance(value, dict):
        for item in value.values():
            _letters(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _letters(item, found)
    return found


def notice_event(notice):
    """The core's `notice` event for a reference Notice (gui/CardStack.cs's shape): its view as notice_card.view makes it,
    its title, whether it stays, and every character its words draw."""
    from codex_auto_resume import notice_card
    if notice is None:
        return None                                  # what build gives an event with no notice: the card host refuses it
    view = _plain(notice_card.view(notice))
    return {"id": 1, "key": notice.key, "title": notice.title, "stays": notice.stays is True, "view": view,
            "letters": "".join(sorted(_letters(view, set())))}


class HostStack:
    def __init__(self, log=None, focus=None, clock=None, locate=None, appearance=None, **unused):
        self.log, self.focus = log or (lambda *unused: None), focus
        self.clock = clock or (lambda: 0.0)
        self.locate, self.appearance = locate, appearance
        self.answers, self.history, self.seen, self.made = [], [], 0, None
        self.hwnd = None

    def create(self):
        self.made = {"where": _plain(self.locate()), "appearance": _plain(self.appearance())}
        self.hwnd = "the host's stack window"
        return self

    def _go(self, step):
        self.history.append(step)
        while True:
            found = surfacehost.SERVE.ask("card_focus", op="steps", answers=self.answers, steps=self.history,
                                          create=self.made is not None, **(self.made or {}))
            last = found["steps"][-1]
            if not last["unanswered"]:
                break
            try:
                self.answers.append(_plain(self.focus()))
            except Exception:
                self.answers.append("raise")
        for line in last["logs"][self.seen:]:
            self.log(line)
        self.seen = len(last["logs"])
        return last["returned"]

    def _focus_after(self, before):
        self._go(["after", _plain(before)])

    def show(self, notice):
        return self if self._go(["show", notice_event(notice), float(self.clock())]) else None

    def _handle(self, hwnd, message, wparam, lparam):
        return int(self._go(["message", int(message), int(wparam), int(lparam or 0)]))

    def destroy(self):
        pass


def _modules():
    stack = types.SimpleNamespace(CardStack=HostStack, WM_TIMER=original.stack.WM_TIMER,
                                  focus_line=lambda before, after: surfacehost.SERVE.ask(
                                      "card_focus", op="line", before=_plain(before), after=_plain(after)))
    win32 = types.SimpleNamespace(TIMER_FOCUS=original.win32.TIMER_FOCUS,
                                  _plain=lambda text: surfacehost.SERVE.ask("card_focus", op="plain", text=text),
                                  focus_snapshot=lambda: surfacehost.SERVE.ask("card_focus", op="snapshot"))
    return stack, win32


class HostModules:
    def setUp(self):
        stack, win32 = _modules()
        for name, value in (("stack", stack), ("win32", win32)):
            patcher = mock.patch.object(original, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        super().setUp()


@ON_HOST
class FocusLineOnHostTests(HostModules, LINE):  # noqa: F821
    def test_a_change_is_one_line_and_no_change_is_none(self):
        super().test_a_change_is_one_line_and_no_change_is_none()

    def test_a_probe_that_fails_says_nothing(self):
        super().test_a_probe_that_fails_says_nothing()

    def test_only_plain_words_reach_the_log(self):
        super().test_only_plain_words_reach_the_log()

    def test_the_probe_answers_its_three_keys_on_this_machine(self):
        super().test_the_probe_answers_its_three_keys_on_this_machine()


@ON_HOST
class SecondLookOnHostTests(HostModules, SECOND):  # noqa: F821
    def test_cards_shown_start_no_thread_and_the_timer_takes_one_look_from_before_the_first(self):
        super().test_cards_shown_start_no_thread_and_the_timer_takes_one_look_from_before_the_first()


del LINE, SECOND


if __name__ == "__main__":
    unittest.main()
