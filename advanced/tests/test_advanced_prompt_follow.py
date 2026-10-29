"""#50's follow-through (v0.6.20): a delivered scheduled message followed to the end of the work it started - the turn it
started, the limit that cut that turn off, where the recovery of THAT turn stands, and the next cut-off of the recovery's
own turn, to the end (control/follow.py, the bridge's advanced-prompt-follow).

The link is exact where the occurrence's own proof is in Codex's history (core's marker_rows), and by time only where it
is not - said so in the answer, never more. A turn a person started is never linked to the message. Read-only.

The pure rule is held with records of the tests' own; the whole path once against core's own engine and simulated Codex
home (takingcase.py through the prompt queue's harness), the message really sent, delivered and its turn cut off.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_queue import QueueCase, T1  # noqa: E402
from codexsim import USAGE_ERROR  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.control import follow  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand, PromptReason, PromptState, Refusal  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0002-7000-8000-000000000002"
TURN = "0a1b2c3d-00aa-7000-8000-0000000000aa"
TURN_2 = "0a1b2c3d-00ab-7000-8000-0000000000ab"
RECOVERY = "0a1b2c3d-00bb-7000-8000-0000000000bb"
RECOVERY_2 = "0a1b2c3d-00bc-7000-8000-0000000000bc"
PERSONS = "0a1b2c3d-00cc-7000-8000-0000000000cc"
RECORD = "a" * 64
RECORD_2 = "b" * 64
SENT, DELIVERED = 1_790_000_000.0, 1_790_000_060.0
# Core's reader of Codex's history, as the bridge makes it - pointed at the simulated home in BridgeTests.
READ_TURNS = follow.read_turns


def prompt(record=RECORD, sent=SENT, delivered=DELIVERED, thread=THREAD, **more):
    row = {"prompt_id": 1, "thread_id": thread, "record_id": record, "state": "done", "reason": "delivered",
           "sent_at": sent, "due_at": sent, "finished_at": delivered, "sent_count": 1, "occurrences": 1}
    row.update(more)
    return row


def marked(turn, status="completed"):
    """One marker row as core's marker_rows gives it."""
    return {"turn_id": turn, "ordinal": 6, "status": status, "first_unset": False, "starts_turn": True,
            "client_id": None}


def cut(turn, state="waiting_reset", *, interruption=None, started=SENT + 1, detected=SENT + 900, recovery=None,
        parent=None, thread=THREAD, limit="300m", category="usage_limit", outcome=None):
    """One of core's interruptions, as much of it as the follow-through reads."""
    return {"interruption_id": interruption or hashlib.sha256(turn.encode()).hexdigest(), "thread_id": thread,
            "turn_id": turn, "state": state, "category": category, "limit_type": limit, "started_at": started,
            "detected_at": detected, "reset_at": detected + 3600, "outcome_at": outcome, "recovery_turn_id": recovery,
            "recovery_turn_status": None, "parent_interruption_id": parent, "last_error": None, "queue_id": None}


