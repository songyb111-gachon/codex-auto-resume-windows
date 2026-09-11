"""Outcomes, chains, Pause, gates and notifications, end to end.

The v0.6 engine design (sections 3-9) promises what happens to a continuation after it
leaves this tool: which turn it started, how that turn ended, what a failure of that
turn inherits, what a Pause or a Cancel does to it while it is still in Codex's queue,
and what the user is told. These tests drive the real Engine, the real Store and the
real LocalSource over a real Codex home (`codexsim`): the three SQLite databases with
the columns Codex 0.153.4 has, and its rollout files. Only the Codex *processes* are
simulated, so a query that is wrong against the real schema fails here too.

Every expectation is taken from the design, not from what the code happens to do. The
test ids (T13 ... T48) are the ids of the design's section 10.1 table.
"""
from __future__ import annotations

import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from codexsim import BASE, USAGE_ERROR, CodexHome, SimBackend, new_id, transient_error  # noqa: E402

from codex_auto_resume import machine  # noqa: E402
from codex_auto_resume.control import Control  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.source import LocalSource  # noqa: E402
from codex_auto_resume.store import Store, StoreError  # noqa: E402

DAY = 86400.0
SERVER_5XX = transient_error("serverOverloaded")
HISTORY_DB = "thread_history_1.sqlite"


def too_many_attempts(status):
    """Codex's `responseTooManyFailedAttempts` variant carrying an HTTP status."""
    return json.dumps({"codexErrorInfo": {"responseTooManyFailedAttempts": {"httpStatusCode": status}}})


class World:
    """One Codex home, one state directory, one engine, one clock."""

    def __init__(self, test: unittest.TestCase, *, state_dir=None, **options):
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = BASE + 10.0
        self.home = CodexHome(self.root / "codex")
        # Dispatched turns finish "now", on the test's clock.
        self.home.clock = lambda: self.now
        self.state_dir = Path(state_dir) if state_dir else self.root / "state"
        self.store = Store(self.state_dir)
        test.addCleanup(self.store.close)
        self.backend = SimBackend(self.home)
        self.source = LocalSource(self.home.root)
        self.logs: list[tuple] = []
        self.notes: list[tuple] = []
        self.engine = Engine(self.store, self.source, self.backend, clock=lambda: self.now,
                             log=lambda *args: self.logs.append(args),
                             notify=lambda event, detail: self.notes.append((event, detail)),
                             options=options)

    # ------------------------------------------------------------- plumbing
    def enable(self):
        self.store.set_enabled(True, self.now)

    def pause(self):
        self.store.set_enabled(False, self.now)

    def tick(self, advance=0.0):
        self.now += advance
        self.engine.tick()

    def thread(self, loaded=True) -> str:
        thread = new_id()
        self.home.add_thread(thread)
        self.backend.loaded_map[thread] = "loaded" if loaded else "notLoaded"
        return thread

    def fail(self, thread, error_json=SERVER_5XX) -> str:
        """A failed turn on `thread`, finished now, that is the thread's latest turn."""
        return self.home.fail_transient(thread, completed=int(self.now), error_json=error_json)

    def records(self, thread) -> list:
        return [row for row in self.store.all_records() if row["thread_id"] == thread]

    def only(self, thread) -> dict:
        rows = self.records(thread)
        assert len(rows) == 1, [row["state"] for row in rows]
        return rows[0]

    def get(self, key) -> dict:
        return self.store.get(key)

    def sends(self, thread=None) -> int:
        return sum(1 for sent, _ in self.backend.send_calls if thread is None or sent == thread)

    def notes_for(self, key) -> list:
        return [(event, detail.get("state")) for event, detail in self.notes
                if detail.get("interruption_id") == key]

    def event_codes(self, key) -> list:
        return [entry["code"] for entry in self.store.events(key)]

    def tick_until_sent(self, thread, step=5.0, limit=60) -> bool:
        before = self.sends(thread)
        for _ in range(limit):
            self.tick(step)
            if self.sends(thread) > before:
                return True
        return False

    # -------------------------------------------------------- Codex history
    def history(self):
        return closing(sqlite3.connect(self.home.root / HISTORY_DB))

    def drop_projection_table(self):
        with self.history() as db:
            db.execute("DROP TABLE thread_history_projection_state")
            db.commit()

    def delete_turn_row(self, thread, turn):
        with self.history() as db:
            db.execute("DELETE FROM thread_turns WHERE thread_id=? AND turn_id=?", (thread, turn))
            db.commit()

    def finish(self, thread, turn, status, error_json=None):
        """Codex finishing a turn row that was projected as running."""
        self.home.set_turn(thread, turn, status=status, completed_at=int(self.now), error_json=error_json)

    # ------------------------------------------------------------ scenarios
    def queued(self, thread=None, error_json=SERVER_5XX):
        """A transient failure, recorded and sent; the continuation waits in Codex's queue."""
        thread = thread or self.thread()
        self.backend.after_accept = "queue"
        self.fail(thread, error_json)
        self.tick()
        key = self.only(thread)["interruption_id"]
        assert self.tick_until_sent(thread), self.logs
        assert self.get(key)["state"] == "queued", self.get(key)["state"]
        return thread, key

    def started(self, thread=None, *, status="inProgress", progress=True, steer_user=False):
        """As `queued`, then Codex dispatches it and the watch correlates the turn."""
        thread, key = self.queued(thread)
        turn = self.home.dispatch(thread, status=status, progress=progress, steer_user=steer_user)
        self.tick(1)
        return thread, key, turn


class Base(unittest.TestCase):
    def world(self, **options) -> World:
        return World(self, **options)


