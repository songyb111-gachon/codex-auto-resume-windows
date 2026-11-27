"""The popup's `perform` and `PopupModel` under CODEX_AR_CORE=rust equal the reference's, call for call (S6.4b).

`tests/rustdiff/surfaceproxy.py` answers `ui.popup.model.perform` and `PopupModel` from car-surface, handing the control
layer, the opener and the source the test passed in back to the test's own objects: each control call is made once, in the
order and with the shape (positional or keyword) the reference writes it. This file holds that wrapper to the Python
original (`__wrapped__`) on the same recording objects: the same result, the same calls with the same arguments and
keywords, the same exception reaching the same verdict, and for the model the same state after every step.

Without the variable the proxy is not installed and every test here is skipped (the shipped edition never sees it).
"""
from __future__ import annotations

import types
import unittest

from codex_auto_resume import l10n
from codex_auto_resume.ui.popup import model

PROXIED = bool(getattr(model.perform, "rust_core", None))
KEY, THREAD = "k" * 64, "0a1b2c3d-0001-7000-8000-000000000001"
ROW = {"interruption_id": KEY, "thread_id": THREAD, "state": "waiting_reset", "category": "usage_limit", "code": "waiting_reset",
       "eligible_at": 2000.0, "overlays": [], "thread_enabled": True, "hold": None, "tier": None, "name": "Example",
       "reset_at": 2000.0, "detected_at": 900.0, "cancel_requested": False, "terminal": False, "postponed_until": None,
       "once_words": False, "reason": "reset"}
STATUS = {"enabled": True, "watcher_running": True, "settings": {"default_tier": "automatic"}, "watcher": {"ticking": True}}