class LinkTests(unittest.TestCase):
    def test_the_exact_link_is_the_turn_its_own_mark_is_in_and_the_cut_off_of_that_turn(self):
        """Fails with the exact link reverted: the turn is not found from the marker rows."""
        answer = follow.follow(prompt(), [marked(TURN, "failed")], [cut(TURN)])
        self.assertEqual((answer["link"], answer["turn_id"]), (follow.EXACT, TURN))
        (step,) = answer["steps"]
        self.assertEqual((step["turn_id"], step["category"], step["limit_type"]), (TURN, "usage_limit", "300m"))
        self.assertEqual((step["stage"], step["code"], answer["end"]), ("waiting", "waiting_reset", "waiting"))

    def test_only_time_ties_them_when_codex_s_history_cannot_be_read_and_the_answer_says_so(self):
        for found in (None, []):
            with self.subTest(found=found):
                answer = follow.follow(prompt(), found, [cut(TURN)])
                self.assertEqual((answer["link"], answer["turn_id"]), (follow.TIME, TURN))
                self.assertIsNone(answer["turn_status"], "nothing claimed of the turn but its cut-off")
                self.assertEqual(len(answer["steps"]), 1)

    def test_a_turn_never_cut_off_finished_or_still_running(self):
        for status, end in (("completed", follow.FINISHED), ("interrupted", follow.FINISHED),
                            ("inProgress", follow.STILL_RUNNING)):
            with self.subTest(status):
                answer = follow.follow(prompt(), [marked(TURN, status)], [])
                self.assertEqual((answer["link"], answer["steps"], answer["end"]), (follow.EXACT, [], end))

    def test_a_recovery_still_waiting_and_one_on_its_way(self):
        self.assertEqual(follow.follow(prompt(), [marked(TURN)], [cut(TURN, "waiting_for_usage")])["end"], "waiting")
        answer = follow.follow(prompt(), [marked(TURN)], [cut(TURN, "queued")])
        self.assertEqual((answer["end"], answer["steps"][0]["code"]), ("recovering", "submitted"))

    def test_a_recovery_that_failed_ends_there_in_history_s_own_word(self):
        for state, code in (("recovery_turn_failed", "recovery_failed"), ("retry_budget_exhausted", "exhausted"),
                            ("failed", "failed_terminal")):
            with self.subTest(state):
                answer = follow.follow(prompt(), [marked(TURN)], [cut(TURN, state, outcome=SENT + 5000)])
                self.assertEqual((answer["end"], answer["steps"][0]["code"]), ("ended", code))
                self.assertEqual(answer["steps"][0]["outcome_at"], SENT + 5000)

    def test_a_recovery_cut_off_again_is_followed_to_its_end(self):
        """Fails with the chain reverted: the follow-through stops at the first cut-off."""
        first = cut(TURN, "recovered", recovery=RECOVERY, outcome=SENT + 4000)
        second = cut(RECOVERY, "recovered", recovery=RECOVERY_2, parent=first["interruption_id"], detected=SENT + 5000,
                     limit="10080m", outcome=SENT + 9000)
        answer = follow.follow(prompt(), [marked(TURN)], [second, first])
        self.assertEqual([step["turn_id"] for step in answer["steps"]], [TURN, RECOVERY])
        self.assertEqual([step["limit_type"] for step in answer["steps"]], ["300m", "10080m"])
        self.assertEqual(answer["end"], "recovered")

    def test_two_messages_in_one_conversation_each_follow_their_own_turn(self):
        records = [cut(TURN, "recovered", outcome=SENT + 4000), cut(TURN_2, "waiting_reset", started=SENT + 7000)]
        first = follow.follow(prompt(), [marked(TURN)], records)
        second = follow.follow(prompt(record=RECORD_2, sent=SENT + 6990, delivered=SENT + 7050), [marked(TURN_2)],
                               records)
        self.assertEqual([step["turn_id"] for step in first["steps"]], [TURN])
        self.assertEqual([step["turn_id"] for step in second["steps"]], [TURN_2])
        self.assertEqual((first["end"], second["end"]), ("recovered", "waiting"))

    def test_a_turn_the_person_started_in_between_is_never_linked_to_the_message(self):
        """The message's turn finished; the person's own turn after it was cut off. Neither the exact link nor the link by
        time names the person's turn."""
        persons = cut(PERSONS, started=DELIVERED + 300, detected=DELIVERED + 900)
        exact = follow.follow(prompt(), [marked(TURN, "completed")], [persons])
        self.assertEqual((exact["steps"], exact["end"]), ([], follow.FINISHED))
        by_time = follow.follow(prompt(), None, [persons])
        self.assertEqual((by_time["link"], by_time["why"], by_time["steps"]), (follow.NONE, follow.NOT_FOUND, []))
        # Nor a cut-off of the recovery of a turn of the person's (its parent), nor one in another conversation.
        theirs = cut(RECOVERY, started=SENT + 2, parent=persons["interruption_id"])
        elsewhere = cut(TURN_2, started=SENT + 2, thread=OTHER)
        self.assertEqual(follow.follow(prompt(), None, [persons, theirs, elsewhere])["link"], follow.NONE)

    def test_two_cut_offs_by_time_or_the_mark_in_two_turns_are_no_link(self):
        records = [cut(TURN, started=SENT + 1), cut(TURN_2, started=SENT + 30)]
        answer = follow.follow(prompt(), None, records)
        self.assertEqual((answer["link"], answer["why"], answer["steps"]), (follow.NONE, follow.AMBIGUOUS, []))
        answer = follow.follow(prompt(), [marked(TURN), marked(TURN_2)], records)
        self.assertEqual((answer["link"], answer["why"]), (follow.NONE, follow.AMBIGUOUS))

    def test_a_message_with_no_occurrence_kept_is_not_linked(self):
        answer = follow.follow(prompt(record=None), [marked(TURN)], [cut(TURN)])
        self.assertEqual((answer["link"], answer["why"]), (follow.NONE, follow.NO_RECORD))

    def test_its_proofs_are_its_marker_then_the_client_id_it_went_under_with_none(self):
        self.assertEqual(follow.proofs(RECORD), (ids.short_marker(RECORD), ids.continuation_client_id(RECORD)))

    def test_it_answers_ids_closed_words_and_times_only(self):
        answer = follow.follow(prompt(), [marked(TURN)], [cut(TURN)])
        self.assertEqual(set(answer["steps"][0]), set(follow.STEP_FIELDS) | {"code", "stage"})