# =====================================================================================
# T13-T17: how the recovery turn ended (design 4.2, 4.3)
# =====================================================================================
class T13OutcomeRulesTests(Base):
    def test_T13_a_row_that_stays_in_progress_becomes_unverified_at_the_deadline(self):
        """A turn row can stay `inProgress` forever after a crash (U4). The record is
        followed for 24 h and then left as unverified - never as a success, never as
        no progress."""
        w = self.world()
        w.enable()
        thread, key, _ = w.started()
        row = w.get(key)
        self.assertEqual(row["state"], "turn_started")
        started_at = row["turn_started_at"]
        w.now = started_at + 24 * 3600 - 1
        w.tick()
        self.assertEqual(w.get(key)["state"], "turn_started")
        self.assertEqual(w.get(key)["recovery_turn_status"], "inProgress")
        w.now = started_at + 24 * 3600
        w.tick()
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("outcome_unverified", "outcome_deadline"))
        self.assertEqual(machine.public_code(row), "outcome_unverified")
        self.assertIsNotNone(row["outcome_at"])

    def test_T13_a_later_terminal_turn_proves_an_in_progress_row_stale(self):
        """Codex only updates the running turn's row, so a later finished turn means
        ours can never finish: `outcome_unverified(stale_turn_row)`, without waiting
        for the deadline."""
        w = self.world()
        w.enable()
        thread, key, turn = w.started()
        self.assertEqual(w.get(key)["state"], "turn_started")
        w.home.add_turn(thread, status="completed")
        w.tick(30)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("outcome_unverified", "stale_turn_row"))
        self.assertEqual(row["recovery_turn_id"], turn)

    def test_T13_an_interrupted_recovery_turn_is_stopped_by_the_user(self):
        w = self.world()
        w.enable()
        thread, key, turn = w.started()
        w.finish(thread, turn, "interrupted")
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "turn_completed")
        w.tick(11)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("stopped_by_user", "turn_interrupted"))
        self.assertEqual(row["recovery_turn_status"], "interrupted")
        self.assertEqual(machine.public_code(row), "stopped_by_user")

    def test_T13_an_unknown_status_string_is_unverified(self):
        """A status Codex adds later is stored as `other` (M8) and never guessed at."""
        w = self.world()
        w.enable()
        thread, key, turn = w.started()
        w.home.set_turn(thread, turn, status="pausedForReview", completed_at=int(w.now))
        w.tick(1)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("outcome_unverified", "unknown_turn_status"))
        self.assertEqual(row["recovery_turn_status"], "other")

    def test_T13_unreadable_history_is_retried_then_hits_the_deadline_never_no_progress(self):
        """The turn really did complete with no output, but the engine cannot read
        that: an unreadable history is UNKNOWN, retried every tick, and at the deadline
        the record is unverified - it is never shown as "no progress"."""
        w = self.world()
        w.enable()
        thread, key, turn = w.started(progress=False)
        w.finish(thread, turn, "completed")
        history = w.home.root / HISTORY_DB
        history.rename(history.with_name(HISTORY_DB + ".away"))
        started_at = w.get(key)["turn_started_at"]
        for _ in range(23):
            w.tick(3600)
            row = w.get(key)
            self.assertEqual(row["state"], "turn_started")
            self.assertNotEqual(machine.public_code(row), "no_progress")
        w.now = started_at + 24 * 3600
        w.tick()
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("outcome_unverified", "outcome_deadline"))
        self.assertNotIn("completed_no_progress", [entry[1] for entry in w.logs])

    def test_T13_history_that_becomes_readable_again_is_evaluated_normally(self):
        """"Retried" means exactly that: once the history can be read again, the
        outcome is evaluated as if nothing happened."""
        w = self.world()
        w.enable()
        thread, key, turn = w.started(progress=True)
        w.finish(thread, turn, "completed")
        history = w.home.root / HISTORY_DB
        away = history.with_name(HISTORY_DB + ".away")
        history.rename(away)
        for _ in range(3):
            w.tick(60)
            self.assertEqual(w.get(key)["state"], "turn_started")
        away.rename(history)
        w.tick(1)
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "recovered")


class T14SettleTests(Base):
    def test_T14_completed_before_its_agent_item_is_projected_is_not_judged_early(self):
        """Codex can mark a turn completed before its last items are projected. The
        result is judged only at `completed_at + 10 s`, so the late agent message
        counts: recovered, not no progress."""
        w = self.world()
        w.enable()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="completed", progress=False)
        completed = w.home.turns(thread)[-1]["completed_at"]
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "turn_completed")
        w.now = completed + 5
        w.tick()
        self.assertEqual(w.get(key)["state"], "turn_completed")     # no evaluation yet
        w.home.add_item(thread, turn, "agentMessage")
        w.now = completed + 10
        w.tick()
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("recovered", "progress_observed"))

    def test_T14_a_terminal_status_first_seen_late_still_waits_one_more_tick(self):
        """Even when the watcher first sees the finished turn long after
        `completed_at + 10 s`, it judges it on a later tick, not the one that first
        saw it."""
        w = self.world()
        w.enable()
        thread, key, turn = w.started(progress=False)
        w.finish(thread, turn, "completed")
        w.tick(60)
        self.assertEqual(w.get(key)["state"], "turn_completed")
        w.home.add_item(thread, turn, "agentMessage")
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "recovered")


class T15NoProgressTests(Base):
    def test_T15_a_zero_output_completed_turn_is_no_progress_and_not_recovered(self):
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.home.dispatch(thread, status="completed", progress=False)
        w.tick(1)
        w.tick(11)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("completed_no_progress", "no_progress_observed"))
        self.assertEqual(machine.public_code(row), "no_progress")
        stats = w.store.statistics()
        self.assertEqual(stats["outcomes"]["no_progress"], 1)
        self.assertEqual(stats["outcomes"]["recovered"], 0)
        self.assertEqual(stats["success_denominator"], 1)

    def test_T15_a_zero_output_failed_recovery_turn_counts_as_no_progress_in_the_chain(self):
        """In the chain, a recovery turn that produced nothing adds one to the child's
        no-progress count; one that produced something adds nothing."""
        for progress, expected in ((False, 1), (True, 0)):
            with self.subTest(progress=progress):
                w = self.world()
                w.enable()
                thread, key = w.queued()
                turn = w.home.dispatch(thread, status="inProgress", progress=progress)
                w.finish(thread, turn, "failed", SERVER_5XX)
                w.tick(1)
                child = w.records(thread)[-1]
                self.assertEqual(child["parent_interruption_id"], key)
                self.assertEqual(child["no_progress_count"], expected)


class T16UserJoinedTests(Base):
    def join(self, client_id):
        w = self.world()
        w.enable()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress")
        w.home.add_item(thread, turn, "userMessage", "typed while it ran", client_id)
        return w, thread, key, turn

    def test_T16_an_extra_user_message_hands_the_turn_over_at_once(self):
        """Whoever wrote it, and whatever its clientId, a user message without our
        marker in our turn means the turn is shared now: handed over immediately,
        while the turn is still running."""
        for client_id in (None, "0a1b2c3d-0016-7000-8000-000000000001"):
            with self.subTest(client_id=client_id):
                w, thread, key, turn = self.join(client_id)
                w.tick(1)
                row = w.get(key)
                self.assertEqual((row["state"], row["last_error"]), ("handed_over", "user_joined"))
                self.assertTrue(row["user_joined"])
                self.assertEqual(row["recovery_turn_id"], turn)
                self.assertEqual(w.home.turns(thread)[-1]["status"], "inProgress")

    def test_T16_a_steered_message_from_codexsim_is_seen_the_same_way(self):
        w = self.world()
        w.enable()
        thread, key, _ = w.started(steer_user=True)
        self.assertEqual(w.get(key)["state"], "handed_over")

    def test_T16_when_the_handed_over_turn_fails_the_child_is_superseded_and_never_claimed(self):
        w, thread, key, turn = self.join(None)
        w.tick(1)
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        rows = w.records(thread)
        self.assertEqual(len(rows), 2)
        child = rows[-1]
        self.assertEqual((child["state"], child["last_error"]), ("superseded", "parent_handed_over"))
        self.assertEqual(child["parent_interruption_id"], key)
        for _ in range(20):
            w.tick(300)
        child = w.get(child["interruption_id"])
        self.assertIsNone(child["last_claim_at"])
        self.assertIsNone(child["submitted_at"])
        self.assertEqual(w.sends(thread), 1)


