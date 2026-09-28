"""v0.6.11: Don't postpone - a person's own postponement taken away, and nothing else.

Retry now never shortens a postponement (tests/test_postpone_and_tiers.py), so a person who
postponed a task needs a way to undo exactly that: `unpostpone`, bound to the exact record like
postponing is, and only ever back to what the schedule says without the person's postponement. An
objection window still ahead stays - its card promised that time - and so do the retry's wait, a usage
reset and quiet hours, which it never touches. It is offered in the Dashboard and the popup's row
menu, and never to a model: MCP has no tool for it, because it brings a send nearer.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, controlcli, l10n, machine, mcpserver, settings  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import KEY, OTHER_KEY, THREAD, ControlTestCase, detection  # noqa: E402
from test_engine import T1, EngineCase  # noqa: E402

OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000009"


class RuleTests(unittest.TestCase):
    """domain/public.own_postponement: the one rule every surface and the store read."""

    def test_only_a_time_past_the_objection_windows_end_is_a_persons(self):
        rule = machine.own_postponement
        self.assertIsNone(rule({"not_before": None}))
        self.assertEqual(rule({"not_before": 500.0}), 500.0)
        self.assertIsNone(rule({"not_before": 500.0, "objection_until": 500.0}), "the window's own end")
        self.assertEqual(rule({"not_before": 900.0, "objection_until": 500.0}), 900.0)
        self.assertIsNone(rule({"not_before": 500.0}, 600.0), "over already")
        self.assertEqual(rule({"not_before": 500.0}, 400.0), 500.0)


class StoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / "state")
        self.addCleanup(self.store.close)
        self.store.set_enabled(True, 100.0)

    def test_it_takes_a_persons_postponement_away_and_journals_it(self):
        self.store.register(detection(), 100.0)
        before = dict(self.store.get(KEY))
        self.store.postpone(KEY, THREAD, 5000.0, 200.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 300.0, actor="gui"), (True, None))
        after = self.store.get(KEY)
        self.assertIsNone(after["not_before"])
        self.assertEqual({name for name in before if before[name] != after[name]}, set(),
                         "back to exactly what it was: the retry's wait and the reset untouched")
        [event] = [event for event in self.store.events(KEY) if event["code"] == "unpostponed"]
        self.assertEqual((event["actor"], event["value"]), ("gui", None))

    def test_it_never_goes_past_an_objection_window(self):
        """Its card said when the continuation goes; a person's later postponement taken away goes
        back to that time, never sooner."""
        self.store.register(detection(), 100.0)
        self.assertTrue(self.store.open_objection_window(KEY, 500.0, 200.0))
        self.assertEqual(self.store.get(KEY)["objection_until"], 500.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 250.0), (False, "not_postponed"),
                         "the window is nobody's to take away")
        self.store.postpone(KEY, THREAD, 5000.0, 250.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 300.0), (True, 500.0))
        self.assertEqual(self.store.get(KEY)["not_before"], 500.0)
        # Once the window is over, nothing of it is kept.
        self.store.postpone(KEY, THREAD, 6000.0, 300.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 600.0), (True, None))
        self.assertIsNone(self.store.get(KEY)["not_before"])

    def test_a_postponement_that_is_over_or_none_is_not_one_to_take_away(self):
        self.store.register(detection(), 100.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 150.0), (False, "not_postponed"))
        self.store.postpone(KEY, THREAD, 500.0, 200.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 600.0), (False, "not_postponed"))
        self.assertEqual(self.store.get(KEY)["not_before"], 500.0, "a refusal changes nothing")

    def test_it_is_bound_to_the_exact_waiting_record(self):
        self.store.register(detection(), 100.0)
        self.store.postpone(KEY, THREAD, 5000.0, 200.0)
        self.assertEqual(self.store.unpostpone(OTHER_KEY, THREAD, 250.0), (False, "unknown_record"))
        self.assertEqual(self.store.unpostpone(KEY, OTHER_THREAD, 250.0), (False, "thread_mismatch"))
        self.assertEqual(self.store.get(KEY)["not_before"], 5000.0)
        self.store.cancel_interruption(KEY, 260.0)
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 270.0), (False, "finished"))

    def test_a_claimed_record_is_not_a_waiting_one(self):
        self.store.register(detection(), 100.0)
        self.assertTrue(self.store.reserve(KEY, 200.0))
        self.assertEqual(self.store.unpostpone(KEY, THREAD, 250.0), (False, "claimed"))


class EngineTests(EngineCase):
    def test_it_goes_at_the_windows_time_after_and_every_gate_still_runs(self):
        self.h.engine.apply_policy(dict(settings.defaults(), default_tier="objection_window",
                                        objection_minutes=5))
        self.ready_after_reset()
        self.h.tick()
        key = self.h.record()["interruption_id"]
        self.h.store.postpone(key, T1, self.h.now + 3600, self.h.now)
        self.assertEqual(self.h.store.unpostpone(key, T1, self.h.now + 10)[0], True)
        self.h.tick(advance=60)
        self.assert_no_send()
        self.h.tick(advance=241)
        self.assertEqual(len(self.h.backend.send_calls), 1, "at the window's end, not before it")

    def test_a_pause_still_holds_it(self):
        self.ready_after_reset()
        key = self.h.record()["interruption_id"]
        self.h.store.postpone(key, T1, self.h.now + 3600, self.h.now)
        self.h.store.set_enabled(False, self.h.now)
        self.h.store.unpostpone(key, T1, self.h.now + 1)
        self.h.tick(advance=5)
        self.assert_no_send()


class ControlTests(ControlTestCase):
    def test_it_answers_with_the_time_left_and_the_later_check(self):
        self.register()
        self.control.postpone(KEY, THREAD, minutes=120)
        self.assertIsNotNone(self.control.list_pending()[0]["postponed_until"])
        reply = self.control.unpostpone(KEY, THREAD)
        self.assertEqual((reply["interruption_id"], reply["thread_id"], reply["not_before"]), (KEY, THREAD, None))
        self.assertIn("every safety check still applies", reply["note"])
        row = self.control.list_pending()[0]
        self.assertEqual((row["not_before"], row["postponed_until"]), (None, None))

    def test_it_refuses_in_its_own_words(self):
        with self.assertRaises(control.ControlError) as caught:
            self.control.unpostpone(KEY, THREAD)
        self.assertEqual(caught.exception.code, "no_such_interruption")
        self.register()
        for arguments, code in (((KEY, THREAD), "not_postponed"), ((KEY, OTHER_THREAD), "thread_mismatch"),
                                ((KEY[:8], THREAD), "invalid_id")):
            with self.subTest(code), self.assertRaises(control.ControlError) as caught:
                self.control.unpostpone(*arguments)
            self.assertEqual(caught.exception.code, code)
        self.assertIn("error.not_postponed", l10n.catalog("en"))

    def test_it_sends_nothing_and_changes_only_the_time(self):
        self.register()
        with Store(self.paths.state_dir) as store:
            before = dict(store.get(KEY))
        self.control.postpone(KEY, THREAD, preset="3_hours")
        self.control.unpostpone(KEY, THREAD)
        with Store(self.paths.state_dir) as store:
            after = dict(store.get(KEY))
        self.assertEqual({name for name in before if before[name] != after[name]}, set())

    def test_the_bridge_offers_it_bound_to_the_row(self):
        self.register()
        self.control.postpone(KEY, THREAD, minutes=60)
        reply = controlcli.dispatch(self.control, "unpostpone", {"interruption_id": KEY, "thread_id": THREAD})
        self.assertTrue(reply["ok"])
        refused = controlcli.dispatch(self.control, "unpostpone", {"interruption_id": KEY, "thread_id": THREAD})
        self.assertEqual(refused["error_code"], "not_postponed")


class NeverToAModelTests(unittest.TestCase):
    def test_no_mcp_tool_and_no_panel_call_reaches_it(self):
        names = {tool["name"] for tool in mcpserver.TOOLS}
        self.assertFalse({name for name in names if "postpone" in name} - {"postpone_recovery"})
        source = (Path(mcpserver.__file__).parent / "mcp").glob("*.py")
        for path in list(source) + [Path(mcpserver.__file__).parent / "mcp" / "assets" / "panel.js"]:
            with self.subTest(path.name):
                self.assertNotIn("unpostpone", path.read_text(encoding="utf-8"))


class PopupTests(unittest.TestCase):
    def setUp(self):
        from codex_auto_resume.ui import popup
        self.popup = popup
        self.strings = l10n.catalog("en")

    def row(self, **extra):
        return dict({"interruption_id": KEY, "thread_id": THREAD, "state": "waiting_reset",
                     "category": "usage_limit", "eligible_at": 2000.0, "overlays": [],
                     "thread_enabled": True, "hold": None, "tier": None}, **extra)

    def dont(self, row):
        task = self.popup.task_item(row, self.strings, 1000.0)
        postpone = self.popup.model.row_menu(task, self.strings, "automatic")[0]
        return postpone["items"][-1]

    def test_it_is_last_under_postpone_and_only_for_a_persons_postponement_still_ahead(self):
        item = self.dont(self.row(postponed_until=5000.0, not_before=5000.0))
        self.assertEqual((item["text"], item["action"], item["enabled"]),
                         (self.strings["menu.unpostpone"], ("unpostpone", KEY, THREAD), True))
        self.assertFalse(self.dont(self.row(postponed_until=900.0))["enabled"], "over already")
        self.assertFalse(self.dont(self.row(not_before=5000.0))["enabled"], "an objection window's")
        self.assertFalse(self.dont(self.row(state="submitting", postponed_until=5000.0))["enabled"])

    def test_it_is_one_control_call_bound_to_its_row(self):
        calls = []

        class Control:
            def unpostpone(self, *args, **kwargs):
                calls.append((args, kwargs))
                return {}
        action = ("unpostpone", KEY, THREAD)
        self.assertEqual(self.popup.perform(action, Control()), ("ok", {}))
        self.assertEqual(calls, [((KEY, THREAD), {})])
        self.assertEqual(self.popup.busy_key(action), ("row", KEY))
        model = self.popup.PopupModel(self.strings)
        model.apply_outcome(action, ("refused", "thread_mismatch"), 0.0)
        self.assertEqual(model.notice_key, "popup.stale")
        self.assertIn("unpostpone", self.popup.model.CONTROL_CALLS)


if __name__ == "__main__":
    unittest.main()
