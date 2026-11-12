"""v0.6.23 second round B1: after a change of Codex account, no stage of the usage capabilities acts on a reading the
meter made of the old account.

After an automatic switch the meter's last reading is still account A's - at 90% or more where A's window filled
between two readings - while the turns the switch freed run on account B, with room. The wrap-up then told every one of
them to wrap up and stop. A-R4 had given the pause alone the rule "a reading made at or before the switch is the old
account's"; now every stage asks one helper (usage.of_account), and the meter reads again at once after a change.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_usage as _usage  # noqa: E402
from codex_auto_resume_advanced import profiles, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import authfile  # noqa: E402
from codex_auto_resume_advanced.engine import usage  # noqa: E402
from codex_auto_resume_advanced.vocabulary import OptionKey  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from test_engine import T1  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced"


def switched(home, at):
    """account_auto_switch's record of a switch at `at`, as swap.switch writes it (profiles' switch.last)."""
    with patch.object(authfile, "_PRIVATE", lambda directory: True):
        profiles.Profiles(home, clock=lambda: int(at)).mark_switched("two@example.com")


class TheWrapUpLeavesTheOldAccountsReading(TakingCase):
    """The report's scenario, through core's engine and a simulated Codex home: A's reading at 91% (the wrap-up's 90),
    the switch to B, a turn running on B. WrapUpTests' own set-up, none of its tests."""
    DEFINITION = _usage.WrapUpTests.DEFINITION
    BESIDE = _usage.WrapUpTests.BESIDE
    language = _usage.WrapUpTests.language

    def setUp(self):
        super().setUp()
        self.compat = _usage._view_all()

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(w) for w in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def running(self, percent=91):
        plug, turn = _usage.WrapUpTests.running(self, percent)
        # The meter cannot read again here: its rows stay the ones each test made (a change makes it read at once,
        # TheOtherStagesLeaveItToo's last test).
        plug.runtime._code_of(plug.runtime.registry.get("usage_meter"))._app_running = lambda: False
        return plug, turn

    def sent(self, plug):
        self.language(plug, "en")
        for _ in range(3):
            self.h.tick(advance=61)
        return [prompt for thread, prompt in self.h.backend.send_calls if thread == T1]

    def test_a_reading_made_before_the_switch_sends_no_wrap_up(self):
        """Fails without the rule in _look: the turn on B was sent "You have used 91% ... stop at 95%"."""
        plug, _turn = self.running()
        read_at = plug.runtime.state.meter()[("codex", 300)]["read_at"]
        switched(plug.paths.home, read_at + 5)
        self.assertEqual(self.sent(plug), [], self.h.logs[-10:])

    def test_a_reading_made_at_the_very_second_of_the_switch_is_the_old_accounts(self):
        plug, _turn = self.running()
        read_at = plug.runtime.state.meter()[("codex", 300)]["read_at"]
        switched(plug.paths.home, read_at)
        self.assertEqual(self.sent(plug), [])

    def test_account_switch_seeing_another_account_counts_as_a_change_too(self):
        """A person who signed in to another account themselves: account_switch's watch stamps it."""
        plug, _turn = self.running()
        read_at = plug.runtime.state.meter()[("codex", 300)]["read_at"]
        plug.runtime.state.stamp("account_switch", OptionKey.ACCOUNT_CHANGED_AT, int(read_at) + 5)
        self.assertEqual(self.sent(plug), [])

    def test_a_reading_made_after_the_switch_still_acts(self):
        """A guard, not a proof: B's own reading at 91% is B's, and the wrap-up goes as before."""
        plug, _turn = self.running()
        read_at = plug.runtime.state.meter()[("codex", 300)]["read_at"]
        switched(plug.paths.home, read_at - 60)
        self.assertEqual(len(self.sent(plug)), 1, self.h.logs[-10:])