class T17StuckObservingTests(Base):
    def test_T17_a_newer_failure_closes_a_stale_observing_record_and_is_recovered(self):
        """Our turn row stays `inProgress` after a crash; the user carries on and their
        turn fails. That failure is recovered, and it proves our row stale."""
        w = self.world()
        w.enable()
        thread, first, _ = w.started()
        self.assertEqual(w.get(first)["state"], "turn_started")
        w.fail(thread)
        w.tick(1)
        self.assertEqual((w.get(first)["state"], w.get(first)["last_error"]),
                         ("outcome_unverified", "stale_turn_row"))
        newer = [row for row in w.records(thread) if row["interruption_id"] != first]
        self.assertEqual(len(newer), 1)
        self.assertIsNone(newer[0]["parent_interruption_id"])
        # The per-thread cooldown after our own claim still applies; it is a wait, not a block.
        self.assertTrue(w.tick_until_sent(thread, step=60, limit=30))
        self.assertEqual(w.sends(thread), 2)

    def test_T17_an_observing_record_the_engine_cannot_close_does_not_block(self):
        """submission_safe is per record: a record still in OBSERVING - here one whose
        turn row cannot be read at all - never holds up a newer failure's claim."""
        w = self.world()
        w.enable()
        thread, first, turn = w.started()
        w.delete_turn_row(thread, turn)
        w.fail(thread)
        w.tick(1)
        self.assertEqual(w.get(first)["state"], "turn_started")
        self.assertTrue(w.tick_until_sent(thread, step=60, limit=30))
        self.assertEqual(w.get(first)["state"], "turn_started")   # still stuck, still not blocking
        newer = [row for row in w.records(thread) if row["interruption_id"] != first][0]
        gates = machine.decode_gates(newer["gate_eval"])
        self.assertEqual(gates["submission_safe"][0], machine.PASS)


# =====================================================================================
# T18-T23: chains, budgets and cancel (design 4.4, 7.2)
# =====================================================================================
class ChainBase(Base):
    CHAIN_OPTIONS = {"thread_cooldown_seconds": 0, "max_submissions_per_thread_per_day": 1000}

    def chain(self, *, error_json, progress, step, hops=12, **options):
        """Every continuation starts a turn that fails at once, the same way."""
        w = self.world(**{**self.CHAIN_OPTIONS, **options})
        w.enable()
        w.backend.after_accept = "queue"
        thread = w.thread()
        w.fail(thread, error_json)
        w.tick()
        for _ in range(hops):
            if not w.tick_until_sent(thread, step=step, limit=40):
                break
            turn = w.home.dispatch(thread, status="inProgress", progress=progress)
            w.finish(thread, turn, "failed", error_json)
            w.tick(1)
        return w, thread, w.records(thread)

    def assert_linked(self, rows):
        root = rows[0]
        self.assertIsNone(root["parent_interruption_id"])
        for parent, child in zip(rows, rows[1:]):
            self.assertEqual(child["parent_interruption_id"], parent["interruption_id"])
            self.assertEqual(child["chain_origin_id"], root["interruption_id"])
            self.assertEqual(parent["recovery_turn_id"], child["turn_id"])


class T18ChainTests(ChainBase):
    def test_T18_a_transient_chain_stops_at_the_chain_cap(self):
        w, thread, rows = self.chain(error_json=SERVER_5XX, progress=True, step=5,
                                     max_chain_continuations=3, max_recovery_attempts=10)
        self.assertEqual(w.sends(thread), 3)
        self.assertEqual(len(rows), 4)
        self.assert_linked(rows)
        self.assertEqual([row["chain_continuations"] for row in rows], [1, 2, 3, 3])
        self.assertEqual((rows[-1]["state"], rows[-1]["last_error"]), ("retry_budget_exhausted", "chain_cap"))

    def test_T18_a_transient_chain_stops_at_the_recovery_budget_across_rows(self):
        w, thread, rows = self.chain(error_json=SERVER_5XX, progress=True, step=5,
                                     max_chain_continuations=10, max_recovery_attempts=2)
        self.assertEqual(w.sends(thread), 2)
        self.assertEqual(len(rows), 3)
        self.assert_linked(rows)
        self.assertEqual([row["recovery_attempts"] for row in rows], [1, 2, 2])
        self.assertEqual((rows[-1]["state"], rows[-1]["last_error"]),
                         ("retry_budget_exhausted", "recovery_budget"))

    def test_T18_a_usage_chain_stops_at_the_chain_cap_whatever_the_attempt_budget(self):
        """A usage limit does not spend recovery attempts, so only the chain cap bounds
        a plan condition that makes every continuation fail at once."""
        w, thread, rows = self.chain(error_json=USAGE_ERROR, progress=True, step=900,
                                     max_chain_continuations=3, max_recovery_attempts=1)
        self.assertEqual(w.sends(thread), 3)
        self.assertEqual(len(rows), 4)
        self.assert_linked(rows)
        self.assertTrue(all(row["category"] == "usage_limit" for row in rows))
        self.assertEqual((rows[-1]["state"], rows[-1]["last_error"]), ("retry_budget_exhausted", "chain_cap"))

    def test_T18_no_progress_carries_over_the_recovery_turn_link(self):
        w, thread, rows = self.chain(error_json=SERVER_5XX, progress=False, step=5,
                                     max_chain_continuations=10, max_recovery_attempts=10,
                                     max_no_progress=3)
        self.assertEqual(w.sends(thread), 3)
        self.assert_linked(rows)
        self.assertEqual([row["no_progress_count"] for row in rows], [0, 1, 2, 3])
        self.assertEqual((rows[-1]["state"], rows[-1]["last_error"]),
                         ("no_progress_exhausted", "no_progress_budget"))

    def test_T18_usage_unavailable_time_carries_over_and_expires_the_chain(self):
        """The 7-day "never available" bound belongs to the task, not to each record:
        a child starts from its parent's accumulated time."""
        w = self.world(**self.CHAIN_OPTIONS)
        w.enable()
        w.backend.after_accept = "queue"
        thread = w.thread()
        w.home.fail_usage(thread, completed=int(w.now), reset=None)
        w.tick()
        root = w.only(thread)["interruption_id"]
        w.backend.usage_result = {"available": False, "reset_at": None, "limit_type": "x", "reason": "x"}
        for _ in range(3 * 96 + 1):
            w.tick(900)
        inherited = w.get(root)["usage_unavailable_seconds"]
        self.assertAlmostEqual(inherited, 3 * DAY, delta=1800)
        w.backend.usage_result = {"available": True, "reset_at": None, "limit_type": "x", "reason": "ok"}
        self.assertTrue(w.tick_until_sent(thread, step=900))
        turn = w.home.dispatch(thread, status="inProgress", progress=True)
        w.finish(thread, turn, "failed", USAGE_ERROR)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual(child["parent_interruption_id"], root)
        self.assertEqual(child["usage_unavailable_seconds"], inherited)
        w.backend.usage_result = {"available": False, "reset_at": None, "limit_type": "x", "reason": "x"}
        began = w.now
        for _ in range(8 * 96):
            w.tick(900)
            if w.get(child["interruption_id"])["state"] == "terminal_failure":
                break
        row = w.get(child["interruption_id"])
        self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "usage_never_available"))
        # The child needed only what the chain had left, not 7 days of its own.
        self.assertLess(w.now - began, 7 * DAY - inherited + 2 * 3600)