class Refused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Recording:
    """A control layer that records each call as the reference writes it and answers from `answers`."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def _go(self, name, args, kwargs):
        self.calls.append((name, args, kwargs))
        found = self.answers.get(name, {"ok": True})
        if isinstance(found, BaseException):
            raise found
        return found

    def __getattr__(self, name):
        if name.startswith("_") or name not in model.CONTROL_CALLS:
            raise AttributeError(name)
        return lambda *args, **kwargs: self._go(name, args, kwargs)


ACTIONS = [("read",), ("recovery", KEY, THREAD, False), ("recovery", KEY, THREAD, 1), ("enabled", True), ("enabled", 0),
           ("postpone", KEY, THREAD, "1_hour"), ("postpone", KEY, THREAD, None), ("unpostpone", KEY, THREAD),
           ("release", KEY, THREAD), ("tier", KEY, THREAD, "ask_first"), ("project", KEY, THREAD, True),
           ("unsay", KEY, THREAD), ("dashboard",), ("dashboard_row", "message", KEY, THREAD),
           ("dashboard_row", "nope", KEY, THREAD), ("nope",), ()]
ANSWER_SETS = [
    {"list_pending": [dict(ROW)], "get_status": dict(STATUS)},
    {"list_pending": [], "get_status": {}, "set_enabled": {"enabled": False}, "set_interruption_recovery": {"enabled": True}},
    {"list_pending": Refused("no_such_interruption"), "set_enabled": Refused("nope"), "postpone": Refused("thread_mismatch")},
    {"list_pending": RuntimeError("x"), "get_status": OSError("y"), "unpostpone": Refused(""), "release_hold": ValueError("z")},
    {"set_thread_tier": {"set": True}, "set_project_rule": {"always": True}, "set_once_words": {"set": False}},
]


def run(function, action, answers, source, opener):
    control = Recording(answers)
    asked = []
    if opener is None:
        dashboard = None
    else:
        def dashboard(row=None):
            asked.append(row)
            return opener
    try:
        result = function(action, control, source=source, dashboard=dashboard)
    except Exception as error:                       # the reference never lets one out; neither may the proxy
        result = ("raised", type(error).__name__)
    return result, control.calls, asked


@unittest.skipUnless(PROXIED, "needs CODEX_AR_CORE=rust: the proxy is what is held to the reference")
class PerformTests(unittest.TestCase):
    def test_every_action_calls_the_control_layer_as_the_reference_does(self):
        sources = (None, types.SimpleNamespace(name="source"))
        for action in ACTIONS:
            for answers in ANSWER_SETS:
                for source in sources:
                    for opener in (None, True, 0):
                        with self.subTest(action=action, answers=sorted(answers), source=source is not None, opener=opener):
                            mine = run(model.perform, action, answers, source, opener)
                            theirs = run(model.perform.__wrapped__, action, answers, source, opener)
                            self.assertEqual(mine, theirs)

    def test_a_source_goes_to_the_control_layer_as_the_object_the_test_passed(self):
        source = object()
        control = Recording({"list_pending": [], "get_status": {}})
        self.assertEqual(model.perform(("read",), control, source=source), ("ok", {"rows": [], "status": {}}))
        self.assertIs(control.calls[0][2]["source"], source)


@unittest.skipUnless(PROXIED, "needs CODEX_AR_CORE=rust: the proxy is what is held to the reference")
class PopupModelTests(unittest.TestCase):
    def state(self, shown):
        return {name: getattr(shown, name) for name in ("rows", "status", "read_failed", "notice_key", "notice_until",
                                                        "busy", "drawn_paused", "wants_read", "drawn", "drawn_tasks")}

    def test_every_step_leaves_the_state_the_reference_leaves(self):
        strings = l10n.catalog("en")
        steps = [("view", 1000.0), ("apply", ("read",), ("ok", {"rows": [dict(ROW)], "status": dict(STATUS)}), 1000.0),
                 ("view", 1000.0), ("begin", ("recovery", KEY, THREAD, False)), ("begin", ("recovery", KEY, THREAD, False)),
                 ("view", 1001.0), ("apply", ("recovery", KEY, THREAD, False), ("ok", {"enabled": False}), 1001.0),
                 ("view", 1001.0), ("apply", ("unpostpone", KEY, THREAD), ("refused", "thread_mismatch"), 1002.0),
                 ("view", 1003.0), ("view", 1010.0), ("apply", ("read",), ("failed", "OSError"), 1011.0), ("view", 1011.0),
                 ("apply", ("enabled", True), ("ok", {"enabled": True}), 1012.0), ("view", 1012.0)]
        mine, theirs = model.PopupModel(strings), model.PopupModel.__wrapped__(strings)
        for step in steps:
            with self.subTest(step=step):
                if step[0] == "view":
                    self.assertEqual(mine.view(step[1]), theirs.view(step[1]))
                elif step[0] == "begin":
                    self.assertEqual(mine.begin(step[1]), theirs.begin(step[1]))
                else:
                    mine.apply_outcome(step[1], step[2], step[3])
                    theirs.apply_outcome(step[1], step[2], step[3])
                self.assertEqual(self.state(mine), self.state(theirs))
                self.assertEqual(mine.attention(), theirs.attention())
                self.assertEqual(mine.menu_for(KEY), theirs.menu_for(KEY))
                for target in (("check", KEY), ("check", "x"), ("toggle",), ("dashboard",), ("nope",), (), None):
                    self.assertEqual(mine.action_for(target), theirs.action_for(target))

    def test_rows_and_status_set_together_are_one_read(self):
        strings = l10n.catalog("en")
        mine, theirs = model.PopupModel(strings), model.PopupModel.__wrapped__(strings)
        for shown in (mine, theirs):
            shown.status, shown.rows = dict(STATUS), [dict(ROW)]
        self.assertEqual(self.state(mine), self.state(theirs))
        self.assertEqual(mine.view(1000.0), theirs.view(1000.0))
        self.assertEqual(mine.attention(), theirs.attention())

    def test_what_cannot_be_sent_is_refused_and_never_answered_by_python(self):
        mine = model.PopupModel(l10n.catalog("en"))
        with self.assertRaises(TypeError):
            mine.notice_key = "popup.stale"
        mine.status = dict(STATUS)
        with self.assertRaises(TypeError):
            mine.view(1000.0)                  # status without rows: the reference's model would hold rows None


if __name__ == "__main__":
    unittest.main()
