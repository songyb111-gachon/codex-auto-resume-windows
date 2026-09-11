"""General transient recovery: separate policy, bounded budgets, and stopping rules.

Usage-limit recovery has its own policy and its own tests; nothing here may change it.

Everything runs against a real Codex home through the real LocalSource (see
test_engine). The budgets are bounded per *task*, not per record: a failure of a turn
our own continuation started is the same task failing again, so the record created for
it inherits its parent's counters in the very transaction that creates it
(engine-design-v2 §4.4). The v0.5 no-progress carry survives only for a predecessor
recorded before chains existed - a migrated, delivered (`resumed`) row.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # test_engine and codexsim live next to this file

from codexsim import CodexHome, new_id, transient_error  # noqa: E402
from codex_auto_resume import failures, machine, settings  # noqa: E402
from codex_auto_resume.engine import TRANSIENT_BACKOFF, transient_delay  # noqa: E402
from codex_auto_resume.source import detect, valid_uuid  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_engine import (BASE, RESET, T1, T2, TURN_A, TURN_B, TURN_C, Harness,  # noqa: E402
                         dispatch_and_fail, fail_turn)


def rate_limit_gave_up(status):
    """Codex retried a request itself and gave up; `status` is the last HTTP status."""
    return json.dumps({"codexErrorInfo": {"responseTooManyFailedAttempts": {"httpStatusCode": status}}})


class Base(unittest.TestCase):
    def harness(self, **options):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        harness = Harness(Path(temp.name), options=options or None)
        self.addCleanup(harness.store.close)
        harness.backend.loaded_map[T1] = "loaded"
        harness.backend.loaded_map[T2] = "loaded"
        return harness


class PolicySeparationTests(Base):
    def test_a_transient_failure_waits_on_backoff_not_on_a_reset(self):
        harness = self.harness()
        harness.home.fail_transient(T1)
        harness.enable()
        harness.tick()
        row = harness.record(T1)
        self.assertEqual(row["category"], "server_5xx")
        self.assertEqual(row["state"], "waiting_backoff")
        self.assertIsNone(row["reset_at"])
        self.assertAlmostEqual(row["next_retry_at"], harness.now + TRANSIENT_BACKOFF[0], delta=1)

    def test_a_usage_limit_still_waits_for_its_reset(self):
        harness = self.harness()
        harness.home.fail_usage(T1)
        harness.enable()
        harness.tick()
        row = harness.record(T1)
        self.assertEqual(row["category"], failures.USAGE_LIMIT)
        self.assertEqual(row["state"], "waiting_reset")
        self.assertEqual(row["reset_at"], RESET)

    def test_the_backoff_ladder_is_bounded(self):
        self.assertEqual([transient_delay(n) for n in range(1, 6)], list(TRANSIENT_BACKOFF))
        # Beyond the ladder it stays at the cap instead of growing without limit.
        self.assertEqual(transient_delay(50), TRANSIENT_BACKOFF[-1])
        self.assertEqual(transient_delay(0), TRANSIENT_BACKOFF[0])

    def test_threads_recover_independently(self):
        harness = self.harness()
        harness.home.fail_transient(T1)
        harness.home.fail_usage(T2, turn_id=TURN_B)
        harness.enable()
        harness.tick()
        self.assertEqual(harness.record(T1)["state"], "waiting_backoff")
        self.assertEqual(harness.record(T2)["state"], "waiting_reset")
        self.assertNotEqual(harness.record(T1)["interruption_id"], harness.record(T2)["interruption_id"])

    def test_T27_a_rate_limit_codex_gave_up_on_waits_at_least_a_minute(self):
        """§7.9: the one widening. Codex already retried, so the first wait is never
        shorter than a minute, whatever the timing preset says."""
        harness = self.harness()
        harness.home.fail_transient(T1, error_json=rate_limit_gave_up(429))
        harness.enable()
        harness.tick()
        row = harness.record(T1)
        self.assertEqual(row["category"], "rate_limit_transient")
        self.assertEqual(row["state"], "waiting_backoff")
        self.assertGreaterEqual(row["next_retry_at"] - harness.now, max(60, TRANSIENT_BACKOFF[0]))

    def test_T27_the_same_tag_with_any_other_status_is_never_recovered(self):
        harness = self.harness()
        harness.enable()
        for status in (None, 500, 503):
            with self.subTest(status=status):
                harness.home.fail_transient(new_id(), error_json=rate_limit_gave_up(status))
                harness.tick(advance=60)
        self.assertEqual(harness.store.all_records(), [])
        self.assertEqual(harness.backend.send_calls, [])

    def test_T27_it_is_switched_off_with_the_rate_limit_category(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_rate_limit_transient=False))
        harness.home.fail_transient(T1, error_json=rate_limit_gave_up(429))
        harness.enable()
        harness.tick()
        self.assertIsNone(harness.record(T1))
        self.assertIn("category_recovery_disabled", harness.codes(T1))


class BudgetTests(Base):
    def exhaust(self, harness, limit):
        """Drive repeated reservations by making every launch fail provably."""
        harness.backend.default_outcome = "not_started"
        for _ in range(limit + 3):
            harness.tick(advance=3600)
            if harness.record(T1)["state"] in ("retry_budget_exhausted", "failed"):
                break
        return harness.record(T1)

    def test_a_transient_chain_stops_at_the_recovery_budget(self):
        harness = self.harness(max_recovery_attempts=2, max_queue_retries=99)
        harness.home.fail_transient(T1)
        harness.enable()
        harness.tick()
        row = self.exhaust(harness, 2)
        self.assertEqual(row["state"], "retry_budget_exhausted")
        self.assertEqual(row["last_error"], "recovery_budget")
        self.assertLessEqual(row["recovery_attempts"], 2)
        self.assertEqual(len(harness.backend.send_calls), 2)

    def test_the_budget_does_not_apply_to_a_usage_limit(self):
        # A usage limit keeps the policy it already had: the daily cap and the
        # per-thread cooldown bound it, not an attempt ladder.
        harness = self.harness(max_recovery_attempts=1, max_queue_retries=3)
        harness.home.fail_usage(T1)
        harness.enable()
        harness.tick()
        row = self.exhaust(harness, 1)
        self.assertNotEqual(row["state"], "retry_budget_exhausted")
        self.assertEqual(row["recovery_attempts"], 0)

    def test_attempts_persist_across_a_restart(self):
        harness = self.harness(max_recovery_attempts=3)
        harness.home.fail_transient(T1)
        harness.enable()
        harness.tick()
        harness.backend.default_outcome = "not_started"
        harness.tick(advance=3600)
        row = harness.record(T1)
        self.assertGreaterEqual(row["recovery_attempts"], 1)
        reopened = Store(harness.root)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get(row["interruption_id"])["recovery_attempts"], row["recovery_attempts"])


class ChainBase(Base):
    """A task whose continuation Codex runs, and which then fails again."""

    def start(self, harness, *, usage=False):
        harness.backend.after_accept = "queue"
        if usage:
            harness.home.fail_usage(T1, TURN_A, reset=None)
        else:
            harness.home.fail_transient(T1, TURN_A)
        harness.enable()
        harness.tick()
        return harness.record(T1)

    def continuation_fails(self, harness, *, progress=False, usage=False):
        """Wait for the next continuation to be sent; Codex runs it, and it fails.

        Returns the record created for that failure.
        """
        sent = len(harness.backend.send_calls)
        for _ in range(6):
            harness.tick(advance=1000)
            if len(harness.backend.send_calls) > sent:
                break
        self.assertEqual(len(harness.backend.send_calls), sent + 1, "a continuation was sent")
        dispatch_and_fail(harness.home, T1, progress=progress, usage=usage)
        harness.tick(advance=1)
        return harness.records(T1)[-1]

    def run_chain(self, harness, *, usage=False, rounds=12):
        """Every continuation fails at once, having produced nothing."""
        for _ in range(rounds):
            if harness.records(T1)[-1]["state"] in machine.TERMINAL:
                break
            self.continuation_fails(harness, usage=usage)
        return harness.records(T1)

    def assert_one_chain(self, rows):
        origin = rows[0]["interruption_id"]
        for parent, child in zip(rows, rows[1:]):
            self.assertEqual(child["parent_interruption_id"], parent["interruption_id"])
            self.assertEqual(child["chain_origin_id"], origin)


class NoProgressTests(ChainBase):
    def test_no_progress_since_the_last_recovery_increments_the_count(self):
        harness = self.harness()
        first = self.start(harness)
        row = self.continuation_fails(harness)
        self.assertEqual(row["parent_interruption_id"], first["interruption_id"])
        self.assertEqual(row["no_progress_count"], 1)
        self.assertEqual(row["state"], "waiting_backoff")

    def test_visible_progress_adds_nothing_to_the_count(self):
        """§4.4: the child keeps its parent's count, plus one only when the failed
        recovery turn produced nothing."""
        harness = self.harness()
        self.start(harness)
        empty = self.continuation_fails(harness, progress=False)
        self.assertEqual(empty["no_progress_count"], 1)
        worked = self.continuation_fails(harness, progress=True)
        self.assertEqual(worked["parent_interruption_id"], empty["interruption_id"])
        self.assertEqual(worked["no_progress_count"], 1)
        self.assertNotIn(worked["state"], machine.TERMINAL)

    def test_an_exhausted_chain_stops_instead_of_recovering_again(self):
        harness = self.harness(max_no_progress=2)
        self.start(harness)
        self.continuation_fails(harness)
        row = self.continuation_fails(harness)
        self.assertEqual(row["state"], "no_progress_exhausted")
        self.assertEqual(row["no_progress_count"], 2)
        self.assertIsNone(row["last_claim_at"])
        for _ in range(3):
            harness.tick(advance=3600)
        self.assertEqual(len(harness.backend.send_calls), 2)
        # Announced as stopped, never as a new interruption that "will resume".
        announced = [(event, detail["interruption_id"]) for event, detail in harness.notifications]
        self.assertIn(("stopped", row["interruption_id"]), announced)
        self.assertNotIn(("interruption", row["interruption_id"]), announced)

    def test_progress_is_decided_without_reading_any_content(self):
        harness = self.harness()
        recorded = []
        for name in ("turn_progress", "turn_observation", "progress"):
            original = getattr(harness.source, name)
            setattr(harness.source, name,
                    lambda *args, _original=original, _name=name: recorded.append((_name, args))
                    or _original(*args))
        self.start(harness)
        self.continuation_fails(harness)
        self.assertIn("turn_progress", {name for name, _args in recorded})
        for name, args in recorded:
            # Ids, ordinals and our own marker - never a message body.
            for value in args:
                self.assertTrue(valid_uuid(value) or type(value) is int
                                or (isinstance(value, str) and value.startswith("[codex-auto-resume:")),
                                (name, value))


class ChainTests(ChainBase):
    """T18 and T20: the budgets and the stops belong to the task, across its records."""

    def test_T18_a_transient_chain_stops_at_the_attempt_budget_across_records(self):
        harness = self.harness(max_no_progress=10)
        self.start(harness)
        rows = self.run_chain(harness)
        self.assert_one_chain(rows)
        self.assertEqual(len(harness.backend.send_calls), 4)
        self.assertEqual(rows[-1]["state"], "retry_budget_exhausted")
        self.assertEqual(rows[-1]["last_error"], "recovery_budget")
        self.assertEqual([row["recovery_attempts"] for row in rows], [1, 2, 3, 4, 4])
        # no_progress_count carries over each recovery_turn_id link.
        self.assertEqual([row["no_progress_count"] for row in rows], [0, 1, 2, 3, 4])

    def test_T18_a_transient_chain_stops_at_the_continuation_cap(self):
        harness = self.harness(max_no_progress=10, max_recovery_attempts=10, max_chain_continuations=3)
        self.start(harness)
        rows = self.run_chain(harness)
        self.assert_one_chain(rows)
        self.assertEqual(len(harness.backend.send_calls), 3)
        self.assertEqual(rows[-1]["state"], "retry_budget_exhausted")
        self.assertEqual(rows[-1]["last_error"], "chain_cap")
        self.assertEqual([row["chain_continuations"] for row in rows], [1, 2, 3, 3])

    def test_T18_a_usage_chain_stops_at_the_continuation_cap(self):
        harness = self.harness(max_no_progress=10, max_submissions_per_thread_per_day=10)
        self.start(harness, usage=True)
        rows = self.run_chain(harness, usage=True)
        self.assert_one_chain(rows)
        self.assertEqual(len(harness.backend.send_calls), 6)
        self.assertEqual(rows[-1]["state"], "retry_budget_exhausted")
        self.assertEqual(rows[-1]["last_error"], "chain_cap")
        self.assertEqual({row["recovery_attempts"] for row in rows}, {0})

    def test_T18_time_without_usage_accumulates_across_the_chain(self):
        harness = self.harness()
        first = self.start(harness, usage=True)
        harness.backend.usage_result = {"available": False, "reset_at": None, "limit_type": "unknown",
                                        "reason": "blocked"}
        for _ in range(3):
            harness.tick(advance=900)
        waited = harness.store.get(first["interruption_id"])["usage_unavailable_seconds"]
        self.assertEqual(waited, 1800)
        harness.backend.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows",
                                        "reason": "ok"}
        child = self.continuation_fails(harness, usage=True)
        self.assertEqual(child["parent_interruption_id"], first["interruption_id"])
        self.assertEqual(child["usage_unavailable_seconds"], waited)

    def test_T20_a_cancelled_parent_stops_its_child_before_its_own_outcome(self):
        harness = self.harness()
        parent = self.start(harness)
        harness.tick(advance=10)
        self.assertEqual(len(harness.backend.send_calls), 1)
        turn = harness.home.dispatch(T1, status="inProgress")
        harness.tick(advance=1)
        self.assertEqual(harness.record(T1)["state"], "turn_started")
        harness.store.cancel_interruption(parent["interruption_id"], harness.now)
        fail_turn(harness.home, T1, turn, code="internalServerError")
        harness.tick(advance=1)
        parent, child = harness.records(T1)
        self.assertEqual(child["parent_interruption_id"], parent["interruption_id"])
        self.assertEqual(child["state"], "cancelled")
        self.assertEqual(child["last_error"], "parent_cancelled")
        self.assertNotIn(parent["state"], machine.OUTCOMES, "decided before the parent's own outcome")
        harness.tick(advance=10)
        self.assertEqual(harness.store.get(parent["interruption_id"])["state"], "recovery_turn_failed")
        for _ in range(3):
            harness.tick(advance=3600)
        self.assertEqual(len(harness.backend.send_calls), 1)
        announced = [(event, detail["interruption_id"]) for event, detail in harness.notifications]
        self.assertIn(("stopped", child["interruption_id"]), announced)
        self.assertNotIn(("interruption", child["interruption_id"]), announced)

    def test_T20_a_continuation_that_ran_after_user_work_does_not_continue_its_chain(self):
        harness = self.harness()
        parent = self.start(harness)
        harness.tick(advance=10)
        # The user's turn ran first, and Codex dispatched our item the moment it ended.
        harness.home.add_turn(T1)
        turn = harness.home.dispatch(T1, status="inProgress")
        harness.tick(advance=1)
        parent = harness.store.get(parent["interruption_id"])
        self.assertTrue(parent["after_user_work"])
        self.assertIn("continuation_after_user_turn",
                      [event["code"] for event in harness.store.events(parent["interruption_id"])])
        fail_turn(harness.home, T1, turn)
        harness.tick(advance=1)
        child = harness.records(T1)[-1]
        self.assertEqual(child["parent_interruption_id"], parent["interruption_id"])
        self.assertEqual(child["state"], "superseded")
        self.assertEqual(child["last_error"], "parent_handed_over")
        self.assertEqual(len(harness.backend.send_calls), 1)


# A v0.5 state database: schema 2, exactly as those versions wrote it.
_V2_SCHEMA = (
    "CREATE TABLE settings (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
    "enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), armed_at REAL NOT NULL, "
    "poll_seconds INTEGER NOT NULL)",
    "CREATE TABLE threads (thread_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)))",
    "CREATE TABLE interruptions (interruption_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, "
    "turn_id TEXT NOT NULL, completed_at REAL NOT NULL, started_at REAL, ordinal INTEGER NOT NULL, "
    "detected_at REAL NOT NULL, reset_at REAL, limit_type TEXT, "
    "uncertain INTEGER NOT NULL CHECK (uncertain IN (0, 1)), state TEXT NOT NULL, "
    "retry_count INTEGER NOT NULL, next_retry_at REAL NOT NULL, resumed_at REAL, last_error TEXT, "
    "marker TEXT NOT NULL, queue_id TEXT, submitted_at REAL, attempt_count INTEGER NOT NULL, "
    "cancel_requested INTEGER NOT NULL CHECK (cancel_requested IN (0, 1)), "
    "category TEXT NOT NULL DEFAULT 'usage_limit', recovery_attempts INTEGER NOT NULL DEFAULT 0, "
    "no_progress_count INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX interruptions_thread ON interruptions(thread_id)",
)


def legacy_state(state_dir: Path, home: CodexHome, *, turn_id=TURN_A, no_progress_count=0) -> str:
    """Write a v0.5 state holding one delivered recovery of `turn_id`. Returns its id."""
    failed = next(turn for turn in home.turns(T1) if turn["turn_id"] == turn_id)
    key = detect(dict(failed))["interruption_id"]
    state_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_dir / "state.sqlite")
    try:
        for statement in _V2_SCHEMA:
            connection.execute(statement)
        connection.execute("INSERT INTO settings VALUES (1, 1, ?, 30)", (BASE,))
        connection.execute(
            "INSERT INTO interruptions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, T1, turn_id, failed["completed_at"], failed["started_at"], failed["rollout_ordinal"],
             BASE + 15, None, "server_5xx", 0, "resumed", 0, BASE + 15, BASE + 30, None,
             f"[codex-auto-resume:{key}]", None, BASE + 20, 1, 0, "server_5xx", 1, no_progress_count))
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    finally:
        connection.close()
    return key


class LegacyCarryTests(unittest.TestCase):
    """A predecessor delivered by v0.5 (`resumed`, migrated with legacy=1).

    Its recovery turn can be linked by marker (T38); until it is, the v0.5 carry rule
    applies to it exactly as before: no completed turn and no reply since it means the
    count carries forward, and visible progress starts the count over.
    """

    def migrated(self, *, no_progress_count=0, **options):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = CodexHome(Path(temp.name) / "codex-home")
        home.fail_transient(T1, TURN_A)
        key = legacy_state(Path(temp.name) / "state", home, no_progress_count=no_progress_count)
        harness = Harness(Path(temp.name) / "state", home=home, options=options or None, migrate=True)
        self.addCleanup(harness.close)
        harness.backend.loaded_map[T1] = "loaded"
        harness.now = BASE + 200
        legacy = harness.store.get(key)
        self.assertEqual(legacy["state"], "resumed")
        self.assertTrue(legacy["legacy"])
        self.assertEqual(machine.public_code(legacy), "delivered_legacy")
        return harness, key

    def later_failure(self, harness):
        harness.home.fail_transient(T1, TURN_B, ordinal=7, completed=BASE + 100)
        harness.tick()
        return next(row for row in harness.records(T1) if row["turn_id"] == TURN_B)

    def test_no_progress_since_a_legacy_recovery_increments_the_count(self):
        harness, key = self.migrated()
        row = self.later_failure(harness)
        self.assertEqual(row["no_progress_count"], 1)
        self.assertIsNone(row["parent_interruption_id"])
        self.assertEqual(row["chain_origin_id"], row["interruption_id"])
        # The legacy row is never evaluated and never blocks the new record - but its
        # claim still counts towards the per-thread cooldown, like every earlier claim.
        self.assertEqual(harness.store.get(key)["state"], "resumed")
        harness.tick(advance=10)
        self.assertEqual(harness.backend.send_calls, [])
        self.assertEqual(harness.store.get(row["interruption_id"])["last_error"], "thread_submission_cooldown")
        harness.tick(advance=900)
        self.assertEqual(len(harness.backend.send_calls), 1)
        self.assertEqual(harness.store.get(key)["state"], "resumed")

    def test_visible_progress_since_a_legacy_recovery_resets_the_count(self):
        harness, _key = self.migrated(no_progress_count=2)
        harness.home.add_turn(T1, TURN_C, "completed", ordinal=6, completed=BASE + 50)
        row = self.later_failure(harness)
        self.assertEqual(row["no_progress_count"], 0)

    def test_an_exhausted_legacy_count_stops_instead_of_recovering_again(self):
        harness, _key = self.migrated(no_progress_count=1, max_no_progress=2)
        row = self.later_failure(harness)
        self.assertEqual(row["state"], "no_progress_exhausted")
        self.assertEqual(row["no_progress_count"], 2)
        harness.tick(advance=3600)
        self.assertEqual(harness.backend.send_calls, [])

    def test_T38_a_failure_of_a_legacy_recovery_turn_links_to_its_parent(self):
        harness, key = self.migrated(no_progress_count=1)
        marker = harness.store.get(key)["marker"]
        # The turn v0.5's continuation started, failing in turn.
        harness.home.add_turn(T1, TURN_C, "failed", ordinal=6, completed=BASE + 100,
                              error_json=transient_error(), user_text="(continuation)\n\n" + marker,
                              progress=False)
        harness.tick()
        child = next(row for row in harness.records(T1) if row["turn_id"] == TURN_C)
        legacy = harness.store.get(key)
        self.assertEqual(child["parent_interruption_id"], key)
        self.assertEqual(child["chain_origin_id"], key)
        self.assertEqual(child["no_progress_count"], 2)
        self.assertEqual(child["recovery_attempts"], 1)
        self.assertEqual(legacy["recovery_turn_id"], TURN_C, "the parent's recovery turn is backfilled")
        self.assertEqual(legacy["state"], "resumed")
        self.assertEqual(machine.public_code(legacy), "delivered_legacy")
        statistics = harness.store.statistics()
        self.assertEqual(statistics["outcomes"]["delivered_legacy"], 1)
        self.assertEqual(statistics["success_denominator"], 0, "legacy rows are not outcomes")


class SupersedeTests(Base):
    def test_a_later_turn_by_the_user_stops_the_old_recovery(self):
        harness = self.harness()
        harness.home.fail_transient(T1, ordinal=5)
        harness.enable()
        harness.tick()
        self.assertEqual(harness.record(T1)["state"], "waiting_backoff")
        # The user carries on in that exact thread before the backoff elapses.
        harness.home.add_turn(T1, TURN_B, "completed", 6, completed=BASE + 5)
        harness.tick(advance=3600)
        self.assertEqual(harness.record(T1)["state"], "superseded_by_user")
        self.assertEqual(harness.backend.send_calls, [])

    def test_a_stale_interruption_is_never_retried_afterwards(self):
        harness = self.harness()
        harness.home.fail_transient(T1, ordinal=5)
        harness.enable()
        harness.tick()
        harness.home.add_turn(T1, TURN_B, "completed", 6, completed=BASE + 5)
        harness.tick(advance=3600)
        state = harness.record(T1)["state"]
        for _ in range(3):
            harness.tick(advance=3600)
        self.assertEqual(harness.record(T1)["state"], state)
        self.assertEqual(harness.backend.send_calls, [])


class UnknownNeverRetriedTests(Base):
    def test_an_unclassified_failure_is_never_registered(self):
        harness = self.harness()
        harness.home.add_turn(T1, TURN_A, "failed", 5, completed=BASE, progress=False,
                              error_json=json.dumps({"codexErrorInfo": "brandNewVariant"}))
        harness.enable()
        for _ in range(3):
            harness.tick(advance=3600)
        self.assertEqual(harness.store.all_records(), [])
        self.assertEqual(harness.backend.send_calls, [])

    def test_a_terminal_failure_is_never_registered(self):
        harness = self.harness()
        harness.enable()
        for code in ("unauthorized", "badRequest", "contextWindowExceeded", "cyberPolicy"):
            with self.subTest(code=code):
                thread_id = new_id()
                harness.home.add_turn(thread_id, None, "failed", progress=False,
                                      error_json=json.dumps({"codexErrorInfo": code}))
                harness.backend.loaded_map[thread_id] = "loaded"
                harness.tick(advance=60)
                self.assertEqual(harness.store.all_records(), [])
        self.assertEqual(harness.backend.send_calls, [])


if __name__ == "__main__":
    unittest.main()