class T20LineageTests(Base):
    def test_T20_a_cancelled_parent_makes_its_failed_turn_a_cancelled_child_in_the_same_tick(self):
        """Cancel while our turn runs only marks the record. When that turn then fails,
        its child is registered already cancelled - before the parent's own outcome
        has even been evaluated."""
        w = self.world()
        w.enable()
        thread, key, turn = w.started()
        result = w.store.cancel_interruption(key, w.now, actor="gui")
        self.assertEqual(result["effects"][key], "cancel_requested")
        self.assertEqual(w.get(key)["state"], "turn_started")
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        parent = w.get(key)
        self.assertEqual(parent["state"], "turn_completed")       # outcome not yet evaluated
        child = w.records(thread)[-1]
        self.assertEqual(child["parent_interruption_id"], key)
        self.assertEqual((child["state"], child["last_error"]), ("cancelled", "parent_cancelled"))
        self.assertTrue(child["cancel_requested"])
        for _ in range(10):
            w.tick(300)
        self.assertEqual(w.sends(thread), 1)

    def test_T20_a_parent_that_ran_after_user_work_makes_the_child_superseded(self):
        """The user's own turn ran between the failure and ours (Codex dispatches the
        queue head the moment their turn ends). Our turn then fails: the child is not
        recovered on top of the user's work."""
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.home.add_turn(thread, status="completed")                 # the user's turn
        turn = w.home.dispatch(thread, status="inProgress")          # ours, right after it
        w.tick(1)
        parent = w.get(key)
        self.assertEqual(parent["state"], "turn_started")
        self.assertTrue(parent["after_user_work"])
        self.assertIn("continuation_after_user_turn", w.event_codes(key))
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual((child["state"], child["last_error"]), ("superseded", "parent_handed_over"))
        for _ in range(10):
            w.tick(300)
        self.assertEqual(w.sends(thread), 1)


class T22CancelRaceTests(Base):
    def test_T22_cancel_after_the_claim_but_before_the_send_releases_the_claim(self):
        """The UI read the record as waiting; by the time its Cancel lands the watcher
        has claimed it. The cancel is recorded as a request, and the last look before
        the queue process starts gives the claim back: nothing is sent."""
        w = self.world()
        w.enable()
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        seen_by_ui = w.get(key)["state"]
        self.assertEqual(seen_by_ui, "waiting_backoff")
        real = w.store.reserve_detailed
        effects = []

        def reserve_then_cancel(interruption_id, now, **options):
            result = real(interruption_id, now, **options)
            effects.append(w.store.cancel_interruption(interruption_id, now, actor="gui"))
            return result
        w.store.reserve_detailed = reserve_then_cancel
        w.tick(5)
        self.assertEqual(effects[0]["effects"][key], "cancel_requested")
        self.assertEqual(w.sends(thread), 0)
        row = w.get(key)
        self.assertEqual(row["state"], "cancelled")
        self.assertTrue(row["cancel_requested"])
        self.assertEqual(w.home.queued(thread), [])

    def test_T22_cancel_after_the_process_started_is_withdrawn_by_the_watch(self):
        """Once the queue process has started, Cancel can only mark the record
        (`cancel_requested=1`, not `cancelled`). The watch then takes the item back and
        the record settles as cancelled - with no queue row left behind untracked."""
        w = self.world()
        w.enable()
        w.backend.after_accept = "queue"
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        seen = {}

        def cancel_during_send(sent_thread, prompt):
            seen["state_before"] = w.get(key)["state"]
            seen["result"] = w.store.cancel_interruption(key, w.now, actor="toast")
            seen["state_after"] = w.get(key)["state"]
        w.backend.on_send = cancel_during_send
        w.tick(5)
        self.assertEqual(seen["state_before"], "submitting")
        self.assertEqual(seen["result"]["effects"][key], "cancel_requested")
        self.assertEqual(seen["state_after"], "submitting")
        row = w.get(key)
        self.assertEqual(row["state"], "queued")
        self.assertTrue(row["cancel_requested"])
        self.assertEqual(machine.overlays(row), ["cancel_pending"])
        w.tick(1)
        row = w.get(key)
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "cancel"))
        self.assertEqual(w.home.queued(thread), [])
        for _ in range(8):
            w.tick(30)
        row = w.get(key)
        self.assertEqual(row["state"], "cancelled")
        self.assertEqual(w.home.queued(thread), [])
        self.assertEqual(w.source.marker_presence(thread, row["marker"]), {"history": 0, "queue": 0})
        self.assertEqual(w.sends(thread), 1)


