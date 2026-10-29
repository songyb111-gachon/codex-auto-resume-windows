"""Which endings are red on the icon and the taskbar button, and which ask for attention (v0.6.20, standard J14 as the
owner amended it on 2026-10-29: "확실한 실패만 빨강").

Red until seen, for a certain, unhidden, unseen ending after which nothing started: a recovery that failed, one whose
turn failed, one whose attempts ran out (a retry budget, or no progress), one handed over to the person. Amber, "Needs
your attention", under the same rule and with the same seen time, for a sending whose arrival cannot be confirmed
(submission_unknown) and one whose outcome was never verified (outcome_unverified). The headers keep their rule: red is
the icon's and the taskbar's, as tests/data/light_states.json says.

Every test runs against an isolated home; nothing touches the real install, its registry or its state.
"""
from __future__ import annotations

import io
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, l10n, startup  # noqa: E402
from codex_auto_resume.win import homelock  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.ui import tray  # noqa: E402
from codex_auto_resume.ui.tray import model as tray_model, words as tray_words  # noqa: E402

from test_control import ControlTestCase  # noqa: E402

RED = ("failed", "recovery_turn_failed", "retry_budget_exhausted", "no_progress_exhausted", "handed_over")
AMBER = ("submission_unknown", "outcome_unverified")
NOT_EITHER = ("terminal_failure", "cancelled", "recovered", "completed_no_progress", "stopped_by_user", "superseded")
THREAD = "0a1b2c3d-0001-7000-8000-%012d"


class OutcomeCase(ControlTestCase):
    def fresh(self):
        """A home of its own for the next sub-test: the last one's patches undone first. Calling setUp again without
        tearDown left Control.watcher_running patched for the rest of the process, so a later module's start_watcher
        saw a watcher that was not there (the order leak of tests/test_wire_goldens, 2026-10-30)."""
        self.tearDown()
        self.setUp()

    def ended(self, state, outcome_at=300.0, **more):
        """A record that ended in `state`, as the store keeps it; its key."""
        self.register()
        key = next(iter(self.rows()))
        # The states that follow a recovery turn name it.
        self.set_row(key, state=state, outcome_at=outcome_at, submitted_at=290.0,
                     recovery_turn_id="0a1b2c3d-0001-7000-8000-0000000000aa", **more)
        return key

    def rows(self):
        connection = sqlite3.connect(str(self.paths.state_dir / "state.sqlite"))
        try:
            return {row[0]: row[1] for row in connection.execute("SELECT interruption_id, state FROM interruptions")}
        finally:
            connection.close()

    def set_row(self, key, **columns):
        connection = sqlite3.connect(str(self.paths.state_dir / "state.sqlite"))
        try:
            assignments = ", ".join("%s=?" % name for name in columns)
            connection.execute("UPDATE interruptions SET %s WHERE interruption_id=?" % assignments,
                               (*columns.values(), key))
            connection.commit()
        finally:
            connection.close()

    def marks(self):
        with Store(self.paths.state_dir) as store:
            return store.failure_marks()

    def status(self):
        return control.Control(self.paths).get_status()

    def snapshot(self):
        with Store(self.paths.state_dir) as store:
            return tray_model.snapshot_from(store, 400.0)


class RedTests(OutcomeCase):
    def test_each_certain_ending_is_a_failure_nobody_has_seen(self):
        """Fails with the old rule (`failed` alone): the other four are no failure."""
        for state in RED:
            with self.subTest(state=state):
                self.fresh()
                self.ended(state)
                self.assertEqual(self.marks()["failed_at"], 300.0)
                self.assertIsNone(self.marks()["unconfirmed_at"])
                self.control.acknowledge_failure(200.0, baseline=True)
                status = self.status()
                self.assertEqual((status["failure_unseen"], status["unconfirmed_unseen"]), (True, False))

    def test_the_icon_is_red_for_each(self):
        for state in RED:
            with self.subTest(state=state):
                self.fresh()
                self.ended(state)
                snapshot = self.snapshot()
                self.assertEqual(snapshot["failures"]["failed_at"], 300.0)
                self.assertEqual(tray.icon_state(snapshot, failed=True), "failed")

    def test_seen_or_hidden_it_is_red_no_more(self):
        key = self.ended("handed_over")
        self.control.acknowledge_failure(200.0, baseline=True)
        self.assertTrue(self.status()["failure_unseen"])
        self.control.acknowledge_failure()
        self.assertFalse(self.status()["failure_unseen"])
        self.set_row(key, history_hidden_at=1.0)
        self.assertIsNone(self.marks()["failed_at"])

    def test_a_recovery_that_started_after_it_clears_it(self):
        self.ended("recovery_turn_failed")
        self.register(key="b" * 64, thread_id=THREAD % 2)
        self.set_row("b" * 64, submitted_at=310.0)
        self.control.acknowledge_failure(200.0, baseline=True)
        self.assertEqual(self.marks()["started_at"], 310.0)
        self.assertFalse(self.status()["failure_unseen"])


