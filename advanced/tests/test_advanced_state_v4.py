"""The advanced state's version 4 (v0.6.15-beta): the continuations, the conversations kept going and the queued
prompts - their tables, the closed words the file holds them to, and the ways they are written.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import test_advanced_state as base  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume_advanced.state import EVENT_MAX_AGE, Refused  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.state.prompts import PER_CONVERSATION, PROMPTS_LIMIT  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (ContinuationReason, KeepReason, KeepState,  # noqa: E402
                                                   PromptReason, PromptState, RecordState, Refusal)

DAY = 86400
THREAD2 = "0a1b2c3d-0002-7000-8000-000000000002"
QUEUE = "0a1b2c3d-0004-7000-8000-000000000004"
WORDS = "The last turn ended without a reply. Please continue from where you stopped."


def key(n):
    return "%064x" % (1000 + n)


class TableTests(StateCase):
    def test_version_four_has_the_three_tables_and_they_start_empty(self):
        state = self.state()
        self.assertGreaterEqual(schema_module.SCHEMA_VERSION, 4)
        for name in schema_module.V4_TABLES:
            self.assertIn(name, schema_module.TABLES)
        state.set_keep_going(ac.THREAD, 2)
        state.keep_going(ac.THREAD)
        self.assertEqual((state.continuations(), state.prompts()), ([], []))

    def test_a_version_three_file_takes_the_new_words_once_brought_to_four(self):
        """Fails with `overrides` not made again: its old CHECK refuses queue_for_open, as `options`' refuses days."""
        case = base.ResetStateTests("test_a_version_three_file_is_brought_to_version_four_and_keeps_every_row")
        case.paths, case.now = self.paths, self.now
        path = case.version_three()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO overrides VALUES (?, 'test_wake', 'queue_for_open', 1, NULL)",
                                   (key(0),))
        opened = self.state()
        opened.arming()                                      # first read: brought to this version
        opened.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute("INSERT INTO overrides VALUES (?, 'test_wake', 'queue_for_open', 1, NULL)", (key(0),))
            connection.execute("INSERT INTO options VALUES ('test_wake', 'days', 5)")
            for name in schema_module.V4_TABLES:
                self.assertEqual(connection.execute("SELECT count(*) FROM %s" % name).fetchone()[0], 0)


class CheckTests(StateCase):
    """The file itself refuses what the code never writes."""

    def refused(self, state, statement, values=()):
        connection = self.__dict__.get("_raw") or self.__dict__.setdefault("_raw", self.raw(state))
        with self.assertRaises(sqlite3.IntegrityError, msg=statement):
            connection.execute(statement, values)
        connection.rollback()

    def prompt_row(self, **changes):
        row = dict(thread_id=ac.THREAD, words="'mine'", trigger="'recurring'", at=self.now, every="'day'",
                   occurrences=3, sent_count=0, until=self.now + DAY, depends=0, position=0, state="'waiting'",
                   created_at=self.now)
        row.update(changes)
        return ("INSERT INTO prompts (%s) VALUES (%s)"
                % (", ".join(row), ", ".join("'%s'" % value if name == "thread_id" else str(value)
                                              for name, value in row.items())))

    def test_a_prompt_s_shape_is_held_by_the_file(self):
        state = self.state()
        state.set_keep_going(ac.THREAD, 1)                    # the file made
        connection = self.__dict__.setdefault("_raw", self.raw(state))
        connection.execute(self.prompt_row())                  # the shape the code writes
        connection.commit()
        for changes in ({"state": "'done'"},                   # words on a finished prompt
                        {"until": self.now + 31 * DAY},        # a series past 30 days
                        {"occurrences": 31},                   # past 30 occurrences
                        {"trigger": "'at_time'", "every": "NULL"},  # several occurrences of a one-time prompt
                        {"every": "NULL"},                     # a recurring prompt without its every
                        {"every": "'month'"}, {"trigger": "'soon'"}, {"state": "'sent'"},
                        {"reason": "'whatever'"}, {"sent_count": 4}, {"words": "''"}):
            with self.subTest(changes):
                self.refused(state, self.prompt_row(**changes))

    def test_a_continuation_s_and_a_kept_conversation_s_words_are_closed(self):
        state = self.state()
        state.set_keep_going(ac.THREAD, 1)
        for statement in (
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, created_at) "
                "VALUES ('%s', 'reset_message', 'empty_response', '%s', 1, 1)" % (key(1), ac.THREAD),
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, created_at) "
                "VALUES ('%s', 'empty_response', 'chatter', '%s', 1, 1)" % (key(1), ac.THREAD),
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, created_at, reason) "
                "VALUES ('%s', 'empty_response', 'empty_response', '%s', 1, 1, 'because')" % (key(1), ac.THREAD),
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, created_at, words, finished_at) "
                "VALUES ('%s', 'empty_response', 'empty_response', '%s', 1, 1, 'x', 2)" % (key(1), ac.THREAD),
                "INSERT INTO keep_going VALUES ('%s', 11, 0, 1, 'on', NULL, NULL)" % THREAD2,
                "INSERT INTO keep_going VALUES ('%s', 2, 3, 1, 'on', NULL, NULL)" % THREAD2,
                "INSERT INTO keep_going VALUES ('%s', 2, 0, 1, 'paused', NULL, NULL)" % THREAD2):
            with self.subTest(statement):
                self.refused(state, statement)