class T23CancelContentionTests(Base):
    @staticmethod
    def hold_write_lock(path, seconds):
        """Another connection holds BEGIN IMMEDIATE on our state for `seconds`."""
        ready = threading.Event()

        def run():
            connection = sqlite3.connect(path, isolation_level=None, timeout=1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                ready.set()
                time.sleep(seconds)
                connection.execute("COMMIT")
            finally:
                connection.close()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert ready.wait(5)
        return worker

    def pending(self, w):
        w.enable()
        thread = w.thread()
        w.fail(thread)
        w.tick()
        return thread, w.only(thread)["interruption_id"]

    def test_T23_cancel_waits_out_a_short_write_lock(self):
        w = self.world()
        thread, key = self.pending(w)
        worker = self.hold_write_lock(w.store.path, 2)
        started = time.monotonic()
        result = w.store.cancel_interruption(key, w.now, actor="gui")
        worker.join(10)
        self.assertGreaterEqual(time.monotonic() - started, 1.5)
        self.assertTrue(result["changed"])
        self.assertEqual(w.get(key)["state"], "cancelled")

    def test_T23_cancel_succeeds_by_retrying_under_a_12_second_write_lock(self):
        """Cancel must never fail because of contention (C15): Control retries on
        SQLITE_BUSY for up to 30 s, past the store's own 10 s busy timeout."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = Path(temp.name) / "runtime"
        w = World(self, state_dir=runtime / "config")
        thread, key = self.pending(w)
        worker = self.hold_write_lock(w.store.path, 12)
        try:
            result = Control(runtime).cancel_interruption(key)
        finally:
            worker.join(20)
        self.assertEqual(result["interruption_id"], key)
        self.assertEqual(w.get(key)["state"], "cancelled")


# =====================================================================================
# T24-T25: Pause (design 7.1)
# =====================================================================================
class T24PauseTests(Base):
    def test_T24_pause_while_queued_withdraws_and_releases_to_waiting(self):
        """Pause takes back a continuation Codex has not started. Once it is proven
        that nothing ran, the record is waiting again - unsent, but its claim still
        counts against the daily cap."""
        w = self.world(max_submissions_per_thread_per_day=1)
        w.enable()
        thread, key = w.queued()
        claimed = w.get(key)
        w.pause()
        w.tick(1)
        row = w.get(key)
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "paused"))
        self.assertTrue(row["withdraw_deleted"])
        self.assertEqual(w.home.queued(thread), [])
        for _ in range(5):
            w.tick(30)
            self.assertEqual(w.get(key)["state"], "withdrawn_unconfirmed")
        w.tick(60)
        row = w.get(key)
        self.assertIn(row["state"], machine.WAITING)
        self.assertIsNone(row["submitted_at"])
        self.assertIsNone(row["queue_id"])
        self.assertEqual(row["last_claim_at"], claimed["last_claim_at"])
        self.assertEqual(row["first_queued_at"], claimed["first_queued_at"])
        self.assertIn("release_withdrawn", w.event_codes(key))
        self.assertEqual(w.store.recent_claims(thread, w.now - DAY), [claimed["last_claim_at"]])
        w.enable()
        for _ in range(3):
            w.tick(60)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("waiting_retry", "daily_submission_cap"))
        self.assertEqual(w.sends(thread), 1)

    def test_T24_a_marker_that_appears_during_the_settle_starts_the_turn(self):
        """Codex can report the delete after it already started our item (U2). The
        marker then appears and the record follows that turn."""
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.backend.delete_result = True          # "deleted", but Codex had already taken it
        w.pause()
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "withdrawn_unconfirmed")
        turn = w.home.dispatch(thread, status="inProgress")
        w.tick(1)
        row = w.get(key)
        self.assertEqual(row["state"], "turn_started")
        self.assertEqual(row["recovery_turn_id"], turn)
        self.assertIn("dispatched_while_paused", w.event_codes(key))

    def test_T24_a_stale_projection_through_the_settle_ends_unknown(self):
        """With Codex's history behind its own file for the whole settle window, "no
        marker" proves nothing: the record ends as submission_unknown, never waiting."""
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.pause()
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "withdrawn_unconfirmed")
        w.home.make_stale(thread)
        for _ in range(20):
            w.tick(10)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "withdraw_unconfirmed"))
        self.assertIsNotNone(row["submitted_at"])

    def test_T24_a_later_turn_during_the_settle_prevents_the_release(self):
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.pause()
        w.tick(1)
        w.home.add_turn(thread, status="completed")
        for _ in range(8):
            w.tick(30)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "withdraw_unconfirmed"))

    def test_T24_a_row_that_vanished_without_our_delete_is_never_released(self):
        w = self.world()
        w.enable()
        thread, key = w.queued()

        def vanished_without_our_delete(sent_thread, queue_id):
            w.home.remove_queued(queue_id)
            return False
        w.backend.delete_queue = vanished_without_our_delete
        w.pause()
        w.tick(1)
        row = w.get(key)
        self.assertEqual(row["state"], "withdrawn_unconfirmed")
        self.assertFalse(row["withdraw_deleted"])
        for _ in range(8):
            w.tick(30)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "withdraw_unconfirmed"))


class T25PausedWatchTests(Base):
    def settle_while_paused(self, w, key):
        w.pause()
        for _ in range(8):
            w.tick(30)
        return w.get(key)

    def test_T25_a_not_loaded_withdrawal_still_settles_while_paused(self):
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.backend.loaded_map[thread] = "notLoaded"
        w.tick(6)
        row = w.get(key)
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "not_loaded"))
        row = self.settle_while_paused(w, key)
        self.assertEqual(row["state"], "failed")
        self.assertEqual(machine.public_code(row), "failed_terminal")
        self.assertEqual(w.home.queued(thread), [])

    def test_T25_an_expiry_withdrawal_still_settles_while_paused(self):
        w = self.world()
        w.enable()
        thread, key = w.queued()
        for _ in range(7):
            w.tick(30)
        row = w.get(key)
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "expired"))
        row = self.settle_while_paused(w, key)
        self.assertEqual(row["state"], "failed")

    def test_T25_cancel_is_honoured_while_paused(self):
        """A cancel is not turned into a Pause release: it ends cancelled."""
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.pause()
        w.store.cancel_interruption(key, w.now, actor="gui")
        w.tick(1)
        row = w.get(key)
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "cancel"))
        for _ in range(8):
            w.tick(30)
        self.assertEqual(w.get(key)["state"], "cancelled")
        self.assertEqual(w.home.queued(thread), [])

    def test_T25_an_unknown_record_that_owns_a_row_is_still_withdrawn_while_paused(self):
        """The watch runs paused or not, including for a submission_unknown record
        whose queue row is still there after failed deletes."""
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.backend.delete_result = False
        w.pause()
        # A failed delete is retried only every delete_retry_seconds (each one starts a
        # Codex process); the record is still looked at on every pass.
        for _ in range(6):
            w.tick(10)
            if w.get(key)["state"] == "submission_unknown":
                break
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "queue_cleanup_unconfirmed"))
        self.assertIsNotNone(row["queue_id"])
        w.backend.delete_result = None
        deletes = len(w.backend.deleted)
        w.tick(61)
        self.assertGreater(len(w.backend.deleted), deletes)
        self.assertEqual(w.home.queued(thread), [])
        self.assertEqual(w.get(key)["state"], "withdrawn_unconfirmed")


