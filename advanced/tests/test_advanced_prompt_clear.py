"""Delete completed (v0.6.19, issue #50): the completed messages the Dashboard showed are taken off the prompt queue's list
- exactly those still completed (delivered, or handed over to the person), against the generation the list was read at -
and the answer says how many were deleted and how many kept because they changed. Waiting, held, cancelled, uncertain
and failed messages are kept, and so is every row of `records`, which the ledger's caps count, and anything of Codex's.

Held against core's own engine and simulated Codex home (takingcase.py) through the prompt queue's own harness, the
Dashboard's bridge (surfaces.bridge) as the page asks it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_queue import QueueCase  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.vocabulary import PromptReason, PromptState, Refusal  # noqa: E402


class ClearCase(QueueCase):
    def delivered(self, plug, count):
        """`count` messages sent and delivered, one after another (fifteen minutes apart, as every recovery): their ids."""
        found = []
        for index in range(count):
            found.append(self.add(plug, words="message number %d of mine" % index)["prompt"])
            self.h.tick(advance=1)
            self.h.tick(advance=10)
            self.h.tick(advance=901)
        for prompt in found:
            row = plug.runtime.state.prompt(prompt)
            self.assertEqual((row["state"], row["reason"]), (PromptState.DONE, PromptReason.DELIVERED))
        return found

    def clear(self, plug, prompts, generation=None):
        generation = plug.runtime.state.meta()["generation"] if generation is None else generation
        return surfaces.bridge(plug.runtime, "advanced-prompts-clear-done", {"prompts": prompts, "generation": generation})

    def records(self, plug):
        with contextlib.closing(sqlite3.connect(plug.runtime.state.path)) as connection:
            return connection.execute("SELECT record_id, state FROM records ORDER BY record_id").fetchall()


class ClearTests(ClearCase):
    def test_the_completed_ones_shown_are_deleted_and_counted(self):
        """Fails with Delete completed reverted: the bridge passes the command over, and every row stays."""
        plug = self.on()
        done = self.delivered(plug, 2)
        shown = surfaces.bridge(plug.runtime, "advanced-prompts", {})
        self.assertEqual([item["completed"] for item in shown["prompts"]], [True, True])
        answer = self.clear(plug, done)
        self.assertTrue(answer["done"], answer)
        self.assertEqual((answer["deleted"], answer["skipped"]), (2, 0))
        self.assertEqual(plug.runtime.state.prompts(pending=None), [])
        self.assertEqual(answer["prompts"], [], "the list it answers with is read after the delete")

    def test_no_row_the_caps_count_is_touched(self):
        """Each delivered message's occurrence is a row of `records` that the one claim counts against core's caps
        (ledger.py): deleting the message from the list leaves it, so nothing can be sent sooner for it."""
        plug = self.on()
        done = self.delivered(plug, 2)
        before = self.records(plug)
        self.assertEqual(len(before), 2)
        self.clear(plug, done)
        self.assertEqual(self.records(plug), before)

    def test_waiting_held_cancelled_uncertain_and_failed_ones_are_kept_and_counted(self):
        """Fails with the reasons not held to completed work: an uncertain or expired message would be deleted."""
        plug = self.on()
        (done,) = self.delivered(plug, 1)
        state = plug.runtime.state
        waiting = self.add(plug, words="still to go", trigger="at_time", at=self.h.now + 7200)["prompt"]
        held = self.add(plug, words="waits for the one before", depends=True)["prompt"]
        state.cancel_prompt(waiting, at=self.h.now)
        self.h.tick(advance=1)
        self.assertEqual(state.prompt(held)["state"], PromptState.HELD)
        cancelled = waiting
        uncertain = self.add(plug, words="its arrival unproven", trigger="at_time", at=self.h.now + 7200)["prompt"]
        state.change_prompt(uncertain, state=PromptState.DONE, reason=PromptReason.UNKNOWN, finished_at=self.h.now)
        expired = self.add(plug, words="never went", trigger="at_time", at=self.h.now + 7200)["prompt"]
        state.change_prompt(expired, state=PromptState.DONE, reason=PromptReason.EXPIRED, finished_at=self.h.now)
        kept = [held, cancelled, uncertain, expired]
        shown = {item["prompt_id"]: item["completed"] for item in surfaces.bridge(plug.runtime, "advanced-prompts",
                                                                                   {})["prompts"]}
        self.assertEqual({prompt: shown[prompt] for prompt in [done] + kept},
                         {done: True, held: False, cancelled: False, uncertain: False, expired: False})
        answer = self.clear(plug, [done] + kept)
        self.assertEqual((answer["deleted"], answer["skipped"]), (1, 4))
        self.assertIsNone(state.prompt(done))
        for prompt in kept:
            with self.subTest(prompt=prompt):
                self.assertIsNotNone(state.prompt(prompt))

    def test_one_gone_since_the_list_was_read_is_kept_as_changed(self):
        plug = self.on()
        first, second = self.delivered(plug, 2)
        self.clear(plug, [first])
        answer = self.clear(plug, [first, second])
        self.assertEqual((answer["deleted"], answer["skipped"]), (1, 1))

    def test_a_stale_generation_deletes_nothing(self):
        """Fails with the generation not checked: a list read before something moved would be acted on."""
        plug = self.on()
        done = self.delivered(plug, 1)
        stale = plug.runtime.state.meta()["generation"] - 1
        answer = self.clear(plug, done, generation=stale)
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.STALE_GENERATION))
        self.assertIsNotNone(plug.runtime.state.prompt(done[0]))
        # Checked in the deleting transaction too, whatever the bridge read.
        from codex_auto_resume_advanced.state.choices import Refused
        with self.assertRaises(Refused):
            plug.runtime.state.clear_done(done, stale)
        self.assertIsNotNone(plug.runtime.state.prompt(done[0]))

    def test_ids_that_are_not_a_list_of_prompts_are_refused(self):
        plug = self.on()
        done = self.delivered(plug, 1)
        for prompts in ([], None, "1", [done[0], done[0]], [str(done[0])], [1.0], [True]):
            with self.subTest(prompts=prompts):
                answer = self.clear(plug, prompts)
                self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.INVALID_REQUEST))
        self.assertIsNotNone(plug.runtime.state.prompt(done[0]))

    def test_its_arguments_are_the_ids_and_the_generation_alone(self):
        plug = self.on()
        done = self.delivered(plug, 1)
        answer = surfaces.bridge(plug.runtime, "advanced-prompts-clear-done",
                                 {"prompts": done, "generation": plug.runtime.state.meta()["generation"],
                                  "thread_id": "x"})
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.INVALID_REQUEST))
        self.assertNotIn(surfaces.BridgeCommand.ADVANCED_PROMPTS_CLEAR_DONE, surfaces.UNANSWERED)


if __name__ == "__main__":
    unittest.main()