class ContinuationTests(StateCase):
    def test_a_turn_is_answered_once_and_its_words_go_when_it_is_sent(self):
        state = self.state()
        self.assertTrue(state.add_continuation(key(1), "empty_response", "empty_response", ac.THREAD, WORDS,
                                               ordinal=4))
        self.assertFalse(state.add_continuation(key(1), "empty_response", "empty_response", ac.THREAD, WORDS,
                                                ordinal=4), "one turn, one answer")
        found = state.continuation(key(1))
        self.assertEqual((found["words"], found["record_state"], found["chain"]), (WORDS, RecordState.WAITING, 1))
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            connection.execute("UPDATE records SET state=?, claimed_at=? WHERE record_id=?",
                               (RecordState.IN_FLIGHT, self.now, key(1)))
            connection.commit()
        self.assertEqual(state.continuation_moved(key(1), "sent", queue_id=QUEUE),
                         {"capability": "empty_response", "trip": False})
        found = state.continuation(key(1))
        self.assertEqual((found["words"], found["queue_id"]), (None, QUEUE))
        self.assertEqual(state.continuation_moved(key(1), "delivered")["trip"], False)
        found = state.continuation(key(1))
        self.assertEqual((found["reason"], found["record_state"]), (ContinuationReason.DELIVERED, RecordState.FINISHED))
        self.assertIsNone(state.continuation_moved(key(1), "unproven"), "a finished one moves no more")

    def test_each_end_has_its_reason_and_only_unproven_trips(self):
        state = self.state()
        for n, (move, reason) in enumerate((("unproven", ContinuationReason.UNKNOWN),
                                            ("superseded", ContinuationReason.SUPERSEDED),
                                            ("handed_over", ContinuationReason.HANDED_OVER),
                                            ("withdrawn", ContinuationReason.WITHDRAWN))):
            with self.subTest(move):
                state.add_continuation(key(10 + n), "keep_going", "keep_going", ac.THREAD, WORDS, ordinal=n)
                self.assertEqual(state.continuation_moved(key(10 + n), move)["trip"], move == "unproven")
                self.assertEqual(state.continuation(key(10 + n))["reason"], reason)

    def test_a_decision_is_kept_without_a_record_or_words(self):
        state = self.state()
        self.assertTrue(state.note_continuation(key(2), "empty_response", "empty_response", ac.THREAD,
                                                ContinuationReason.GOAL_LEFT, ordinal=3))
        found = state.continuation(key(2))
        self.assertEqual((found["record_id"], found["words"], found["reason"], found["record_state"]),
                         (None, None, ContinuationReason.GOAL_LEFT, None))
        self.assertFalse(state.note_continuation(key(2), "empty_response", "empty_response", ac.THREAD,
                                                 ContinuationReason.GOAL_LEFT))

    def test_turned_off_ends_those_waiting_and_leaves_one_in_flight_to_core(self):
        state = self.state()
        state.add_continuation(key(3), "keep_going", "keep_going", ac.THREAD, WORDS, ordinal=1)
        state.add_continuation(key(4), "keep_going", "keep_going", THREAD2, WORDS, ordinal=1)
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            connection.execute("UPDATE records SET state=? WHERE record_id=?", (RecordState.IN_FLIGHT, key(4)))
            connection.commit()
        self.assertEqual(state.end_continuations(ContinuationReason.TURNED_OFF, capability="keep_going"), 1)
        self.assertEqual((state.continuation(key(3))["words"], state.continuation(key(3))["record_state"]),
                         (None, RecordState.CANCELLED))
        self.assertEqual(state.continuation(key(4))["record_state"], RecordState.IN_FLIGHT)