class BridgeTests(QueueCase):
    def delivered(self, plug, running=False):
        """A message after this turn, sent and delivered; its turn left running where `running`."""
        if running:
            self.h.backend.turn_status = "inProgress"
        made = self.add(plug)["prompt"]
        self.h.tick(advance=1)
        self.h.tick(advance=10)
        row = plug.runtime.state.prompt(made)
        self.assertEqual((row["state"], row["reason"]), (PromptState.DONE, PromptReason.DELIVERED))
        return made

    def ask(self, plug, prompt_id):
        """The bridge's answer, Codex's history read from the simulated home and core's records from the harness's
        store - the bridge's own runtime keeps its state elsewhere in this harness."""
        with patch.object(follow, "read_turns", lambda home: READ_TURNS(self.h.home.root)), \
                patch.object(follow, "_records", lambda runtime, thread: [
                    record for record in self.h.store.all_records() if record["thread_id"] == thread]):
            return surfaces.bridge(plug.runtime, "advanced-prompt-follow", {"prompt": prompt_id})

    def digest(self, plug):
        with contextlib.closing(sqlite3.connect(plug.runtime.state.path)) as connection:
            return connection.execute("SELECT * FROM prompts ORDER BY prompt_id").fetchall(), connection.execute(
                "SELECT * FROM records ORDER BY record_id").fetchall()

    def test_a_delivered_message_s_turn_cut_off_by_a_limit_is_followed_through_the_bridge(self):
        """Fails with the command reverted: the bridge passes it over."""
        plug = self.on()
        made = self.delivered(plug, running=True)
        turn = self.h.home.turns(T1)[-1]["turn_id"]
        answer = self.ask(plug, made)
        self.assertTrue(answer["done"], answer)
        self.assertEqual((answer["link"], answer["turn_id"], answer["end"]), (follow.EXACT, turn, follow.STILL_RUNNING))
        self.h.home.set_turn(T1, turn, status="failed", error_json=USAGE_ERROR, completed_at=int(self.h.now))
        self.h.tick(advance=30)
        self.h.tick(advance=30)
        before = self.digest(plug)
        answer = self.ask(plug, made)
        (step,) = answer["steps"]
        self.assertEqual((step["turn_id"], step["category"], step["stage"]), (turn, "usage_limit", "waiting"))
        self.assertEqual(answer["delivered_at"], plug.runtime.state.prompt(made)["finished_at"])
        self.assertEqual(self.digest(plug), before, "nothing written")

    def test_refused_unless_the_queue_stands_and_the_message_was_delivered(self):
        plug = self.on()
        made = self.delivered(plug)
        waiting = self.add(plug, trigger="at_time", at=self.h.now + 3600)["prompt"]
        for argument, refusal in (({"prompt": "1"}, Refusal.INVALID_REQUEST), ({"prompt": waiting}, Refusal.INVALID_REQUEST),
                                  ({"prompt": 999}, Refusal.INVALID_REQUEST), ({"prompt": made, "x": 1}, Refusal.INVALID_REQUEST)):
            with self.subTest(argument):
                self.assertEqual(surfaces.bridge(plug.runtime, "advanced-prompt-follow", argument)["refusal"], refusal)
        plug.runtime.arming.disarm("prompt_queue", actor="dashboard")
        self.assertEqual(self.ask(plug, made)["refusal"], Refusal.NOT_ON)

    def test_it_is_the_dashboard_s_alone(self):
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_PROMPT_FOLLOW], frozenset({"prompt"}))
        self.assertNotIn("advanced-prompt-follow", [tool["name"] for tool in surfaces.TOOLS])


if __name__ == "__main__":
    unittest.main()
