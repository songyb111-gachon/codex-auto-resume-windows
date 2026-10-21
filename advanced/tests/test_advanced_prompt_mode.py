"""The prompt queue's send mode while a turn is running (v0.6.19, issue #50): a message at a time or on a schedule either
waits until the conversation's running turn ends ("wait", what the Dashboard's editor recommends and preselects) or goes
into Codex's own queue at once ("queue", what every message did before the choice existed, and still does for a row
written then). "After this turn" goes into Codex's queue by its nature. Either way every core gate still applies and an
uncertain send still blocks; "wait" holds while whether a turn runs cannot be read (unknown never sends).

Held against core's own engine and simulated Codex home (takingcase.py), whose turn history the capability reads
read-only (codex/turns.py) where the watcher's Codex home is pointed at it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_queue import QueueCase  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import inuse  # noqa: E402
from codex_auto_resume_advanced.engine import promptqueue  # noqa: E402
from codex_auto_resume_advanced.registry import PROMPT_QUEUE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import PromptReason, PromptState, Refusal, WhileRunning  # noqa: E402
from test_engine import T1  # noqa: E402


class ModeCase(QueueCase):
    def setUp(self):
        super().setUp()
        # The watcher's Codex home is the simulated one, whose turn history the capability reads.
        patcher = mock.patch.object(inuse, "home", lambda paths=None: self.h.home.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def running(self):
        """A turn of the conversation in progress now, the latest."""
        return self.h.home.add_turn(T1, status="inProgress")

    def finished(self, turn):
        self.h.home.set_turn(T1, turn, status="completed", completed_at=int(self.h.now))

    def timed(self, plug, mode=None, **argument):
        if mode is not None:
            argument["while_running"] = mode
        return self.add(plug, words="carry on with the release notes", trigger="at_time", at=self.h.now + 60,
                        **argument)


class WaitTests(ModeCase):
    def test_wait_holds_while_the_latest_turn_runs_and_goes_once_it_is_final(self):
        """Fails with the mode reverted: the message is handed while the turn runs."""
        plug = self.on()
        turn = self.running()
        prompt = self.timed(plug, "wait")["prompt"]
        self.h.tick(advance=120)
        self.h.tick(advance=10)
        self.assertEqual(self.sends(), [])
        row = plug.runtime.state.prompt(prompt)
        self.assertEqual((row["state"], row["reason"]), (PromptState.WAITING, PromptReason.TURN_RUNNING))
        self.finished(turn)
        self.h.tick(advance=10)
        self.assertEqual(len(self.sends()), 1)
        self.assertTrue(self.sends()[0].startswith("carry on with the release notes\n\n"))

    def test_wait_goes_at_its_time_when_no_turn_runs(self):
        plug = self.on()
        self.timed(plug, "wait")
        self.h.tick(advance=120)
        self.assertEqual(len(self.sends()), 1)

    def test_wait_holds_where_whether_a_turn_runs_cannot_be_read(self):
        """Unknown never sends: the history unreadable holds a waiting message, and says nothing it does not know."""
        plug = self.on()
        prompt = self.timed(plug, "wait")["prompt"]
        with mock.patch.object(promptqueue, "turn_running", lambda paths, thread: None):
            self.h.tick(advance=120)
            self.h.tick(advance=10)
        self.assertEqual(self.sends(), [])
        self.assertIsNone(plug.runtime.state.prompt(prompt)["reason"])
        self.h.tick(advance=10)
        self.assertEqual(len(self.sends()), 1)

    def test_wait_still_meets_every_core_gate(self):
        """The turn final, a conversation the app does not hold still waits for it (A11): the mode relaxes nothing."""
        plug = self.on()
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.timed(plug, "wait")
        self.h.tick(advance=120)
        self.h.tick(advance=10)
        self.assertEqual(self.sends(), [])

    def test_a_held_wait_is_not_counted_due_while_watched(self):
        plug = self.on()
        self.running()
        self.timed(plug, "wait")
        self.h.now += 120
        code = plug.runtime._code_of(plug.runtime.registry.get(PROMPT_QUEUE.id))
        self.assertEqual(code.watched_due(_Enabled()), [])


class _Enabled:
    @staticmethod
    def thread_enabled(thread):
        return True


class QueueModeTests(ModeCase):
    def test_queue_goes_into_codex_s_queue_while_a_turn_runs_as_before(self):
        """Fails with the mode applied to every row: a message written to go into Codex's queue would wait."""
        plug = self.on()
        self.running()
        self.timed(plug, "queue")
        self.h.tick(advance=120)
        self.assertEqual(len(self.sends()), 1)

    def test_queue_never_reads_the_turn_history(self):
        plug = self.on()
        reader = mock.Mock(return_value=True)
        self.timed(plug, "queue")
        with mock.patch.object(promptqueue, "turn_running", reader):
            self.h.tick(advance=120)
        reader.assert_not_called()
        self.assertEqual(len(self.sends()), 1)

    def test_a_row_written_before_the_choice_and_one_not_naming_it_go_into_codex_s_queue(self):
        plug = self.on()
        added = self.timed(plug)["prompt"]
        self.assertEqual(plug.runtime.state.prompt(added)["while_running"], WhileRunning.QUEUE)
        direct = plug.runtime.state.add_prompt(T1, "a row as v0.6.18 wrote it", "at_time", at=self.h.now + 60)
        self.assertEqual(plug.runtime.state.prompt(direct)["while_running"], WhileRunning.QUEUE)
        shown = surfaces.bridge(plug.runtime, "advanced-prompts", {})["prompts"]
        self.assertEqual([item["while_running"] for item in shown], ["queue", "queue"])


class RefusalTests(ModeCase):
    def test_after_this_turn_goes_into_codex_s_queue_by_its_nature(self):
        plug = self.on()
        answer = self.add(plug, while_running="wait")
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.OCCASION_INVALID))
        self.assertTrue(self.add(plug, while_running="queue")["done"])

    def test_a_mode_that_is_not_one_is_refused(self):
        plug = self.on()
        for mode in ("later", 1, True):
            with self.subTest(mode=mode):
                answer = self.timed(plug, mode)
                self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.OCCASION_INVALID))
        self.assertEqual(plug.runtime.state.prompts(pending=None), [])

    def test_the_statement_names_the_mode_and_its_revision_moved_on(self):
        """The statement describes the default, so its revision moved on (#50): a person who had the queue on reads
        the new one before it is on again (arming.py's tripwire)."""
        self.assertEqual(PROMPT_QUEUE.revision, 2)
        from codex_auto_resume_advanced import statement
        does = statement.CATALOGS.own("en")[statement.key(PROMPT_QUEUE.id, "does")]
        self.assertIn("running", does)
        self.assertIn("recommended", does)


if __name__ == "__main__":
    unittest.main()