# =====================================================================================
# T27-T28: classifier and usage expiry (design 7.8, 7.9)
# =====================================================================================
class T27RateLimitTests(Base):
    def test_T27_too_many_attempts_with_429_is_a_rate_limit_with_a_minute_first_wait(self):
        for ladder in (None, (3, 8, 20, 45, 90)):
            with self.subTest(ladder=ladder):
                w = self.world(**({"retry_ladder": ladder} if ladder else {}))
                w.enable()
                thread = w.thread()
                w.fail(thread, too_many_attempts(429))
                w.tick()
                row = w.only(thread)
                self.assertEqual(row["category"], "rate_limit_transient")
                self.assertEqual(row["state"], "waiting_backoff")
                self.assertGreaterEqual(row["next_retry_at"] - row["detected_at"], 60)
                w.tick(59)
                self.assertEqual(w.sends(thread), 0)
                w.now = row["next_retry_at"]
                w.tick()
                self.assertEqual(w.sends(thread), 1)

    def test_T27_the_same_tag_with_any_other_status_is_never_registered(self):
        for status in (None, 500, 503):
            with self.subTest(status=status):
                w = self.world()
                w.enable()
                thread = w.thread()
                w.fail(thread, too_many_attempts(status))
                for _ in range(3):
                    w.tick(60)
                self.assertEqual(w.records(thread), [])
                self.assertEqual(w.sends(thread), 0)

    def test_T27_the_429_case_is_switched_off_with_the_rate_limit_category(self):
        w = self.world(recoverable_categories=frozenset({"usage_limit", "server_5xx"}))
        w.enable()
        thread = w.thread()
        w.fail(thread, too_many_attempts(429))
        w.tick()
        self.assertEqual(w.records(thread), [])


class T28UsageExpiryTests(Base):
    UNAVAILABLE = {"available": False, "reset_at": None, "limit_type": "x", "reason": "x"}

    def test_T28_a_weekly_reset_never_expires_before_reset_plus_a_day(self):
        w = self.world()
        w.enable()
        thread = w.thread()
        reset = w.now + 7 * DAY
        w.home.fail_usage(thread, completed=int(w.now), reset=reset)
        w.tick()
        key = w.only(thread)["interruption_id"]
        self.assertEqual(w.get(key)["reset_at"], reset)
        w.backend.usage_result = dict(self.UNAVAILABLE)
        while w.now < reset + DAY - 900:
            w.tick(3600 if w.now < reset else 900)
            self.assertNotIn(w.get(key)["state"], machine.TERMINAL, w.now - reset)
        self.assertEqual(w.get(key)["usage_unavailable_seconds"], 0)
        for _ in range(3):
            w.tick(900)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]),
                         ("terminal_failure", "usage_not_restored_after_reset"))
        self.assertGreaterEqual(w.now, reset + DAY)

    def test_T28_a_probe_reset_a_week_out_is_not_never_available(self):
        """Seven days of "unavailable" with a known reset is a weekly window, not a
        limit that never lifts."""
        w = self.world()
        w.enable()
        thread = w.thread()
        w.home.fail_usage(thread, completed=int(w.now), reset=None)
        w.tick()
        key = w.only(thread)["interruption_id"]
        reset = w.now + 7 * DAY
        w.backend.usage_result = {**self.UNAVAILABLE, "reset_at": reset}
        while w.now < reset + DAY - 900:
            w.tick(900)
            self.assertNotIn(w.get(key)["state"], machine.TERMINAL, w.now - reset)
        for _ in range(3):
            w.tick(900)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]),
                         ("terminal_failure", "usage_not_restored_after_reset"))

    def test_T28_app_closed_and_unknown_probe_time_is_not_accumulated(self):
        w = self.world()
        w.enable()
        thread = w.thread()
        w.home.fail_usage(thread, completed=int(w.now), reset=None)
        w.tick()
        key = w.only(thread)["interruption_id"]
        w.backend.usage_result = dict(self.UNAVAILABLE)
        w.tick(900)
        w.tick(900)
        self.assertEqual(w.get(key)["usage_unavailable_seconds"], 900)
        # The desktop app is closed for three days.
        app, w.backend.app = w.backend.app, None
        for _ in range(3 * 24):
            w.tick(3600)
        w.backend.app = app
        w.tick(900)
        self.assertEqual(w.get(key)["usage_unavailable_seconds"], 900)
        # The probe itself cannot tell for a day.
        w.backend.usage_result = {"available": None, "reset_at": None, "limit_type": None, "reason": "error"}
        for _ in range(24):
            w.tick(3600)
        w.backend.usage_result = dict(self.UNAVAILABLE)
        w.tick(900)
        self.assertEqual(w.get(key)["usage_unavailable_seconds"], 900)
        w.tick(900)
        self.assertEqual(w.get(key)["usage_unavailable_seconds"], 1800)

    def test_T28_seven_days_unavailable_with_no_reset_is_a_terminal_failure(self):
        w = self.world()
        w.enable()
        thread = w.thread()
        w.home.fail_usage(thread, completed=int(w.now), reset=None)
        w.tick()
        key = w.only(thread)["interruption_id"]
        w.backend.usage_result = dict(self.UNAVAILABLE)
        for _ in range(8 * 96):
            w.tick(900)
            row = w.get(key)
            if row["state"] == "terminal_failure":
                break
            self.assertLess(row["usage_unavailable_seconds"], 7 * DAY)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "usage_never_available"))
        self.assertGreaterEqual(row["usage_unavailable_seconds"], 7 * DAY)
        self.assertEqual(machine.public_code(row), "failed_terminal")
        self.assertEqual(w.sends(thread), 0)


# =====================================================================================
# T29-T30: public codes and overlays (design 3.3)
# =====================================================================================
def expected_code(state, last_error, queue_id):
    """The design's section 3.3 table, written out independently of machine.py."""
    if state in ("waiting_reset", "waiting_poll"):
        return "waiting_reset"
    if state == "waiting_for_usage":
        return "waiting_usage"
    if state in ("waiting_for_app", "waiting_for_loaded_thread"):
        return "waiting_thread"
    if state == "waiting_retry":
        return "failed_retryable" if last_error == "queue_process_not_started" else "scheduled"
    if state == "waiting_backoff":
        return "scheduled"
    if state == "submitting":
        return ("submitted" if last_error == "awaiting_delivery_receipt" or queue_id
                else "submission_claimed")
    return {
        "queued": "submitted", "withdrawn_unconfirmed": "withdrawing",
        "turn_started": "turn_running", "turn_completed": "turn_finishing",
        "recovered": "recovered", "completed_no_progress": "no_progress",
        "handed_over": "handed_over", "recovery_turn_failed": "recovery_failed",
        "stopped_by_user": "stopped_by_user", "outcome_unverified": "outcome_unverified",
        "resumed": "delivered_legacy", "cancelled": "cancelled",
        "superseded": "superseded", "superseded_by_user": "superseded",
        "retry_budget_exhausted": "exhausted", "no_progress_exhausted": "exhausted",
        "failed": "failed_terminal", "terminal_failure": "failed_terminal",
        "submission_unknown": "submission_unknown",
    }[state]


