"""Editing a queued message (v0.6.19, issue #50): the Dashboard's editor saves new words, a new time or schedule, whether it
waits for the one before it and its send mode on a message still waiting - checked as a new one is, against the
generation the list was read at - and never on one that moved past waiting (due, being sent, held, finished). A refused
edit leaves the row exactly as it was.

Held against core's own engine and simulated Codex home (takingcase.py) through the prompt queue's harness, the
Dashboard's bridge (surfaces.bridge) as the page asks it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_queue import QueueCase  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.vocabulary import PromptState, Refusal, WhileRunning  # noqa: E402

DAY = 86400


class EditCase(QueueCase):
    def edit(self, plug, prompt, generation=None, **argument):
        argument.setdefault("words", "the words as edited")
        argument.setdefault("trigger", "at_time")
        if argument["trigger"] != "after_turn":
            argument.setdefault("at", self.h.now + 7200)
        argument.update(prompt=prompt, generation=plug.runtime.state.meta()["generation"] if generation is None
                        else generation)
        return surfaces.bridge(plug.runtime, "advanced-prompt-edit", argument)

    def later(self, plug, **argument):
        return self.add(plug, words="the words as written", trigger="at_time", at=self.h.now + 3600, **argument)["prompt"]

    def kept(self, plug, prompt):
        row = plug.runtime.state.prompt(prompt)
        return {name: row[name] for name in ("words", "trigger", "at", "every", "occurrences", "depends", "state",
                                             "while_running", "due_at", "position")}


class EditTests(EditCase):
    def test_a_waiting_message_takes_the_edit_and_keeps_its_place(self):
        """Fails with the edit reverted: the bridge passes the command over and the words stay as written."""
        plug = self.on()
        first = self.later(plug)
        second = self.later(plug)
        answer = self.edit(plug, second, words="carry on, then the links", trigger="recurring", every="day",
                           occurrences=3, at=self.h.now + 600, while_running="wait", depends=True)
        self.assertTrue(answer["done"], answer)
        self.assertEqual(answer["prompt"], second, "the saved row, for the window to select")
        row = plug.runtime.state.prompt(second)
        self.assertEqual((row["words"], row["trigger"], row["every"], row["occurrences"], row["depends"],
                          row["while_running"], row["due_at"], row["state"]),
                         ("carry on, then the links", "recurring", "day", 3, True, WhileRunning.WAIT, self.h.now + 600,
                          PromptState.WAITING))
        self.assertEqual(plug.runtime.state.prompt(first)["position"] + 1, row["position"], "its place kept")

    def test_the_edited_words_are_what_is_sent(self):
        plug = self.on()
        prompt = self.later(plug)
        self.edit(plug, prompt, words="the edited message", trigger="after_turn", while_running="queue")
        self.h.tick(advance=1)
        self.assertEqual(len(self.sends()), 1)
        self.assertTrue(self.sends()[0].startswith("the edited message\n\n"))


class RefusalTests(EditCase):
    def test_a_stale_generation_is_refused_and_the_row_is_kept(self):
        plug = self.on()
        prompt = self.later(plug)
        before = self.kept(plug, prompt)
        answer = self.edit(plug, prompt, generation=plug.runtime.state.meta()["generation"] - 1)
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.STALE_GENERATION))
        self.assertEqual(self.kept(plug, prompt), before)

    def test_only_a_waiting_message_is_edited(self):
        """Fails with the state not checked: an edit would reach a message core may be sending."""
        plug = self.on()
        due = self.add(plug, words="goes at once")["prompt"]
        self.h.tick(advance=1)                               # its occurrence made, and sent
        self.assertNotEqual(plug.runtime.state.prompt(due)["state"], PromptState.WAITING)
        answer = self.edit(plug, due)
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.INVALID_REQUEST))
        cancelled = self.later(plug)
        plug.runtime.state.cancel_prompt(cancelled, at=self.h.now)
        self.assertEqual(self.edit(plug, cancelled)["refusal"], Refusal.INVALID_REQUEST)
        self.assertEqual(self.edit(plug, 9999)["refusal"], Refusal.INVALID_REQUEST)

    def test_what_a_new_message_may_not_be_an_edit_may_not_be_either_and_the_row_is_kept(self):
        plug = self.on()
        prompt = self.later(plug)
        before = self.kept(plug, prompt)
        for change, refusal in (({"words": ""}, Refusal.PROMPT_REFUSED),
                                ({"words": "x" * 2001}, Refusal.PROMPT_REFUSED),
                                ({"at": self.h.now - 7200}, Refusal.OCCASION_INVALID),
                                ({"trigger": "after_turn", "while_running": "wait"}, Refusal.OCCASION_INVALID),
                                ({"trigger": "recurring", "every": "day", "occurrences": 31}, Refusal.OCCASION_INVALID),
                                ({"depends": True}, Refusal.DEPENDENCY_UNKNOWN)):
            with self.subTest(change=change):
                answer = self.edit(plug, prompt, **change)
                self.assertEqual((answer["done"], answer["refusal"]), (False, refusal))
                self.assertEqual(self.kept(plug, prompt), before)

    def test_it_needs_the_queue_standing_and_takes_no_other_argument(self):
        plug = self.on()
        prompt = self.later(plug)
        self.assertEqual(self.edit(plug, prompt, thread_id="x")["refusal"], Refusal.INVALID_REQUEST)
        self.assertNotIn(surfaces.BridgeCommand.ADVANCED_PROMPT_EDIT, surfaces.UNANSWERED)


if __name__ == "__main__":
    unittest.main()