class KeepGoingTests(StateCase):
    def test_a_count_is_used_up_and_then_the_conversation_is_done(self):
        state = self.state()
        for bad in (0, 11, "2", True):
            with self.subTest(bad), self.assertRaises(Refused) as refused:
                state.set_keep_going(ac.THREAD, bad)
            self.assertEqual(refused.exception.refusal, Refusal.KEEP_COUNT_INVALID)
        state.set_keep_going(ac.THREAD, 2)
        self.assertTrue(state.keep_going_used(ac.THREAD))
        self.assertEqual(state.keep_going(ac.THREAD)["state"], KeepState.ON)
        self.assertTrue(state.keep_going_used(ac.THREAD))
        row = state.keep_going(ac.THREAD)
        self.assertEqual((row["used"], row["state"], row["reason"]), (2, KeepState.DONE, KeepReason.COUNT_SPENT))
        self.assertFalse(state.keep_going_used(ac.THREAD), "none left")

    def test_a_stop_says_why_and_reaches_only_those_on(self):
        state = self.state()
        state.set_keep_going(ac.THREAD, 3)
        state.set_keep_going(THREAD2, 3)
        self.assertEqual(state.stop_keep_going(KeepReason.PLAN_DONE, thread_id=ac.THREAD), 1)
        self.assertEqual(state.stop_keep_going(KeepReason.TURNED_OFF), 1)
        self.assertEqual({row["thread_id"]: row["reason"] for row in state.keep_going()},
                         {ac.THREAD: KeepReason.PLAN_DONE, THREAD2: KeepReason.TURNED_OFF})