ERRORS = (None, "queue_process_not_started", "awaiting_delivery_receipt", "queue_launch_retry_limit",
          "user_joined", "other_recovery_in_flight")


class T29T30PublicCodeTests(Base):
    def records(self):
        for state in sorted(machine.STATES):
            for last_error in ERRORS:
                for queue_id in (None, new_id()):
                    for cancel in (False, True):
                        for legacy in (False, True):
                            yield {"state": state, "last_error": last_error, "queue_id": queue_id,
                                   "cancel_requested": cancel, "legacy": legacy,
                                   "withdraw_reason": None, "next_retry_at": BASE, "reset_at": None}

    def test_T29_there_are_twenty_seven_stored_states(self):
        self.assertEqual(len(machine.STATES), 27)

    def test_T29_T30_every_stored_record_maps_as_the_design_table_says(self):
        for record in self.records():
            with self.subTest(**{k: record[k] for k in ("state", "last_error", "cancel_requested")}):
                code = machine.public_code(record)
                self.assertIn(code, machine.PUBLIC_CODES)
                self.assertEqual(code, expected_code(record["state"], record["last_error"], record["queue_id"]))

    def test_T29_every_stored_failed_is_failed_terminal(self):
        for record in self.records():
            if record["state"] in ("failed", "terminal_failure"):
                self.assertEqual(machine.public_code(record), "failed_terminal")

    def test_T29_eligible_at_is_the_later_of_schedule_and_reset_for_waiting_codes(self):
        for state in machine.WAITING:
            record = {"state": state, "next_retry_at": BASE + 10, "reset_at": BASE + 99}
            self.assertEqual(machine.eligible_at(record), BASE + 99)
            record["reset_at"] = None
            self.assertEqual(machine.eligible_at(record), BASE + 10)

    def test_T29_the_mapping_module_imports_no_settings(self):
        tree = ast.parse(Path(machine.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(alias.name for alias in node.names)
        for forbidden in ("settings", "config", "store", "engine", "source"):
            self.assertFalse(any(forbidden in name.split(".") for name in imported), imported)

    def test_T29_the_code_does_not_change_with_the_attempt_budget(self):
        """The engine that produced a record can be re-configured; the record's code
        cannot follow the setting."""
        w = self.world(max_queue_retries=2)
        w.enable()
        w.backend.default_outcome = "not_started"
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        w.tick(5)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("waiting_retry", "queue_process_not_started"))
        self.assertEqual(machine.public_code(row), "failed_retryable")
        self.assertEqual(machine.eligible_at(row), row["next_retry_at"])
        w.tick_until_sent(thread, step=30)
        row = w.get(key)
        self.assertEqual(row["state"], "failed")
        before = machine.describe(row)
        w.engine.options["max_recovery_attempts"] = 99
        w.engine.options["max_queue_retries"] = 99
        self.assertEqual(machine.describe(w.get(key)), before)
        self.assertEqual(before["code"], "failed_terminal")

    def test_T30_overlays_never_apply_to_a_record_that_may_have_been_sent(self):
        watcher = {"engine_state": "incompatible", "running": False}
        for record in self.records():
            state = record["state"]
            found = machine.overlays(record, enabled=False, thread_enabled=False, watcher=watcher)
            pending = bool(record["cancel_requested"]) and state not in machine.TERMINAL
            self.assertEqual("cancel_pending" in found, pending, record)
            if state in machine.WAITING:
                self.assertIn("paused", found)
                self.assertIn("thread_disabled", found)
            else:
                self.assertEqual([name for name in found if name != "cancel_pending"], [], state)

    def test_T30_a_claimed_record_with_a_receipt_or_queue_id_reads_as_submitted(self):
        self.assertEqual(machine.public_code({"state": "submitting", "last_error": "awaiting_delivery_receipt"}),
                         "submitted")
        self.assertEqual(machine.public_code({"state": "submitting", "queue_id": new_id()}), "submitted")
        self.assertEqual(machine.public_code({"state": "submitting"}), "submission_claimed")


# =====================================================================================
# T31-T32: gates and projection freshness (design 6)
# =====================================================================================
class T31GateEvalTests(Base):
    def test_T31_the_gate_vector_is_written_on_a_granted_claim(self):
        w = self.world()
        w.enable()
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        self.assertTrue(w.tick_until_sent(thread))
        row = w.get(key)
        gates = machine.decode_gates(row["gate_eval"])
        self.assertEqual({name: result for name, (result, _) in gates.items()},
                         {name: machine.PASS for name in machine.GATES})
        self.assertEqual(row["gate_eval_at"], row["last_claim_at"])

    def test_T31_a_refused_claim_writes_consent_block_and_makes_no_transition(self):
        """The thread is disabled between the engine's checks and the claim: the claim
        is refused inside its own transaction, the vector says why, and nothing moves."""
        w = self.world()
        w.enable()
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        before = w.get(key)
        real = w.store.reserve_detailed

        def disable_then_reserve(interruption_id, now, **options):
            w.store.set_thread_enabled(thread, False)
            return real(interruption_id, now, **options)
        w.store.reserve_detailed = disable_then_reserve
        w.tick(5)
        row = w.get(key)
        self.assertEqual(w.sends(thread), 0)
        self.assertEqual((row["state"], row["last_error"]), (before["state"], before["last_error"]))
        self.assertIsNone(row["submitted_at"])
        gates = machine.decode_gates(row["gate_eval"])
        self.assertEqual(gates["consent"], (machine.BLOCK, "thread_disabled"))
        self.assertEqual(row["gate_eval_at"], w.now)

    def test_T31_a_due_record_on_a_disabled_thread_records_consent_block(self):
        """The UI reads gate_eval and never recomputes it, so a due record the engine
        declines because its thread is disabled says so there too."""
        w = self.world()
        w.enable()
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        before = w.get(key)
        w.store.set_thread_enabled(thread, False)
        w.tick(5)
        row = w.get(key)
        self.assertEqual(w.sends(thread), 0)
        self.assertEqual(row["state"], before["state"])
        self.assertEqual(machine.decode_gates(row["gate_eval"])["consent"], (machine.BLOCK, "thread_disabled"))

    def test_T31_a_future_stored_reset_is_a_wait_with_a_reason(self):
        """Retry Now brings the schedule forward but never the usage reset: the record
        is parked as waiting_reset with the reason, not refused every poll in silence."""
        w = self.world()
        w.enable()
        thread = w.thread()
        w.home.fail_usage(thread, completed=int(w.now))
        w.tick()
        key = w.only(thread)["interruption_id"]
        reset = w.get(key)["reset_at"]
        self.assertGreater(reset, w.now)
        accepted, eligible = w.store.request_retry_now(key, w.now, actor="gui")
        self.assertTrue(accepted)
        self.assertEqual(eligible, reset)
        w.tick(1)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("waiting_reset", "waiting_reset"))
        self.assertGreaterEqual(row["next_retry_at"], reset)
        self.assertEqual(row["reset_at"], reset)
        self.assertEqual(machine.decode_gates(row["gate_eval"])["schedule"], (machine.WAIT, "waiting_reset"))
        self.assertEqual(w.sends(thread), 0)


