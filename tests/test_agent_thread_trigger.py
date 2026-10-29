"""Issue #54: a conversation an agent made (thread_source agent_created_thread) is a person's own in the turns they start
from the input box - Codex records how each turn was started (turn_attribution.turn_trigger on the rollout's task_started
event), and a failed turn that "composer" started is taken up; any other trigger, none, or no rollout leaves the
conversation excluded exactly as before. Nothing else about eligibility changes.

    PYTHONPATH=src;tests python -m unittest test_agent_thread_trigger
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import unittest.mock

import codexsim
from codex_auto_resume.codex import LocalSource, rollout
from codex_auto_resume.codex.values import AGENT_CREATED_THREAD, taken_thread_source
from codex_auto_resume.domain.plughands import Widening
from test_source import closing_db

AGENT = AGENT_CREATED_THREAD


def started(home, thread, turn, trigger, where="turn_attribution"):
    """The rollout's task_started event of `turn`, with the trigger Codex records (None: no turn_attribution at all)."""
    payload = {"type": "task_started", "turn_id": turn}
    if trigger is not None:
        payload[where] = {"turn_id": turn, "turn_trigger": trigger}
    home._append(thread, [{"type": "event_msg", "payload": payload}])


class AgentThreadTriggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = codexsim.CodexHome(Path(self.temp.name))
        self.source = LocalSource(self.home.root)
        self.since = codexsim.BASE - 1000

    def failing(self, trigger, thread_source=AGENT, **how):
        thread, turn = codexsim.new_id(), codexsim.new_id()
        self.home.add_thread(thread, thread_source=thread_source)
        if trigger is not False:                     # False: the Codex that wrote no task_started at all
            started(self.home, thread, turn, trigger, **how)
        self.home.fail_usage(thread, turn_id=turn)
        return thread, turn

    def detected(self):
        return [row["thread_id"] for row in self.source.latest_failures(self.since)]

    def test_a_turn_started_from_the_input_box_is_taken_up(self):
        thread, turn = self.failing("composer")
        self.assertIn(thread, self.detected())
        self.assertEqual(self.source.latest(thread)["turn_id"], turn)
        passed = {row["turn_id"]: row for row in self.source.passed_over(self.since, self.since)["passed"]}
        self.assertIsNone(passed[turn]["reason"], "brought, not passed over")

    def test_any_other_trigger_or_none_leaves_it_excluded(self):
        for name, trigger in (("queue", "queue"), ("goal", "goal"), ("guardian_review", "guardian_review"),
                              ("a tool sending", "app_tool_send_message"), ("user", "user"), ("Composer", "Composer"),
                              ("no attribution", None), ("no task_started", False), ("empty", "")):
            with self.subTest(name):
                thread, _ = self.failing(trigger)
                self.assertNotIn(thread, self.detected())
                self.assertIsNone(self.source.latest(thread))

    def test_the_excluded_say_why_as_they_always_did(self):
        thread, turn = self.failing("queue")
        found = {row["turn_id"]: row for row in self.source.passed_over(self.since, self.since)["passed"]}
        self.assertEqual((found[turn]["reason"], found[turn]["kind"]), ("other_kind", "thread_source agent_created_thread"))

    def test_no_rollout_file_is_unknown_and_excluded(self):
        thread, _ = self.failing("composer")
        self.home.rollout(thread).unlink()
        self.assertNotIn(thread, self.detected())

    def test_it_is_that_exact_turn_that_counts(self):
        """A composer turn earlier does not make a later queued failure the person's, and the other way round."""
        thread, first, second = codexsim.new_id(), codexsim.new_id(), codexsim.new_id()
        self.home.add_thread(thread, thread_source=AGENT)
        started(self.home, thread, first, "composer")
        started(self.home, thread, second, "queue")
        self.home.add_turn(thread, first, "completed")
        self.home.fail_usage(thread, turn_id=second)
        self.assertNotIn(thread, self.detected())
        other, early, late = codexsim.new_id(), codexsim.new_id(), codexsim.new_id()
        self.home.add_thread(other, thread_source=AGENT)
        started(self.home, other, early, "queue")
        started(self.home, other, late, "composer")
        self.home.add_turn(other, early, "completed")
        self.home.fail_usage(other, turn_id=late)
        self.assertIn(other, self.detected())

    def test_a_trigger_is_read_for_its_own_turn_only(self):
        thread, turn = self.failing("queue")
        other = codexsim.new_id()
        self.assertEqual(rollout.turn_trigger(self.home.rollout(thread), turn), "queue")
        self.assertIsNone(rollout.turn_trigger(self.home.rollout(thread), other))

    def test_the_last_turns_trigger_is_read_once_per_version_of_the_file(self):
        """latest() and the reads like it ask without a turn id, several times a tick: an unchanged file is not opened
        again - whether it held a trigger or none - and a task_started appended to it is seen."""
        thread, _ = self.failing("queue")
        quiet, _ = self.failing(None)
        opened, real = [], Path.open

        def counting(path, *args, **kwargs):
            opened.append(path)
            return real(path, *args, **kwargs)

        for name, file, expected in (("a trigger", self.home.rollout(thread), "queue"),
                                     ("none", self.home.rollout(quiet), None)):
            with self.subTest(name):
                opened.clear()
                with unittest.mock.patch.object(Path, "open", counting):
                    answers = [rollout.turn_trigger(file) for _ in range(3)]
                self.assertEqual(answers, [expected] * 3)
                self.assertEqual(opened, [file], "opened once, not once per ask")
        self.assertIsNone(self.source.latest(quiet))
        started(self.home, quiet, codexsim.new_id(), "composer")
        self.assertEqual(rollout.turn_trigger(self.home.rollout(quiet)), "composer")

    def test_every_other_check_still_stands(self):
        foreign = codexsim.new_id()
        turn = codexsim.new_id()
        self.home.add_thread(foreign, thread_source=AGENT, originator="codex_vscode")
        started(self.home, foreign, turn, "composer")
        self.home.fail_usage(foreign, turn_id=turn)
        archived, turn = self.failing("composer")
        with closing_db(self.home.root / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET archived=1 WHERE id=?", (archived,))
        disagreeing, turn = self.failing("composer")
        with closing_db(self.home.root / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET thread_source='user' WHERE id=?", (disagreeing,))
        found = self.detected()
        self.assertNotIn(foreign, found)
        self.assertNotIn(archived, found)
        self.assertNotIn(disagreeing, found, "the state row says user, the rollout agent_created_thread")

    def test_the_other_kinds_codex_makes_for_itself_stay_excluded_even_from_the_input_box(self):
        for label in ("subagent", "guardian_review", "memory_consolidation"):
            with self.subTest(label):
                thread, _ = self.failing("composer", thread_source=label)
                self.assertNotIn(thread, self.detected())

    def test_wide_the_rule_is_the_same(self):
        self.source.widened = frozenset({Widening.EVERY_DESKTOP})
        composed, _ = self.failing("composer")
        queued, _ = self.failing("queue")
        found = self.detected()
        self.assertIn(composed, found)
        self.assertNotIn(queued, found)

    def test_the_predicate_asks_the_flag_alone_for_an_agent_made_one(self):
        wide = frozenset({Widening.EVERY_DESKTOP})
        for widened in (frozenset(), wide):
            self.assertFalse(taken_thread_source(AGENT, widened))
            self.assertTrue(taken_thread_source(AGENT, widened, composed=True))
            self.assertFalse(taken_thread_source("subagent", widened, composed=True))


if __name__ == "__main__":
    unittest.main()