class PromptTests(StateCase):
    def test_each_trigger_is_kept_in_its_conversation_s_order(self):
        state = self.state()
        first = state.add_prompt(ac.THREAD, "first of mine", "after_turn")
        second = state.add_prompt(ac.THREAD, "second", "at_time", at=self.now + 3600, depends=True)
        third = state.add_prompt(ac.THREAD, "daily", "recurring", at=self.now + 60, every="day", occurrences=10)
        rows = state.prompts(thread_id=ac.THREAD)
        self.assertEqual([row["prompt_id"] for row in rows], [first, second, third])
        self.assertEqual([row["position"] for row in rows], [0, 1, 2])
        self.assertEqual(rows[0]["due_at"], self.now)
        self.assertEqual((rows[1]["due_at"], rows[1]["depends"]), (self.now + 3600, True))
        self.assertEqual(rows[2]["until"], self.now + schema_module.PROMPT_SPAN, "30 days at most, by default")

    def test_what_is_not_on_offer_is_refused(self):
        state = self.state()
        for words, trigger, options, refusal in (
                ("", "after_turn", {}, Refusal.PROMPT_REFUSED),
                ("   ", "after_turn", {}, Refusal.PROMPT_REFUSED),
                ("x" * 8193, "after_turn", {}, Refusal.PROMPT_REFUSED),
                ("mine", "soon", {}, Refusal.OCCASION_INVALID),
                ("mine", "at_time", {}, Refusal.OCCASION_INVALID),
                ("mine", "at_time", {"at": self.now - 3600}, Refusal.OCCASION_INVALID),
                ("mine", "at_time", {"at": self.now + 60, "occurrences": 2}, Refusal.OCCASION_INVALID),
                ("mine", "recurring", {"at": self.now + 60}, Refusal.OCCASION_INVALID),
                ("mine", "recurring", {"at": self.now + 60, "every": "day", "occurrences": 31},
                 Refusal.OCCASION_INVALID),
                ("mine", "recurring", {"at": self.now + 60, "every": "day", "until": self.now + 31 * DAY},
                 Refusal.OCCASION_INVALID),
                ("mine", "after_turn", {"at": self.now + 60}, Refusal.OCCASION_INVALID),
                ("mine", "after_turn", {"depends": True}, Refusal.DEPENDENCY_UNKNOWN)):
            with self.subTest(trigger=trigger, options=options, words=words[:8]):
                with self.assertRaises(Refused) as refused:
                    state.add_prompt(ac.THREAD, words, trigger, **options)
                self.assertEqual(refused.exception.refusal, refusal)
        self.assertEqual(state.prompts(), [])

    def test_as_many_as_may_wait_to_a_conversation_and_in_all(self):
        state = self.state()
        for n in range(PER_CONVERSATION):
            state.add_prompt(ac.THREAD, "mine %d" % n, "after_turn")
        with self.assertRaises(Refused) as refused:
            state.add_prompt(ac.THREAD, "one more", "after_turn")
        self.assertEqual(refused.exception.refusal, Refusal.QUEUE_FULL)
        threads = ["0a1b2c3d-0003-7000-8000-%012d" % n for n in range(PROMPTS_LIMIT)]
        added = PER_CONVERSATION
        for thread in threads:
            while added < PROMPTS_LIMIT and len(state.prompts(thread_id=thread)) < 2:
                state.add_prompt(thread, "mine", "after_turn")
                added += 1
        with self.assertRaises(Refused) as refused:
            state.add_prompt(THREAD2, "one more", "after_turn")
        self.assertEqual(refused.exception.refusal, Refusal.QUEUE_FULL)

    def test_a_cancel_takes_the_words_or_asks_core_for_one_codex_holds(self):
        state = self.state()
        waiting = state.add_prompt(ac.THREAD, "mine", "after_turn")
        self.assertEqual(state.cancel_prompt(waiting), "cancelled")
        row = state.prompt(waiting)
        self.assertEqual((row["state"], row["reason"], row["words"]), (PromptState.CANCELLED, PromptReason.BY_PERSON,
                                                                       None))
        queued = state.add_prompt(ac.THREAD, "mine again", "after_turn")
        state.add_record(key(5), "test_wake", ac.THREAD)
        state.change_prompt(queued, state=PromptState.READY, record_id=key(5), sent_at=self.now)
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            connection.execute("UPDATE records SET state=? WHERE record_id=?", (RecordState.IN_FLIGHT, key(5)))
            connection.commit()
        self.assertEqual(state.cancel_prompt(queued), "withdrawing")
        self.assertTrue(state.prompt(queued)["withdraw"])
        state.change_prompt(queued, sent_at=None, launching_at=self.now)
        with self.assertRaises(Refused) as refused:
            state.cancel_prompt(queued)
        self.assertEqual(refused.exception.refusal, Refusal.BEING_SENT)

    def test_a_held_prompt_goes_on_and_a_finished_one_lets_its_words_go(self):
        state = self.state()
        state.add_prompt(ac.THREAD, "first", "after_turn")
        second = state.add_prompt(ac.THREAD, "second", "after_turn", depends=True)
        state.change_prompt(second, state=PromptState.HELD, reason=PromptReason.DEPENDENCY_FAILED)
        self.assertTrue(state.go_on_prompt(second))
        self.assertEqual((state.prompt(second)["state"], state.prompt(second)["reason"]), (PromptState.WAITING, None))
        self.assertFalse(state.go_on_prompt(second))
        state.change_prompt(second, state=PromptState.DONE, reason=PromptReason.DELIVERED, finished_at=self.now)
        self.assertIsNone(state.prompt(second)["words"])

    def test_turned_off_ends_every_prompt_not_in_flight(self):
        state = self.state()
        state.add_prompt(ac.THREAD, "first", "after_turn")
        state.add_prompt(THREAD2, "second", "after_turn")
        self.assertEqual(state.end_prompts(PromptReason.CONVERSATION_OFF, thread_id=THREAD2), 1)
        self.assertEqual(state.end_prompts(PromptReason.TURNED_OFF), 1)
        self.assertEqual({row["reason"] for row in state.prompts(pending=False)},
                         {PromptReason.CONVERSATION_OFF, PromptReason.TURNED_OFF})
        self.assertEqual({row["words"] for row in state.prompts(pending=None)}, {None})


class PruneTests(StateCase):
    def test_the_new_tables_are_pruned_and_nothing_still_to_go(self):
        state = self.state()
        old = self.now - EVENT_MAX_AGE - DAY
        state.add_continuation(key(6), "empty_response", "empty_response", ac.THREAD, WORDS, ordinal=1, at=old)
        state.note_continuation(key(7), "empty_response", "empty_response", ac.THREAD,
                                ContinuationReason.CHAIN_SPENT, at=old)
        done = state.add_prompt(ac.THREAD, "old", "after_turn", now=old)
        state.change_prompt(done, state=PromptState.DONE, finished_at=old)
        kept = state.add_prompt(ac.THREAD, "still to go", "after_turn", now=old)
        state.set_keep_going(THREAD2, 1, at=old)
        state.stop_keep_going(KeepReason.BY_PERSON, at=old)
        with state._transaction() as connection:
            state._prune(connection, self.now)
        self.assertEqual([row["answer_id"] for row in state.continuations(pending=None)], [key(6)])
        self.assertEqual([row["prompt_id"] for row in state.prompts(pending=None)], [kept])
        self.assertEqual(state.keep_going(), [])


if __name__ == "__main__":
    unittest.main()