class AmberTests(OutcomeCase):
    def test_each_unconfirmed_ending_asks_for_attention_and_is_no_failure(self):
        for state in AMBER:
            with self.subTest(state=state):
                self.fresh()
                self.ended(state)
                self.assertIsNone(self.marks()["failed_at"])
                self.assertEqual(self.marks()["unconfirmed_at"], 300.0)
                self.control.acknowledge_failure(200.0, baseline=True)
                status = self.status()
                self.assertEqual((status["failure_unseen"], status["unconfirmed_unseen"]), (False, True))

    def test_the_icon_asks_for_attention_for_each_and_is_what_it_was_without(self):
        for state in AMBER:
            with self.subTest(state=state):
                self.fresh()
                self.ended(state)
                snapshot = self.snapshot()
                self.assertEqual(snapshot["failures"]["unconfirmed_at"], 300.0)
                self.assertEqual(tray.icon_state(dict(snapshot, unconfirmed=True)), "attention")
                self.assertNotEqual(tray.icon_state(dict(snapshot, unconfirmed=False)), "attention")

    def test_one_seen_time_clears_both(self):
        self.ended("submission_unknown")
        self.control.acknowledge_failure(200.0, baseline=True)
        self.assertTrue(self.status()["unconfirmed_unseen"])
        self.control.acknowledge_failure()
        self.assertFalse(self.status()["unconfirmed_unseen"])

    def test_the_tooltip_says_the_amber_lights_own_word(self):
        english = l10n.catalog("en")
        snapshot = {"enabled": True, "waiting": 0, "running": 0, "unconfirmed": True}
        self.assertIn(english["activity.attention"], tray_words.tooltip(snapshot, english, 0.0))
        self.assertNotIn(english["tray.failed"], tray_words.tooltip(snapshot, english, 0.0))
        held = {"enabled": True, "waiting": 1, "running": 0, "held": 1}
        self.assertIn(english["activity.attention"], tray_words.tooltip(held, english, 0.0))

    def test_red_comes_before_amber_when_both_are_unseen(self):
        english = l10n.catalog("en")
        snapshot = {"enabled": True, "waiting": 0, "running": 0, "failed": True, "unconfirmed": True}
        self.assertEqual(tray.icon_state(snapshot, failed=True), "failed")
        self.assertIn(english["tray.failed"], tray_words.tooltip(snapshot, english, 0.0))


class NeitherTests(OutcomeCase):
    def test_no_other_ending_lights_either(self):
        for state in NOT_EITHER:
            with self.subTest(state=state):
                self.fresh()
                self.ended(state)
                self.assertEqual((self.marks()["failed_at"], self.marks()["unconfirmed_at"]), (None, None))


class LeakGuardTests(unittest.TestCase):
    """The module's own cases leave the process as they found it."""

    WATCHED = (("Control.watcher_running", lambda: control.Control.watcher_running),
               ("Control.startup_enabled", lambda: control.Control.startup_enabled),
               ("startup._winreg", lambda: startup._winreg),
               ("homelock.INSTALL_LOCK", lambda: homelock.INSTALL_LOCK))

    def test_running_the_cases_restores_every_patch_they_make(self):
        """Fails with a case that calls setUp again without tearDown: the patches stack, and the last tearDown puts
        back the previous patch instead of the original."""
        before = [(name, read()) for name, read in self.WATCHED]
        suite = unittest.TestSuite()
        for case in (RedTests, AmberTests, NeitherTests):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        for name, value in before:
            with self.subTest(name):
                self.assertIs(dict((key, read()) for key, read in self.WATCHED)[name], value)
        self.assertFalse(isinstance(control.Control.watcher_running, mock.Mock),
                         "the watcher probe is still a mock after the cases")


if __name__ == "__main__":
    unittest.main()