class T32ProjectionTests(Base):
    def due_record(self, w, loaded=True, **_):
        w.enable()
        thread = w.thread(loaded=loaded)
        w.fail(thread)
        w.tick()
        return thread, w.only(thread)["interruption_id"]

    def test_T32_a_projection_seen_stale_for_over_two_minutes_blocks_the_send(self):
        w = self.world()
        thread, key = self.due_record(w, loaded=False)
        w.home.make_stale(thread)
        w.tick(5)                   # first seen stale
        w.tick(60)
        w.tick(61)                  # stale for more than 120 s
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("waiting_for_loaded_thread", "projection_stale"))
        self.assertEqual(machine.public_code(row), "waiting_thread")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["identity"], (machine.UNKNOWN, "projection_stale"))
        w.backend.loaded_map[thread] = "loaded"
        for _ in range(3):
            w.tick(60)
        self.assertEqual(w.sends(thread), 0)

    def test_T32_a_projection_stale_since_long_before_the_record_was_due_blocks_the_send(self):
        """"Stays larger for more than 120 s" is a fact about Codex's file, not about
        when the engine first looked: a projection frozen for minutes before the record
        falls due must not be trusted at the moment it does."""
        w = self.world(retry_ladder=(300, 300, 300, 300, 300))
        thread, key = self.due_record(w)
        w.home.make_stale(thread)
        for _ in range(9):
            w.tick(30)
            self.assertEqual(w.sends(thread), 0)
        w.now = w.get(key)["next_retry_at"]
        w.tick()
        self.assertEqual(w.sends(thread), 0)

    def test_T32_an_owned_row_is_withdrawn_and_ends_unknown(self):
        w = self.world()
        w.enable()
        thread, key = w.queued()
        w.home.make_stale(thread)
        for _ in range(30):
            w.tick(5)
            if w.get(key)["state"] != "queued":
                break
        row = w.get(key)
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "projection_stale"))
        self.assertEqual(w.home.queued(thread), [])
        for _ in range(8):
            w.tick(30)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "withdraw_unconfirmed"))
        for _ in range(4):
            w.tick(900)
        self.assertEqual(w.get(key)["state"], "submission_unknown")
        self.assertEqual(w.sends(thread), 1)

    def test_T32_a_gap_under_two_minutes_passes(self):
        w = self.world()
        thread, key = self.due_record(w, loaded=False)
        w.home.make_stale(thread)
        w.tick(5)                   # first seen stale, thread not loaded
        self.assertEqual(w.get(key)["last_error"], "notLoaded")
        w.backend.loaded_map[thread] = "loaded"
        w.tick(60)                  # stale for 60 s
        self.assertEqual(w.sends(thread), 1)

    def test_T32_a_missing_projection_table_blocks_as_incompatible(self):
        w = self.world()
        thread, key = self.due_record(w)
        w.drop_projection_table()
        w.tick(5)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), ("waiting_for_app", "projection_table_missing"))
        self.assertEqual(machine.decode_gates(row["gate_eval"])["engine_compatible"],
                         (machine.BLOCK, "projection_table_missing"))
        self.assertEqual(w.sends(thread), 0)


# =====================================================================================
# T48: what the user is told (design 7.5)
# =====================================================================================
class T48NotificationTests(Base):
    def test_T48_a_child_registered_exhausted_is_announced_as_stopped_only(self):
        w = self.world(thread_cooldown_seconds=0, max_submissions_per_thread_per_day=1000,
                       max_no_progress=1)
        w.enable()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=False)
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual(child["state"], "no_progress_exhausted")
        self.assertEqual(w.notes_for(child["interruption_id"]), [("stopped", "no_progress_exhausted")])

    def test_T48_children_registered_cancelled_or_superseded_are_announced_as_stopped_only(self):
        w = self.world()
        w.enable()
        thread, key, turn = w.started()
        w.store.cancel_interruption(key, w.now, actor="gui")
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual(child["state"], "cancelled")
        self.assertEqual(w.notes_for(child["interruption_id"]), [("stopped", "cancelled")])

        w = self.world()
        w.enable()
        thread, key, turn = w.started(steer_user=True)
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual(child["state"], "superseded")
        self.assertEqual(w.notes_for(child["interruption_id"]), [("stopped", "superseded")])

    def test_T48_a_late_delivery_after_an_unknown_result_is_announced(self):
        w = self.world()
        w.enable()
        thread = w.thread()
        w.backend.default_outcome = "unknown"
        # The queue process timed out, but Codex did take the item.
        w.backend.on_send = lambda sent_thread, prompt: w.home.enqueue(sent_thread, prompt, client_id=new_id())
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        self.assertTrue(w.tick_until_sent(thread))
        self.assertEqual(w.get(key)["state"], "submission_unknown")
        self.assertIn(("result", "submission_unknown"), w.notes_for(key))
        w.home.dispatch(thread, status="inProgress")
        w.tick(1)
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "turn_started")
        self.assertIn(("result", "turn_started"), w.notes_for(key))

    def test_T48_nothing_is_announced_between_the_claim_and_the_send(self):
        w = self.world()
        w.enable()
        thread = w.thread()
        w.fail(thread)
        w.tick()
        key = w.only(thread)["interruption_id"]
        seen = {}
        w.backend.on_send = lambda *_: seen.setdefault("at_send", list(w.notes))
        before = list(w.notes)
        w.tick(5)
        self.assertEqual(w.sends(thread), 1)
        self.assertEqual(seen["at_send"], before)
        self.assertIn(("starting", None), w.notes_for(key))


if __name__ == "__main__":
    unittest.main()