class TheOtherStagesLeaveItToo(_usage.UsageCase):
    CORE = {"interruption_id": _usage.ac.KEY, "thread_id": _usage.ac.THREAD}

    def test_the_forced_stop_marks_nothing_on_the_old_accounts_reading(self):
        """Fails without the rule in _mark: the pause marked A's window and the forced stop stopped the turns on B."""
        self.on("usage_meter")
        self.answer = _usage.reply(five=98)
        self.look()                                      # the meter reads A at 98% while the forced stop is off
        read_at = self.rt.state.meter()[("codex", 300)]["read_at"]
        switched(self.rt.paths.home, read_at + 5)
        self.app = False                                 # the meter cannot read again: its rows stay A's
        self.now += 30
        self.on("usage_pause")
        code = self.rt._code_of(self.rt.registry.get("usage_pause"))
        self.assertEqual(code._mark(), [])
        self.assertIsNone(self.rt.state.meter()[("codex", 300)]["paused_reset_at"])

    def test_a_hold_made_on_the_old_account_lets_go_at_the_switch(self):
        self.on("usage_pause")
        self.answer = _usage.reply(five=98)
        self.look()
        self.look()
        self.assertIsNotNone(self.rt.state.meter()[("codex", 300)]["paused_reset_at"])
        read_at = self.rt.state.meter()[("codex", 300)]["read_at"]
        switched(self.rt.paths.home, read_at + 5)
        self.app = False
        self.now += 30
        self.look()
        self.assertIsNone(self.rt.state.meter()[("codex", 300)]["paused_reset_at"])

    def test_the_meters_warning_is_not_shown_for_the_old_account(self):
        """Fails without the rule in meter_view: A's "near the limit" notice and band stayed on for B."""
        self.on("usage_meter")
        self.answer = _usage.reply(five=90)
        self.look()
        found = surfaces.meter_view(self.rt)["meter"]
        self.assertEqual([notice["kind"] for notice in found["notices"]], ["warn"])
        read_at = self.rt.state.meter()[("codex", 300)]["read_at"]
        switched(self.rt.paths.home, read_at + 5)
        found = surfaces.meter_view(self.rt)["meter"]
        self.assertEqual(found["notices"], [])
        self.assertEqual({row["window_minutes"]: row["band"] for row in found["windows"]}[300], "none")
        self.assertEqual({row["window_minutes"]: row["used_percent"] for row in found["windows"]}[300], 90,
                         "the reading itself is still shown as read")

    def test_the_meter_reads_again_at_once_after_a_change(self):
        """Fails without _changed_since: the meter waited its fifteen minutes, and every stage with it."""
        self.on("usage_meter")
        self.look()
        self.assertEqual(len(self.calls), 1)
        self.now += 60
        self.look()
        self.assertEqual(len(self.calls), 1, "within its spacing it does not read")
        self.rt.state.stamp("account_auto_switch", OptionKey.AUTO_SWITCHED_AT, int(self.now))
        self.now += 5
        self.look()
        self.assertEqual(len(self.calls), 2)
        self.now += 60
        self.look()
        self.assertEqual(len(self.calls), 2, "once for the change")


class EveryStageAsksTheOneRule(unittest.TestCase):
    """So the next capability that acts on the meter's windows cannot miss the rule: every function of the advanced
    edition that asks whether a window `reached` a stage's percentage also asks `of_account`."""

    def test_each_caller_of_reached_reads_its_rows_through_of_account(self):
        callers = []
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name == "reached":
                    continue
                called = {getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                          for call in ast.walk(node) if isinstance(call, ast.Call)}
                if "reached" in called:
                    callers.append(node.name)
                    self.assertIn("of_account", called, "%s:%s" % (path.name, node.name))
        self.assertGreaterEqual(len(callers), 4, callers)

    def test_the_pause_asks_it_where_it_holds(self):
        source = ast.get_source_segment((SRC / "engine" / "usage.py").read_text(encoding="utf-8"),
                                        next(node for node in ast.walk(ast.parse((SRC / "engine" / "usage.py")
                                                                                 .read_text(encoding="utf-8")))
                                             if isinstance(node, ast.FunctionDef) and node.name == "holding"))
        self.assertIn("of_account(", source)


if __name__ == "__main__":
    unittest.main()
