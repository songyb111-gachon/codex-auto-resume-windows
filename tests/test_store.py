"""Our own state database, schema 3.

Every test here goes through the real `Store` on a real SQLite file. Where a test
needs a record in a state that only a long engine run would produce, the fixture
writes that row directly with a second, plain SQLite connection and then asks the
store to read it back, so the row is one the store's own validator accepts. The
expectations are the design's (engine-design-v2, sections 2-9 and the section 10
table); a test that disagrees with the code is a question for the code.
"""
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid

from codex_auto_resume import machine
from codex_auto_resume import store as store_module
from codex_auto_resume.machine import (
    CLAIMED, EXHAUSTED, IN_FLIGHT, OBSERVING, OUTCOMES, PLAIN_MOVES, STATES, TERMINAL, WAITING,
)
from codex_auto_resume.store import StateFromNewerVersion, Store, StoreError, UpgradePending


THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
OTHER = "0a1b2c3d-0003-7000-8000-000000000003"
QUEUE = "0a1b2c3d-0005-7000-8000-000000000005"
REPO = Path(__file__).resolve().parents[1]
LIMITS = {"max_chain_continuations": 6, "max_recovery_attempts": 5, "max_no_progress": 3}
ALL_PASS = {name: (machine.PASS, "ok") for name in machine.GATES}
# Section 3.1: these states must name the exact turn our continuation started.
NEEDS_RECOVERY_TURN = OBSERVING | {"recovered", "completed_no_progress", "recovery_turn_failed",
                                   "stopped_by_user"}
SENT = CLAIMED | IN_FLIGHT | OBSERVING
# The columns section 2.1 adds. A migrated database must have every one of them.
V3_COLUMNS = {
    "recovery_turn_id", "recovery_client_id", "recovery_turn_status", "user_joined",
    "after_user_work", "legacy", "withdraw_reason", "withdrawn_at", "withdraw_deleted",
    "turn_started_at", "outcome_at", "first_queued_at", "last_claim_at", "parent_interruption_id",
    "chain_origin_id", "chain_first_detected_at", "chain_continuations", "budget_resets",
    "retry_now_count", "usage_unavailable_seconds", "gate_eval", "gate_eval_at", "history_hidden_at",
}
V2_COLUMNS = (
    "interruption_id", "thread_id", "turn_id", "completed_at", "started_at", "ordinal",
    "detected_at", "reset_at", "limit_type", "uncertain", "state", "retry_count",
    "next_retry_at", "resumed_at", "last_error", "marker", "queue_id", "submitted_at",
    "attempt_count", "cancel_requested", "category", "recovery_attempts", "no_progress_count",
)


def new_turn() -> str:
    return str(uuid.uuid4())


def failure(key="a" * 64, thread_id=THREAD, turn_id=TURN, category=None):
    event = {
        "thread_id": thread_id, "turn_id": turn_id, "completed_at": 110.0,
        "started_at": 105.0, "ordinal": 2, "interruption_id": key,
        "reset_at": 150.0, "limit_type": "codex.primary", "uncertain": True,
    }
    if category is not None:
        event["category"] = category
    return event


def raw(root) -> sqlite3.Connection:
    """A plain second connection: how the fixtures reach rows no single call makes."""
    connection = sqlite3.connect(Path(root) / "state.sqlite", isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def force(connection, key, **columns):
    assignments = ",".join("%s=?" % column for column in columns)
    connection.execute("UPDATE interruptions SET %s WHERE interruption_id=?" % assignments,
                       (*[int(value) if isinstance(value, bool) else value
                          for value in columns.values()], key))


def raw_row(connection, key) -> dict:
    return dict(connection.execute("SELECT * FROM interruptions WHERE interruption_id=?",
                                   (key,)).fetchone())


def event_count(connection, key=None) -> int:
    if key is None:
        return connection.execute("SELECT count(*) FROM events").fetchone()[0]
    return connection.execute("SELECT count(*) FROM events WHERE interruption_id=?",
                              (key,)).fetchone()[0]


_STATUS = {"turn_started": "inProgress", "turn_completed": "completed", "recovered": "completed",
           "completed_no_progress": "completed", "recovery_turn_failed": "failed",
           "stopped_by_user": "interrupted"}


def shape(state, recovery_turn) -> dict:
    """Column values that make a valid row in `state`, the way the engine leaves one."""
    columns = {"state": state}
    if state in SENT | OUTCOMES | {"submission_unknown", "resumed"}:
        columns.update(submitted_at=151.0, last_claim_at=151.0)
    if state in {"queued", "withdrawn_unconfirmed", "resumed"}:
        columns.update(queue_id=QUEUE, first_queued_at=152.0)
    if state == "withdrawn_unconfirmed":
        columns.update(withdraw_reason="cancel", withdrawn_at=160.0, withdraw_deleted=1,
                       last_error="cancel")
    if state in OBSERVING | OUTCOMES:
        columns.update(recovery_turn_id=recovery_turn, turn_started_at=155.0, resumed_at=155.0,
                       first_queued_at=152.0, recovery_turn_status=_STATUS.get(state))
    if state in OUTCOMES:
        columns["outcome_at"] = 170.0
    if state == "resumed":
        columns.update(legacy=1, resumed_at=160.0)
    if state == "submission_unknown":
        columns["last_error"] = "no_receipt_do_not_resend"
    if state in EXHAUSTED:
        columns["last_error"] = "recovery_budget"
    if state == "cancelled":
        columns.update(cancel_requested=1, last_error="user_cancelled")
    return columns


class _StoreCase(unittest.TestCase):
    """A fresh state directory, the store under test and a plain fixture connection."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "owned-state"
        self.store = Store(self.root)
        self.addCleanup(self.store.close)
        self.db = raw(self.root)
        self.addCleanup(self.db.close)
        self.count = 0
        self.rts = {}
        self.failures = {}

    def fast(self):
        """Durability is not what these tests measure; thousands of fsyncs would be."""
        for connection in (self.store._connection, self.db):
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA journal_mode=MEMORY")

    def make(self, state="waiting_reset", *, thread_id=THREAD, category=None, now=111.0, **columns):
        """A record in `state`, on its own Codex turn (one turn is one failure)."""
        self.count += 1
        key = "rec-%04d" % self.count
        event = failure(key, thread_id, new_turn(), category)
        self.assertTrue(self.store.register(event, now))
        self.failures[key] = event
        self.rts[key] = new_turn()
        values = shape(state, self.rts[key])
        values.update(columns)
        force(self.db, key, **values)
        self.store.get(key)          # the fixture is a row the validator accepts
        return key

    def row(self, key):
        return raw_row(self.db, key)


class StoreTests(_StoreCase):
    def test_initial_disabled_and_rearm_only_on_transition(self):
        self.assertEqual(self.store.settings(), {"enabled": False, "armed_at": 0, "poll_seconds": 30})
        self.store.set_enabled(True, 100)
        self.store.set_enabled(False, 120)
        self.store.set_enabled(True, 130)
        self.assertEqual(self.store.settings()["armed_at"], 130)
        self.store.set_enabled(True, 140)
        self.assertEqual(self.store.settings()["armed_at"], 130)
        self.assertTrue(self.store.thread_enabled(THREAD))

    def test_duplicate_and_restart_preserve_pending(self):
        event = failure()
        self.assertTrue(self.store.register(event, 111))
        self.assertFalse(self.store.register(event, 112))
        self.store.close()
        with Store(self.root) as reopened:
            self.assertEqual(len(reopened.pending()), 1)
            self.assertEqual(reopened.get(event["interruption_id"])["thread_id"], THREAD)
            self.assertFalse(reopened.register(event, 114))

    def test_same_key_with_different_identity_fails(self):
        self.store.register(failure(), 111)
        with self.assertRaises(StoreError):
            self.store.register(failure(thread_id=OTHER), 112)

    def test_same_turn_under_a_new_identity_is_refused_not_raised(self):
        """Section 4.4 step 1: one Codex turn is one failure. Seen again under a new id
        (its completion time moved), it is refused and journaled - never raised, because
        a raise inside collect would stop every other detection in the same pass."""
        self.assertTrue(self.store.register(failure(), 111))
        self.assertFalse(self.store.register(failure("b" * 64), 112))
        self.assertIsNone(self.store.get("b" * 64))
        self.assertEqual([event["code"] for event in self.store.events("a" * 64)],
                         ["detected", "identity_drift"])

    def test_global_disable_per_thread_disable_and_reset_gate(self):
        event = failure()
        key = event["interruption_id"]
        self.store.register(event, 111)
        self.assertFalse(self.store.reserve(key, 151))
        self.store.set_enabled(True, 100)
        self.assertFalse(self.store.reserve(key, 120))
        self.store.set_thread_enabled(THREAD, False)
        self.assertFalse(self.store.reserve(key, 151))
        self.store.set_thread_enabled(THREAD, True)
        self.assertTrue(self.store.reserve(key, 151))
        self.assertFalse(self.store.reserve(key, 152))
        self.assertEqual(self.store.get(key)["attempt_count"], 1)

    def test_reenable_preserves_known_pending(self):
        self.store.set_enabled(True, 100)
        self.store.register(failure(), 111)
        self.store.set_enabled(False, 120)
        self.store.set_enabled(True, 160)
        self.assertTrue(self.store.reserve("a" * 64, 200))

    def test_concurrent_connections_share_disable_and_reservation(self):
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        with Store(self.root) as second:
            second.set_enabled(False, 140)
            self.assertFalse(self.store.reserve("a" * 64, 151))
            second.set_enabled(True, 152)
            self.assertTrue(second.reserve("a" * 64, 153))
            self.assertFalse(self.store.reserve("a" * 64, 154))

    def test_reserved_interruption_survives_crash_as_submitting(self):
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.assertTrue(self.store.reserve("a" * 64, 151))
        self.store.close()
        with Store(self.root) as restarted:
            self.assertEqual(restarted.pending()[0]["state"], "submitting")
            self.assertFalse(restarted.reserve("a" * 64, 1000))

    def test_proven_no_launch_can_retry_with_backoff(self):
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.store.reserve(key, 151)
        self.store.update(key, state="waiting_retry", submitted_at=None, retry_count=1, next_retry_at=181)
        self.assertFalse(self.store.reserve(key, 180))
        self.assertTrue(self.store.reserve(key, 181))
        self.assertEqual(self.store.get(key)["attempt_count"], 2)

    def test_cannot_clear_already_queued_submission(self):
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.store.reserve(key, 151)
        self.store.update(key, state="queued", queue_id=OTHER)
        with self.assertRaises(StoreError):
            self.store.update(key, state="waiting_retry", submitted_at=None)

    def test_unknown_submission_can_resolve_but_never_retry(self):
        """A late receipt is information, not a retry: submission_unknown may still
        resolve (section 3.2), but never back to waiting, and its v2 exits to resumed,
        cancelled, superseded and failed are gone - cleanup now goes through
        withdrawn_unconfirmed."""
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.store.reserve(key, 151)
        self.store.update(key, state="submission_unknown")
        with self.assertRaises(StoreError):
            self.store.update(key, state="waiting_retry", submitted_at=None)
        for removed in ("resumed", "cancelled", "superseded", "failed"):
            with self.subTest(removed=removed), self.assertRaises(StoreError):
                self.store.update(key, state=removed)
        self.store.update(key, state="queued", queue_id=OTHER)
        self.store.update(key, state="turn_started", recovery_turn_id=new_turn())
        self.assertFalse(self.store.reserve(key, 170))
        self.assertEqual(self.store.get(key)["state"], "turn_started")

    def test_proven_no_launch_can_reach_terminal_retry_limit(self):
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.store.reserve(key, 151)
        self.store.update(key, state="failed", submitted_at=None, retry_count=5,
                          last_error="queue_launch_retry_limit")
        self.assertFalse(self.store.reserve(key, 200))

    def test_cancel_only_target_thread_and_keep_sent_for_reconciliation(self):
        """The thread-wide cancel is `cancel_thread`; `cancel` stays as its v0.5 name."""
        self.assertEqual(Store.cancel, Store.cancel_thread)
        self.store.register(failure(), 111)
        self.store.register(failure("b" * 64, OTHER), 111)
        self.store.cancel(THREAD, 115)
        self.assertFalse(self.store.thread_enabled(THREAD))
        self.assertEqual(self.store.get("a" * 64)["state"], "cancelled")
        self.assertEqual(len(self.store.pending()), 1)
        self.store.set_enabled(True, 100)
        self.store.reserve("b" * 64, 151)
        self.store.cancel_thread(OTHER, 152)
        self.assertEqual(self.store.get("b" * 64)["state"], "submitting")
        self.assertTrue(self.store.get("b" * 64)["cancel_requested"])
        self.assertFalse(self.store.thread_enabled(OTHER))

    def test_submitted_at_alone_blocks_a_second_reservation(self):
        """Defense in depth: a claimed record returns to waiting only with its send
        disproved, and even a row forced into that shape outside the store is never
        reserved again - that would be a double send."""
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.assertTrue(self.store.reserve(key, 151))
        with self.assertRaises(StoreError):
            self.store.update(key, state="waiting_retry")      # submitted_at kept
        force(self.db, key, state="waiting_retry")
        self.assertIsNotNone(self.row(key)["submitted_at"], "precondition: the send may have happened")
        try:
            claimed = self.store.reserve(key, 200)
        except StoreError:
            claimed = False                                     # refusing to read it is fail-closed too
        self.assertFalse(claimed, "a possible prior send must never be repeated")
        self.assertEqual(self.row(key)["state"], "waiting_retry")
        self.assertEqual(self.row(key)["attempt_count"], 1)

    def test_register_persists_its_schedule_in_one_transaction(self):
        event = failure()
        self.assertTrue(self.store.register(event, 111, state="waiting_poll", next_retry_at=999))
        row = self.store.get(event["interruption_id"])
        self.assertEqual(row["state"], "waiting_poll")
        self.assertEqual(row["next_retry_at"], 999)
        with self.assertRaises(StoreError):
            self.store.register(failure("b" * 64, turn_id=new_turn()), 111, state="queued")
        self.assertIsNone(self.store.get("b" * 64))

    def test_terminal_never_reactivated(self):
        self.store.register(failure(), 111)
        self.store.update("a" * 64, state="superseded", last_error="later_turn_exists")
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.status_counts(), {"superseded": 1})
        with self.assertRaises(StoreError):
            self.store.update("a" * 64, state="waiting_reset")

    def test_update_rejects_identity_unknown_state_and_nonfinite_time(self):
        self.store.register(failure(), 111)
        for changes in ({"thread_id": OTHER}, {"state": "anything"}, {"reset_at": float("inf")},
                        {"retry_count": -1}, {"last_error": "line1\nline2"},
                        {"chain_origin_id": "b" * 64}, {"history_hidden_at": 200.0},
                        {"last_claim_at": 200.0}, {"legacy": True}):
            with self.subTest(changes=changes), self.assertRaises(StoreError):
                self.store.update("a" * 64, **changes)
        self.assertEqual(self.store.get("a" * 64)["state"], "waiting_reset")

    def test_every_record_belongs_to_a_chain(self):
        """Section 2.1: `chain_origin_id` is backfilled and required non-empty; a new
        record with no parent is its own chain."""
        self.store.register(failure(), 111)
        row = self.store.get("a" * 64)
        self.assertEqual((row["chain_origin_id"], row["chain_first_detected_at"]), ("a" * 64, 111))
        self.assertIsNone(row["parent_interruption_id"])
        force(self.db, "a" * 64, chain_origin_id="")
        with self.assertRaises(StoreError):
            self.store.get("a" * 64)

    def test_bad_fixture_rejected_without_partial_insert(self):
        for field, value in (("thread_id", "--last"), ("interruption_id", "a\nb"),
                             ("completed_at", float("nan")), ("uncertain", 2), ("ordinal", -1)):
            event = failure()
            event[field] = value
            with self.subTest(field=field), self.assertRaises(StoreError):
                self.store.register(event, 111)
        self.assertEqual(self.store.all_records(), [])

    def test_corrupt_database_fails_without_reset(self):
        self.db.close()
        self.store.close()
        (self.root / "state.sqlite").write_bytes(b"not a sqlite file")
        with self.assertRaises(StoreError) as caught:
            Store(self.root)
        # Section 2.4: a corruption is never reported as "state from a newer version".
        self.assertNotIsInstance(caught.exception, StateFromNewerVersion)
        self.assertEqual((self.root / "state.sqlite").read_bytes(), b"not a sqlite file")

    def test_newer_schema_and_unknown_record_state_fail_closed(self):
        self.store.register(failure(), 111)
        self.store.close()
        self.db.execute("PRAGMA user_version=4")      # a schema from a future version
        with self.assertRaises(StateFromNewerVersion):
            Store(self.root)
        self.db.execute("PRAGMA user_version=3")
        self.db.execute("UPDATE interruptions SET state='unexpected'")
        with self.assertRaises(StoreError):
            Store(self.root)

    def test_invalid_settings_fail_closed(self):
        self.store.close()
        self.db.execute("UPDATE settings SET poll_seconds=0")
        with self.assertRaises(StoreError):
            Store(self.root)

    def test_existing_empty_state_is_never_silently_reset(self):
        self.db.close()
        self.store.close()
        (self.root / "state.sqlite").write_bytes(b"")
        with self.assertRaises(StoreError):
            Store(self.root)
        self.assertEqual((self.root / "state.sqlite").read_bytes(), b"")


# ============================================================================ T12
DESIGN_TABLE = {
    # Section 3.2, the moves a plain `update` may make. Entries marked "only via X"
    # there are dedicated operations and are deliberately absent. A same-state
    # rewrite is not a move and is compared separately.
    **{state: (WAITING - {state}) | {"superseded", "superseded_by_user", "retry_budget_exhausted",
                                     "no_progress_exhausted", "terminal_failure"}
       for state in WAITING},
    "submitting": {"queued", "waiting_retry", "failed", "withdrawn_unconfirmed", "turn_started",
                   "handed_over", "submission_unknown"},
    "queued": {"withdrawn_unconfirmed", "turn_started", "handed_over", "submission_unknown"},
    "withdrawn_unconfirmed": {"turn_started", "cancelled", "superseded", "superseded_by_user",
                              "failed", "submission_unknown"},
    "submission_unknown": {"queued", "withdrawn_unconfirmed", "turn_started", "handed_over"},
    "turn_started": {"turn_completed", "handed_over", "stopped_by_user", "outcome_unverified"},
    "turn_completed": {"recovered", "completed_no_progress", "recovery_turn_failed", "handed_over",
                       "stopped_by_user", "outcome_unverified"},
}


class TransitionTableTests(_StoreCase):
    """T12: the section 3.2 table, enforced by `Store.update` for every pair."""

    def attempts(self, fixture, target, recovery_turn):
        """Every plausible way to ask for `target`: with the fields the target needs,
        then also with the submission forgotten, then also with the queue id dropped. An
        allowed move must succeed one of these ways; a refused one must fail all of them."""
        base = {"state": target}
        if target in SENT and fixture["submitted_at"] is None:
            base["submitted_at"] = 151.0
        if target in NEEDS_RECOVERY_TURN:
            base["recovery_turn_id"] = fixture["recovery_turn_id"] or recovery_turn
        if target == "withdrawn_unconfirmed":
            base.update(withdraw_reason=fixture["withdraw_reason"] or "cancel",
                        withdrawn_at=fixture["withdrawn_at"] or 160.0, withdraw_deleted=True)
        yield base
        if target not in SENT:
            yield {**base, "submitted_at": None}
            yield {**base, "submitted_at": None, "queue_id": None}

    def test_T12_update_allows_exactly_the_plain_moves(self):
        """Every STATES x STATES pair through `Store.update`: the moves it makes are
        exactly `machine.PLAIN_MOVES` (plus a same-state rewrite), and a refused move
        leaves neither a changed row nor a journal line behind."""
        self.fast()
        keys = {state: self.make(state) for state in sorted(STATES)}
        for source in sorted(STATES):
            key = keys[source]
            fixture = self.row(key)
            restore = {column: value for column, value in fixture.items() if column != "interruption_id"}
            allowed = set(PLAIN_MOVES.get(source, ())) | {source}
            for target in sorted(STATES):
                with self.subTest(source=source, target=target):
                    succeeded = []
                    for changes in self.attempts(fixture, target, self.rts[key]):
                        events = event_count(self.db, key)
                        try:
                            self.store.update(key, at=200.0, **changes)
                        except StoreError:
                            succeeded.append(False)
                            self.assertEqual(self.row(key), fixture, "a refused update wrote something")
                            self.assertEqual(event_count(self.db, key), events,
                                             "a refused update journaled something")
                        else:
                            succeeded.append(True)
                            self.assertEqual(self.row(key)["state"], target)
                            force(self.db, key, **restore)
                    if target in allowed:
                        self.assertTrue(any(succeeded), "an allowed move was refused")
                    else:
                        self.assertFalse(any(succeeded), "a move outside the table was made")

    def test_T12_plain_moves_match_the_design_table(self):
        """The table the store enforces is the one the design states - no extra move,
        because every extra move is a path the invariants in section 3.2 did not prove."""
        found ={state: set(PLAIN_MOVES.get(state, ())) - {state} for state in STATES}
        expected = {state: set(DESIGN_TABLE.get(state, ())) for state in STATES}
        for state in sorted(STATES):
            with self.subTest(source=state):
                self.assertEqual(found[state], expected[state])

    def test_T12_nothing_possibly_sent_returns_to_waiting_by_update(self):
        """The only plain way back to waiting from a claim is the not-started path."""
        for state in sorted(STATES - WAITING):
            with self.subTest(source=state):
                back = set(PLAIN_MOVES.get(state, ())) & WAITING
                self.assertEqual(back, {"waiting_retry"} if state == "submitting" else set())

    def test_T12_observing_never_goes_back_to_claimed_in_flight_or_waiting(self):
        """A turn our continuation started is followed to its end; it can never become
        something that might be sent, or withdrawn, again."""
        for state in OBSERVING:
            with self.subTest(source=state):
                self.assertFalse(set(PLAIN_MOVES.get(state, ())) & (WAITING | CLAIMED | IN_FLIGHT))
        for state in sorted(OBSERVING):
            for target in ("waiting_poll", "submitting", "queued", "withdrawn_unconfirmed"):
                key = self.make(state)
                with self.subTest(source=state, target=target), self.assertRaises(StoreError):
                    self.store.update(key, state=target, withdraw_reason="cancel", withdrawn_at=200.0)

    def test_T12_cancelled_with_a_submission_only_from_withdrawn_unconfirmed(self):
        """C3: a plain update never cancels something that may be in Codex; only the
        settle of a withdrawn item may."""
        sources = {state for state in STATES if "cancelled" in PLAIN_MOVES.get(state, ())}
        self.assertEqual(sources, {"withdrawn_unconfirmed"})
        for state in ("submitting", "queued"):
            key = self.make(state)
            with self.subTest(state=state):
                with self.assertRaises(StoreError):
                    self.store.update(key, state="cancelled")
                with self.assertRaises(StoreError):
                    self.store.update(key, state="cancelled", submitted_at=None, queue_id=None)
                self.assertEqual(self.row(key)["state"], state)
        key = self.make("withdrawn_unconfirmed")
        self.store.update(key, state="cancelled", last_error="owned_queue_removed")
        self.assertEqual(self.row(key)["state"], "cancelled")
        self.assertIsNotNone(self.row(key)["submitted_at"])

    def test_T12_moves_reserved_for_dedicated_operations(self):
        """What the table marks "only via X" is refused by `update` and done by X."""
        self.store.set_enabled(True, 100)
        # WAITING -> submitting only via reserve.
        key = self.make("waiting_poll")
        with self.assertRaises(StoreError):
            self.store.update(key, state="submitting", submitted_at=151.0)
        self.assertTrue(self.store.reserve(key, 151))
        self.assertEqual(self.row(key)["state"], "submitting")
        # WAITING -> cancelled only via cancel_interruption.
        key = self.make("waiting_backoff", category="server_5xx")
        with self.assertRaises(StoreError):
            self.store.update(key, state="cancelled")
        self.store.cancel_interruption(key, 160)
        self.assertEqual(self.row(key)["state"], "cancelled")
        # submitting -> WAITING, cancelled, superseded* only via release_claim.
        for target in ("waiting_poll", "waiting_backoff", "cancelled", "superseded", "superseded_by_user"):
            key = self.make("submitting", retry_count=2)
            with self.subTest(target=target):
                with self.assertRaises(StoreError):
                    self.store.update(key, state=target, submitted_at=None)
                self.assertTrue(self.store.release_claim(key, target, "released_before_send", 160))
                row = self.row(key)
                self.assertEqual(row["state"], target)
                self.assertIsNone(row["submitted_at"])
                self.assertEqual(row["last_claim_at"], 151.0, "the claim still counts")
                self.assertEqual(row["retry_count"], 2, "no attempt happened")
                self.assertEqual(self.store.events(key)[-1]["code"], "release_claim")
        # ... and never for something that may have left.
        for state, columns in (("queued", {}), ("submitting", {"queue_id": QUEUE})):
            key = self.make(state, **columns)
            with self.subTest(release_from=state, **columns):
                self.assertFalse(self.store.release_claim(key, "waiting_poll", "released_before_send", 160))
                self.assertEqual(self.row(key)["state"], state)
        # exhausted -> WAITING only via restore_budget.
        key = self.make("retry_budget_exhausted")
        with self.assertRaises(StoreError):
            self.store.update(key, state="waiting_poll")
        self.assertTrue(self.store.restore_budget(key, 500))
        # submission_unknown -> turn_started: allowed through correlate and through update.
        key = self.make("submission_unknown")
        self.assertTrue(self.store.correlate(key, new_turn(), 170))
        self.assertEqual(self.row(key)["state"], "turn_started")
        key = self.make("submission_unknown")
        self.store.update(key, state="turn_started", recovery_turn_id=new_turn())
        self.assertEqual(self.row(key)["state"], "turn_started")
        # correlate never starts from a record that was never sent.
        key = self.make("waiting_poll")
        self.assertFalse(self.store.correlate(key, new_turn(), 170))
        self.assertEqual(self.row(key)["state"], "waiting_poll")

    def test_T12_validator_rejects_observing_without_its_proof(self):
        """An OBSERVING row names a sent continuation and the exact turn it started;
        without either it is not a row this store will read."""
        cases = [(state, column) for state in sorted(OBSERVING) for column in ("submitted_at", "recovery_turn_id")]
        cases += [(state, "recovery_turn_id") for state in sorted(NEEDS_RECOVERY_TURN - OBSERVING)]
        cases += [("withdrawn_unconfirmed", "withdraw_reason"), ("withdrawn_unconfirmed", "withdrawn_at")]
        for state, column in cases:
            key = self.make(state)
            with self.subTest(state=state, missing=column):
                with self.assertRaises(StoreError):
                    self.store.update(key, **{column: None})
                good = self.row(key)[column]
                force(self.db, key, **{column: None})
                with self.assertRaises(StoreError):
                    self.store.get(key)
                with self.assertRaises(StoreError):
                    Store(self.root).close()
                force(self.db, key, **{column: good})
        # And a move into OBSERVING must carry its proof.
        key = self.make("queued")
        with self.assertRaises(StoreError):
            self.store.update(key, state="turn_started")
        self.assertEqual(self.row(key)["state"], "queued")

    def test_T12_a_recovery_turn_is_written_once(self):
        """Section 2.1: the recovery turn is written once, and no two records may own one
        turn (C10) - a second owner would make two chains out of one continuation."""
        key = self.make("turn_started")
        with self.assertRaises(StoreError):
            self.store.update(key, recovery_turn_id=new_turn())
        other = self.make("queued")
        # The unique index: no two records may own one Codex turn.
        with self.assertRaises(StoreError):
            self.store.update(other, state="turn_started", recovery_turn_id=self.row(key)["recovery_turn_id"])
        self.assertFalse(self.store.correlate(other, self.row(key)["recovery_turn_id"], 170))
        self.assertEqual(self.row(other)["state"], "queued")


# ============================================================================ T19
class _Crashing:
    """A connection that dies at one chosen statement: before it, or right after it
    ran. Everything else passes straight through, including the rollback."""

    def __init__(self, real, at=None, after=False, relaxed=False):
        vars(self).update(real=real, at=at, after=after, calls=0, relaxed=relaxed)

    def execute(self, *args):
        vars(self)["calls"] += 1
        if self.relaxed and args[0] == "PRAGMA synchronous=FULL":
            # Rollback on an exception does not depend on fsync; only the clock does.
            args = ("PRAGMA synchronous=OFF",) + args[1:]
        hit = self.calls == self.at
        if hit and not self.after:
            raise sqlite3.OperationalError("injected crash before statement %d" % self.calls)
        result = self.real.execute(*args)
        if hit:
            raise sqlite3.OperationalError("injected crash after statement %d" % self.calls)
        return result

    def __getattr__(self, name):
        return getattr(vars(self)["real"], name)

    def __setattr__(self, name, value):
        setattr(vars(self)["real"], name, value)


def snapshot(root):
    """Everything a transaction here may write: the records and the journal."""
    with closing(sqlite3.connect(Path(root) / "state.sqlite")) as db:
        db.row_factory = sqlite3.Row
        records = [dict(row) for row in db.execute("SELECT * FROM interruptions ORDER BY interruption_id")]
        events = [tuple(row)[1:] for row in db.execute("SELECT * FROM events ORDER BY event_id")]
    return records, events


PARENT, CHILD, FAILED_TURN = "parent-0001", "child-0001", "0a1b2c3d-0006-7000-8000-000000000006"


class CrashInjectionTests(unittest.TestCase):
    """T19: a crash after any statement of `register` or `reserve` leaves either the
    whole transaction or none of it. Chain counters and `recovery_attempts` are what a
    half-written claim or child would lose, and they are what bounds a retry loop."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = 0

    def fresh(self, build):
        self.runs += 1
        root = Path(self.temp.name) / ("run-%03d" % self.runs)
        build(root)
        return root

    @staticmethod
    def build_register(root):
        with Store(root) as store:
            store.register(failure(PARENT, THREAD, TURN, "server_5xx"), 100.0)
        with closing(raw(root)) as db:
            # A continuation that was claimed and never correlated, deep into its chain.
            force(db, PARENT, **{**shape("submission_unknown", None), "chain_continuations": 2,
                                 "recovery_attempts": 2, "usage_unavailable_seconds": 100.0,
                                 "budget_resets": 1, "no_progress_count": 1,
                                 "chain_first_detected_at": 50.0})

    @staticmethod
    def do_register(store):
        return store.register(failure(CHILD, THREAD, FAILED_TURN, "server_5xx"), 300.0,
                              state="waiting_backoff", next_retry_at=360.0, owner_id=PARENT,
                              failed_turn_progress=False, limits=LIMITS)

    @staticmethod
    def build_reserve(root):
        with Store(root) as store:
            store.register(failure(CHILD, THREAD, FAILED_TURN, "server_5xx"), 300.0,
                           state="waiting_backoff", next_retry_at=360.0)
            store.set_enabled(True, 100.0)
        with closing(raw(root)) as db:
            force(db, CHILD, chain_continuations=1, recovery_attempts=1)

    @staticmethod
    def do_reserve(store):
        claimed, gate, _reason = store.reserve_detailed(CHILD, 400.0, limits=LIMITS, gates=ALL_PASS)
        if not claimed:
            raise AssertionError("fixture not claimable: %s" % gate)

    def run_with(self, root, operation, at=None, after=False):
        store = Store(root)
        proxy = _Crashing(store._connection, at, after)
        store._connection = proxy
        try:
            operation(store)
        finally:
            store.close()
        return proxy.calls

    def all_or_nothing(self, build, operation):
        root = self.fresh(build)
        before = snapshot(root)
        total = self.run_with(root, operation)
        after = snapshot(root)
        self.assertNotEqual(before, after, "the operation must change something")
        self.assertGreater(total, 3)
        for position in range(1, total + 1):
            for crash_after in (False, True):
                with self.subTest(statement=position, after_it=crash_after):
                    root = self.fresh(build)
                    with self.assertRaises(StoreError):
                        self.run_with(root, operation, position, crash_after)
                    found = snapshot(root)
                    committed = crash_after and position == total
                    self.assertEqual(found, after if committed else before)
                    Store(root).close()        # and the state still opens
        return after

    def test_T19_register_with_a_parent_is_all_or_nothing(self):
        records, events = self.all_or_nothing(self.build_register, self.do_register)
        rows = {row["interruption_id"]: row for row in records}
        child, parent = rows[CHILD], rows[PARENT]
        # Section 4.4: the child continues its parent's chain with every counter.
        self.assertEqual(child["parent_interruption_id"], PARENT)
        self.assertEqual(child["chain_origin_id"], PARENT)
        self.assertEqual(child["chain_first_detected_at"], 50.0)
        self.assertEqual(child["chain_continuations"], 2)
        self.assertEqual(child["recovery_attempts"], 2)
        self.assertEqual(child["usage_unavailable_seconds"], 100.0)
        self.assertEqual(child["budget_resets"], 1)
        self.assertEqual(child["no_progress_count"], 2)
        self.assertEqual(child["state"], "waiting_backoff")
        self.assertEqual(child["next_retry_at"], 360.0)
        # The owner found by its marker is linked to the turn it started.
        self.assertEqual(parent["recovery_turn_id"], FAILED_TURN)
        self.assertEqual([event[3] for event in events if event[1] == CHILD], ["detected"])

    def test_T19_reserve_is_all_or_nothing(self):
        records, events = self.all_or_nothing(self.build_reserve, self.do_reserve)
        row = records[0]
        # Section 4.4: everything a claim changes, in the one transaction.
        self.assertEqual(row["state"], "submitting")
        self.assertEqual(row["attempt_count"], 1)
        self.assertEqual(row["recovery_attempts"], 2)
        self.assertEqual(row["chain_continuations"], 2)
        self.assertEqual(row["submitted_at"], 400.0)
        self.assertEqual(row["last_claim_at"], 400.0)
        self.assertIsNotNone(row["gate_eval"])
        self.assertEqual(row["gate_eval_at"], 400.0)
        self.assertEqual([event[3] for event in events], ["detected", "claim"])


# ============================================================================ T21
class CancelTests(_StoreCase):
    """T21, store part: `cancel_interruption` is chain-scoped (section 7.2)."""

    def chain(self):
        origin = self.make("recovered")
        members = {"origin": origin}
        for state in ("waiting_poll", "waiting_backoff", "submitting", "queued", "withdrawn_unconfirmed",
                      "submission_unknown", "turn_started", "turn_completed", "retry_budget_exhausted",
                      "no_progress_exhausted", "superseded", "outcome_unverified"):
            members[state] = self.make(state, chain_origin_id=origin, parent_interruption_id=origin)
        return members

    def test_T21_cancel_applies_to_every_row_of_the_chain(self):
        """Section 7.2 table, row by row: unsent waits are cancelled; anything that may
        be in Codex (submission_unknown included) is only marked, so the watch withdraws
        it and a running turn is followed; finished rows are marked to block a child."""
        members = self.chain()
        unrelated = self.make("waiting_poll")
        elsewhere = self.make("queued", thread_id=OTHER)
        result = self.store.cancel_interruption(members["turn_started"], 500.0, actor="toast")
        self.assertTrue(result["changed"])
        self.assertEqual(set(result["effects"]), set(members.values()))
        for role, key in members.items():
            row = self.row(key)
            with self.subTest(member=role):
                self.assertEqual(row["cancel_requested"], 1, "every chain row blocks a future child")
                if role in WAITING:
                    self.assertEqual(row["state"], "cancelled")
                    self.assertEqual(row["last_error"], "user_cancelled")
                    self.assertEqual(result["effects"][key], "cancelled")
                elif role in SENT | {"submission_unknown"}:
                    self.assertEqual(row["state"], role, "possibly sent: only marked, never cancelled")
                    self.assertEqual(result["effects"][key], "cancel_requested")
                else:
                    self.assertEqual(row["state"], "recovered" if role == "origin" else role)
                    self.assertNotIn(result["effects"][key], ("cancelled", "cancel_requested"))
                events = self.store.events(key)
                self.assertEqual(events[-1]["actor"], "toast")
                self.assertEqual(events[-1]["code"], "cancel" if role in WAITING else "cancel_requested")
        for key in (unrelated, elsewhere):
            self.assertEqual(self.row(key)["cancel_requested"], 0, "another chain is untouched")
        self.assertTrue(self.store.thread_enabled(THREAD), "the chain cancel is not thread-wide")
        # Exhausted rows cannot be reset once cancelled.
        self.assertFalse(self.store.restore_budget(members["retry_budget_exhausted"], 600.0))
        # A repeat changes nothing and journals nothing.
        events = event_count(self.db)
        again = self.store.cancel_interruption(members["origin"], 700.0)
        self.assertFalse(again["changed"])
        self.assertEqual(event_count(self.db), events)

    def test_T21_nothing_running_reports_no_change_but_blocks_a_future_child(self):
        """D5: a true no-op says "already finished; nothing to stop" (changed false),
        yet the mark it leaves still stops a later failure of that task from recovering."""
        finished = self.make("recovered")
        stopped = self.make("superseded", chain_origin_id=finished)
        result = self.store.cancel_interruption(finished, 500.0)
        self.assertFalse(result["changed"], "already finished; nothing to stop")
        self.assertEqual({self.row(finished)["cancel_requested"], self.row(stopped)["cancel_requested"]}, {1})
        self.assertEqual(self.row(finished)["state"], "recovered")
        # The recovery turn of that finished record now fails: the child starts stopped.
        child = failure("child-of-finished", THREAD, self.row(finished)["recovery_turn_id"], "server_5xx")
        self.assertTrue(self.store.register(child, 600.0, state="waiting_backoff", limits=LIMITS))
        row = self.store.get("child-of-finished")
        self.assertEqual((row["state"], row["last_error"]), ("cancelled", "parent_cancelled"))
        self.assertEqual(row["chain_origin_id"], finished)

    def test_T21_cancel_never_cancels_something_possibly_sent(self):
        """T21's first case: a cancel of a submission_unknown whose row may still be
        queued is a real change (the watch must withdraw it), never "already finished"."""
        for state in ("submitting", "queued", "withdrawn_unconfirmed", "submission_unknown",
                      "turn_started", "turn_completed"):
            key = self.make(state)
            with self.subTest(state=state):
                self.assertTrue(self.store.cancel_interruption(key, 500.0)["changed"])
                row = self.row(key)
                self.assertEqual((row["state"], row["cancel_requested"]), (state, 1))


# ============================================================================ T24
class ReleaseWithdrawnTests(_StoreCase):
    """T24, store part: the one way back from "sent" to "waiting" after a Pause."""

    RELEASE = dict(window=180.0, later_turn=False, marker_rows=0, row_present=False, fresh=True,
                   target="waiting_poll")

    def withdrawn(self, **columns):
        return self.make("withdrawn_unconfirmed", **{"withdraw_reason": "paused", "withdrawn_at": 300.0,
                                                     "withdraw_deleted": 1, "last_error": "paused",
                                                     **columns})

    def test_T24_release_after_a_paused_withdrawal_returns_to_waiting(self):
        # Built the way the engine builds it: claim, queue, withdraw on Pause.
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.assertTrue(self.store.reserve(key, 151))
        self.store.update(key, state="queued", queue_id=QUEUE, first_queued_at=152.0)
        self.store.update(key, state="withdrawn_unconfirmed", withdraw_reason="paused",
                          withdrawn_at=300.0, withdraw_deleted=True, last_error="paused")
        retries = self.row(key)["retry_count"]
        self.assertTrue(self.store.release_withdrawn(key, 480.0, **self.RELEASE))
        row = self.row(key)
        self.assertEqual(row["state"], "waiting_poll")
        self.assertIsNone(row["submitted_at"])
        self.assertIsNone(row["queue_id"])
        self.assertEqual(row["last_claim_at"], 151.0)
        self.assertEqual(row["first_queued_at"], 152.0)
        self.assertEqual(row["retry_count"], retries)
        self.assertIn(151.0, self.store.recent_claims(THREAD, 0), "the daily cap still counts it")
        self.assertEqual(self.store.events(key)[-1]["code"], "release_withdrawn")

    def test_T24_release_is_refused_unless_every_condition_holds(self):
        cases = [("reason %s" % reason, {"withdraw_reason": reason}, {})
                 for reason in sorted(machine.WITHDRAW_REASONS - {"paused"})]
        cases += [
            ("row vanished without our delete", {"withdraw_deleted": 0}, {}),
            ("before the window", {}, {"now": 479.0}),
            ("a later turn exists", {}, {"later_turn": True}),
            ("a marker row exists", {}, {"marker_rows": 1}),
            ("our row is still queued", {}, {"row_present": True}),
            ("projection not fresh", {}, {"fresh": False}),
            ("cancel requested", {"cancel_requested": 1}, {}),
        ]
        for name, columns, arguments in cases:
            key = self.withdrawn(**columns)
            before = self.row(key)
            now = arguments.pop("now", 480.0)
            with self.subTest(name):
                self.assertFalse(self.store.release_withdrawn(key, now, **{**self.RELEASE, **arguments}))
                self.assertEqual(self.row(key), before)
        for state in ("queued", "submission_unknown", "turn_started"):
            key = self.make(state, withdraw_reason="paused", withdrawn_at=300.0, withdraw_deleted=1)
            with self.subTest(state=state):
                self.assertFalse(self.store.release_withdrawn(key, 480.0, **self.RELEASE))
                self.assertEqual(self.row(key)["state"], state)
        key = self.withdrawn()
        with self.assertRaises(StoreError):
            self.store.release_withdrawn(key, 480.0, **{**self.RELEASE, "target": "cancelled"})
        self.assertTrue(self.store.release_withdrawn(key, 480.0, **self.RELEASE))


# ============================================================================ T26
class RestoreBudgetTests(_StoreCase):
    """Running out of attempts is the one terminal stop a person may undo.

    `update` refuses to reactivate any terminal record, which is what keeps a finished,
    cancelled or uncertainly-submitted recovery from being restarted by a stray write.
    These tests pin the exception down to exactly the two exhausted states and assert
    that everything else stays refused, since a wider hole here would quietly re-open
    the no-resend guarantee.
    """

    def setUp(self):
        super().setUp()
        self.key = failure()["interruption_id"]
        self.store.register(failure(), 100)

    def exhaust(self, state="retry_budget_exhausted", key=None):
        self.store.update(key or self.key, state=state, recovery_attempts=4, no_progress_count=3,
                          retry_count=2, last_error="recovery_budget")

    def test_restores_the_two_exhausted_states(self):
        for state in ("retry_budget_exhausted", "no_progress_exhausted"):
            with self.subTest(state=state):
                self.exhaust(state)
                self.assertTrue(self.store.restore_budget(self.key, 500))
                record = self.store.get(self.key)
                # A usage record whose stored reset has passed goes back to polling.
                self.assertEqual(record["state"], "waiting_poll")
                self.assertEqual(record["recovery_attempts"], 0)
                self.assertEqual(record["no_progress_count"], 0)
                self.assertNotEqual(record["last_error"], "recovery_budget")
                self.assertEqual(record["next_retry_at"], 500)

    def test_refuses_every_other_terminal_state(self):
        for state in sorted(TERMINAL - EXHAUSTED):
            key = self.make(state)
            with self.subTest(state=state):
                self.assertFalse(self.store.restore_budget(key, 500))
                self.assertEqual(self.store.get(key)["state"], state)

    def test_refuses_every_state_that_is_not_terminal(self):
        for state in sorted(STATES - TERMINAL):
            key = self.make(state)
            with self.subTest(state=state):
                self.assertFalse(self.store.restore_budget(key, 500))
                self.assertEqual(self.store.get(key)["state"], state)

    def test_refuses_a_waiting_record(self):
        self.assertFalse(self.store.restore_budget(self.key, 500))

    def test_refuses_an_unknown_interruption(self):
        self.assertFalse(self.store.restore_budget("f" * 64, 500))

    def test_refuses_a_cancelled_record(self):
        self.exhaust()
        self.store.cancel_interruption(self.key, 400)
        self.assertEqual(self.store.get(self.key)["state"], "retry_budget_exhausted")
        self.assertFalse(self.store.restore_budget(self.key, 500))

    def test_never_reactivates_something_that_may_have_been_sent(self):
        # An exhausted record should not carry a submission stamp or a queue id, but if
        # one ever did, restoring its budget would be a resend of an uncertain send.
        for columns in ({"submitted_at": 110.0}, {"queue_id": QUEUE}):
            key = self.make("retry_budget_exhausted", **columns)
            with self.subTest(**columns):
                self.assertFalse(self.store.restore_budget(key, 500))
                self.assertEqual(self.store.get(key)["state"], "retry_budget_exhausted")

    def test_does_not_submit(self):
        self.exhaust()
        self.store.restore_budget(self.key, 500)
        record = self.store.get(self.key)
        self.assertIsNone(record["submitted_at"])
        self.assertIsNone(record["queue_id"])
        self.assertEqual(record["attempt_count"], 0)

    def test_restored_record_is_pending_again(self):
        self.exhaust()
        self.store.restore_budget(self.key, 500)
        self.assertEqual([row["interruption_id"] for row in self.store.pending()], [self.key])

    def test_T26_usage_record_returns_to_its_reset_wait_and_transient_to_backoff(self):
        future = self.make("retry_budget_exhausted", reset_at=900.0)
        passed = self.make("no_progress_exhausted", reset_at=150.0)
        unknown = self.make("retry_budget_exhausted", reset_at=None)
        transient = self.make("retry_budget_exhausted", category="server_5xx")
        for key, target in ((future, "waiting_reset"), (passed, "waiting_poll"),
                            (unknown, "waiting_poll"), (transient, "waiting_backoff")):
            with self.subTest(target=target):
                self.assertTrue(self.store.restore_budget(key, 500.0))
                row = self.row(key)
                self.assertEqual(row["state"], target)
                self.assertEqual(row["next_retry_at"], 500.0)

    def test_T26_reset_clears_every_budget_counter_and_nothing_else(self):
        key = self.make("retry_budget_exhausted", category="server_5xx", recovery_attempts=5,
                        no_progress_count=2, retry_count=3, chain_continuations=6, attempt_count=4)
        self.store.set_thread_enabled(THREAD, False)
        self.assertTrue(self.store.restore_budget(key, 500.0, actor="mcp"))
        row = self.row(key)
        for column in ("recovery_attempts", "no_progress_count", "retry_count", "chain_continuations"):
            self.assertEqual(row[column], 0, column)
        self.assertEqual(row["budget_resets"], 1)
        self.assertEqual(row["attempt_count"], 4, "a reset is not an attempt")
        self.assertIsNone(row["submitted_at"])
        self.assertFalse(self.store.thread_enabled(THREAD), "a reset never switches a thread back on")
        event = self.store.events(key)[-1]
        self.assertEqual((event["code"], event["actor"]), ("reset_budget", "mcp"))

    def test_T26_the_fourth_reset_of_a_record_is_refused(self):
        key = self.make("retry_budget_exhausted", category="server_5xx")
        for attempt in range(3):
            with self.subTest(reset=attempt + 1):
                self.assertTrue(self.store.restore_budget(key, 500.0 + attempt))
                self.exhaust(key=key)
        self.assertFalse(self.store.restore_budget(key, 600.0))
        row = self.row(key)
        self.assertEqual((row["state"], row["budget_resets"]), ("retry_budget_exhausted", 3))

    def test_T26_the_reset_count_belongs_to_the_chain(self):
        """A later record of the same task inherits the resets already spent, so the
        fourth reset is refused whichever record of the chain it is asked of."""
        parent = self.make("recovered", category="server_5xx", budget_resets=2)
        turn = self.row(parent)["recovery_turn_id"]
        self.assertTrue(self.store.register(failure("chain-child", THREAD, turn, "server_5xx"), 600.0,
                                            state="waiting_backoff"))
        self.assertEqual(self.store.get("chain-child")["budget_resets"], 2)
        self.exhaust(key="chain-child")
        self.assertTrue(self.store.restore_budget("chain-child", 700.0))
        self.exhaust(key="chain-child")
        self.assertFalse(self.store.restore_budget("chain-child", 800.0))


# ============================================================================ T33
class RetryNowTests(_StoreCase):
    """T33, section 8: Retry Now moves a waiting record's schedule and nothing else."""

    def test_T33_refused_for_every_state_that_is_not_waiting(self):
        details = {}
        for state in sorted(STATES - WAITING):
            key = self.make(state)
            before = self.row(key)
            events = event_count(self.db, key)
            with self.subTest(state=state):
                accepted, detail = self.store.request_retry_now(key, 400.0)
                self.assertFalse(accepted)
                self.assertEqual(self.row(key), before)
                self.assertEqual(event_count(self.db, key), events)
                if before["cancel_requested"]:
                    continue        # refused for the pending cancel, which is also right
                klass = ("claimed" if state in CLAIMED else "in_flight" if state in IN_FLIGHT
                         else "observing" if state in OBSERVING else "terminal")
                details.setdefault(klass, set()).add(detail)
        # "The reply says which": one answer per class, and the classes are told apart.
        self.assertTrue(all(len(found) == 1 for found in details.values()), details)
        self.assertEqual(len({next(iter(found)) for found in details.values()}), 4, details)

    def test_T33_refused_while_a_cancel_is_pending(self):
        key = self.make("waiting_backoff", category="server_5xx", cancel_requested=1)
        before = self.row(key)
        self.assertFalse(self.store.request_retry_now(key, 400.0)[0])
        self.assertEqual(self.row(key), before)

    def test_T33_moves_only_the_schedule(self):
        for reset_at, eligible in ((None, 400.0), (150.0, 400.0), (1000.0, 1000.0)):
            for state in sorted(WAITING):
                key = self.make(state, reset_at=reset_at, next_retry_at=900.0, retry_now_count=1)
                before = self.row(key)
                with self.subTest(state=state, reset_at=reset_at):
                    self.assertEqual(self.store.request_retry_now(key, 400.0, actor="cli"), (True, eligible))
                    after = self.row(key)
                    self.assertEqual(after["next_retry_at"], 400.0)
                    self.assertEqual(after["retry_now_count"], 2)
                    self.assertEqual(after["reset_at"], reset_at)
                    changed = {column for column in before if before[column] != after[column]}
                    self.assertEqual(changed, {"next_retry_at", "retry_now_count"})
                    event = self.store.events(key)[-1]
                    self.assertEqual((event["code"], event["actor"]), ("retry_now", "cli"))


# ============================================================================ T39
class JournalTests(_StoreCase):
    """T39 and T44, store part: the journal records, and never decides or blocks."""

    def test_T39_unknown_event_code_and_reason_are_stored_as_other(self):
        key = self.make("waiting_poll")
        self.store.update(key, at=200.0, event="not_a_known_code", state="waiting_backoff",
                          last_error="words nobody listed")
        self.assertEqual(self.row(key)["state"], "waiting_backoff", "the change still committed")
        stored = self.db.execute("SELECT code, reason FROM events WHERE interruption_id=? "
                                 "ORDER BY event_id DESC LIMIT 1", (key,)).fetchone()
        self.assertEqual(tuple(stored), ("other", "other"))
        self.store.update(key, at=201.0, state="waiting_poll", last_error="more unlisted words")
        stored = self.db.execute("SELECT code, reason FROM events WHERE interruption_id=? "
                                 "ORDER BY event_id DESC LIMIT 1", (key,)).fetchone()
        self.assertEqual(tuple(stored), ("state", "other"))

    def test_T39_invalid_client_id_and_turn_status_do_not_stop_a_correlation(self):
        key = self.make("queued")
        turn = new_turn()
        self.assertTrue(self.store.correlate(key, turn, 200.0, client_id="not a client id!",
                                             status="aBrandNewStatus"))
        row = self.row(key)
        self.assertEqual((row["state"], row["recovery_turn_id"]), ("turn_started", turn))
        self.assertIsNone(row["recovery_client_id"])
        self.assertEqual(row["recovery_turn_status"], "other")

    def test_T39_a_foreign_journal_row_never_fails_an_open_or_a_read(self):
        key = self.make("waiting_poll")
        self.db.execute(
            "INSERT INTO events (at, interruption_id, chain_origin_id, code, from_state, to_state, "
            "reason, actor, turn_ref, flags, value) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("yesterday", key, key, "zzz_unknown", "no_such_state", "neither", "free words\n",
             "somebody", new_turn(), "lots", "v"))
        self.db.execute(
            "INSERT INTO events (at, interruption_id, code, flags) VALUES (?,?,?,?)",
            (float("inf"), "bad id\nwith a newline", "detected", -1))
        self.store.close()
        with Store(self.root) as reopened:          # the full check at open
            entries = reopened.events()
            by_key = reopened.events(key)
            self.assertEqual(len(reopened.all_records()), 1)
            reopened.statistics()
        foreign = by_key[-1]
        self.assertEqual(foreign["code"], "other")
        self.assertEqual(foreign["reason"], "other")
        self.assertIsNone(foreign["from_state"])
        self.assertIsNone(foreign["to_state"])
        self.assertIsNone(foreign["turn_ref"], "a raw turn id never reaches an interface")
        self.assertIn(foreign["actor"], machine.ACTORS)
        self.assertIsInstance(foreign["flags"], int)
        self.assertIsInstance(foreign["at"], float)
        last = entries[-1]
        self.assertIsNone(last["interruption_id"])
        self.assertEqual(last["code"], "detected")

    def test_T44_re_entering_the_same_wait_journals_once(self):
        self.fast()
        key = self.make("waiting_poll")
        before = event_count(self.db, key)
        for tick in range(1000):
            self.store.update(key, at=200.0 + tick, state="waiting_for_loaded_thread",
                              last_error="notLoaded", next_retry_at=230.0 + tick)
        self.assertEqual(event_count(self.db, key), before + 1)
        # A different reason in the same state is a new line.
        self.store.update(key, at=2000.0, last_error="loaded_state_unknown")
        self.assertEqual(event_count(self.db, key), before + 2)

    def test_T44_two_writers_of_the_same_transition_journal_once(self):
        key = self.make("waiting_poll")
        before = event_count(self.db, key)
        barrier = threading.Barrier(2)
        errors = []

        def writer():
            try:
                with Store(self.root, check=False) as mine:
                    barrier.wait(5)
                    mine.update(key, at=200.0, state="waiting_for_loaded_thread", last_error="notLoaded")
            except Exception as exc:        # surfaced below, in the test thread
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(event_count(self.db, key), before + 1)

    def test_T44_a_refused_change_journals_nothing(self):
        key = self.make("queued")
        before = event_count(self.db)
        for changes in ({"state": "cancelled"}, {"state": "waiting_retry", "submitted_at": None},
                        {"state": "turn_started"}, {"cancel_requested": True, "state": "nonsense"}):
            with self.subTest(**changes), self.assertRaises(StoreError):
                self.store.update(key, at=200.0, **changes)
        self.assertEqual(event_count(self.db), before)

    def test_T44_pruning_keeps_the_story_of_every_record_still_running(self):
        self.fast()
        running = self.make("waiting_poll", now=1000.0)
        finished = self.make("waiting_poll", now=1000.0)
        self.store.update(finished, at=1000.0, state="superseded", last_error="later_turn_exists")
        kept = [row[0] for row in self.db.execute(
            "SELECT event_id FROM events WHERE interruption_id=?", (running,))]
        late = 1000.0 + 91 * 86400
        # Recent filler, more than the count limit, then fill up to the next prune.
        filler = "INSERT INTO events (at, code, flags) VALUES (?, 'state', 0)"
        self.db.execute("BEGIN")
        for _ in range(store_module.EVENT_LIMIT + 300):
            self.db.execute(filler, (late,))
        while self.db.execute("SELECT max(event_id) FROM events").fetchone()[0] % store_module._PRUNE_EVERY != \
                store_module._PRUNE_EVERY - 1:
            self.db.execute(filler, (late,))
        self.db.execute("COMMIT")
        self.store.update(running, at=late, state="waiting_backoff", last_error="retry_now")
        remaining = {row[0] for row in self.db.execute("SELECT event_id FROM events")}
        self.assertTrue(set(kept) <= remaining, "a running record lost its history")
        self.assertEqual(event_count(self.db, finished), 0, "old events of a finished record are pruned")
        self.assertLessEqual(len(remaining), store_module.EVENT_LIMIT + len(kept) + 1)

    def test_T44_event_ids_are_never_reused(self):
        sql = self.db.execute("SELECT sql FROM sqlite_master WHERE name='events'").fetchone()[0]
        self.assertIn("AUTOINCREMENT", sql.upper())
        key = self.make("waiting_poll")
        self.store.update(key, at=200.0, state="waiting_backoff", last_error="retry_now")
        highest = self.db.execute("SELECT max(event_id) FROM events").fetchone()[0]
        self.db.execute("DELETE FROM events WHERE event_id=?", (highest,))
        self.store.update(key, at=201.0, state="waiting_poll", last_error="retry_now")
        self.assertGreater(self.db.execute("SELECT max(event_id) FROM events").fetchone()[0], highest)


# ============================================================================ T41
class HideHistoryTests(_StoreCase):
    """T41, section 7.12: Clear history is display-only and never hides what may change."""

    NOW = 151.0 + 86400 + 10

    def test_T41_hides_only_finished_records_that_can_no_longer_change(self):
        kept = {
            "waiting": self.make("waiting_poll"),
            "claimed": self.make("submitting"),
            "withdrawn": self.make("withdrawn_unconfirmed"),
            "observing": self.make("turn_started"),
            "finishing": self.make("turn_completed"),
            "unknown in window": self.make("submission_unknown", submitted_at=self.NOW - 100,
                                           last_claim_at=self.NOW - 100),
            "unknown with a queue row": self.make("submission_unknown", queue_id=QUEUE),
        }
        hidden = {
            "unknown settled": self.make("submission_unknown"),
            "cancelled": self.make("cancelled"),
            "recovered": self.make("recovered"),
            "exhausted": self.make("retry_budget_exhausted"),
        }
        result = self.store.hide_history(self.NOW, actor="mcp")
        self.assertEqual(result["hidden"], len(hidden))
        for name, key in kept.items():
            with self.subTest(kept=name):
                self.assertIsNone(self.row(key)["history_hidden_at"])
        for name, key in hidden.items():
            with self.subTest(hidden=name):
                self.assertEqual(self.row(key)["history_hidden_at"], self.NOW)
        shown = {row["interruption_id"] for row in self.store.history()}
        self.assertEqual(shown, set(kept.values()))
        everything = {row["interruption_id"] for row in self.store.history(include_hidden=True)}
        self.assertEqual(everything, set(kept.values()) | set(hidden.values()))
        self.assertEqual(self.store.events()[-1]["code"], "hidden")
        self.assertEqual(self.store.events()[-1]["actor"], "mcp")

    def test_T41_hidden_rows_still_count_for_every_safety_decision(self):
        finished = self.make("recovered")
        drifted = self.make("cancelled")
        self.store.hide_history(self.NOW)
        self.assertEqual(self.row(finished)["history_hidden_at"], self.NOW)
        self.assertIn(finished, {row["interruption_id"] for row in self.store.all_records()})
        self.assertIn(151.0, self.store.recent_claims(THREAD, 0), "caps and cooldown")
        self.assertIn(finished, {row["interruption_id"] for row in self.store.claimed_on_thread(THREAD)})
        # Dedupe: the same failure is not a new record because its row is hidden.
        self.assertFalse(self.store.register(self.failures[drifted], self.NOW))
        # Identity drift: the same turn under a new identity is still refused.
        moved = dict(self.failures[drifted], interruption_id="moved-identity", completed_at=120.0)
        self.assertFalse(self.store.register(moved, self.NOW))
        self.assertIsNone(self.store.get("moved-identity"))
        # Chain lookup: a failure of the hidden record's recovery turn continues its chain.
        turn = self.row(finished)["recovery_turn_id"]
        self.assertTrue(self.store.register(failure("hidden-child", THREAD, turn, "server_5xx"),
                                            self.NOW, state="waiting_backoff"))
        child = self.store.get("hidden-child")
        self.assertEqual(child["parent_interruption_id"], finished)
        self.assertEqual(child["chain_origin_id"], self.row(finished)["chain_origin_id"])


# ============================================================================ 9.1
class StatisticsTests(_StoreCase):
    """Section 9.1: one final outcome per record, from `interruptions` rows only."""

    BUCKETS = {"recovered", "no_progress", "recovery_failed", "outcome_unverified", "handed_over",
               "stopped_by_user", "cancelled", "superseded", "exhausted", "failed_terminal",
               "submission_unknown", "delivered_legacy"}

    def outcome(self, state, wait=None, latency=None, category=None, detected=1000.0):
        columns = {"first_queued_at": None if wait is None else detected + wait}
        if state in OUTCOMES:
            columns["outcome_at"] = None if latency is None else detected + wait + latency
        return self.make(state, now=detected, category=category, **columns)

    def test_statistics_buckets_rate_and_medians(self):
        self.outcome("recovered", 10, 90)
        self.outcome("recovered", 30, 100, category="server_5xx")
        self.outcome("completed_no_progress", 20, 5)
        self.outcome("recovery_turn_failed", 40, 5)
        self.outcome("handed_over", 50, 5)
        self.outcome("stopped_by_user", 55, 5)
        self.outcome("cancelled")
        self.outcome("superseded_by_user")
        self.outcome("resumed", 60)
        waiting = self.outcome("waiting_poll")
        self.outcome("recovered", 1, 1, detected=10.0)          # before the period
        stats = self.store.statistics(since=500.0)
        self.assertEqual(stats["interruptions_detected"], 10)
        self.assertEqual(stats["continuations_submitted"], 7)
        self.assertEqual(set(stats["outcomes"]), self.BUCKETS)
        self.assertEqual(stats["outcomes"], {**{name: 0 for name in self.BUCKETS},
                                             "recovered": 2, "no_progress": 1, "recovery_failed": 1,
                                             "handed_over": 1, "stopped_by_user": 1, "cancelled": 1,
                                             "superseded": 1, "delivered_legacy": 1})
        # Four decided by the engine: not enough data for a rate.
        self.assertIsNone(stats["success_rate"])
        self.assertEqual(stats["median_wait_seconds"], 40.0)     # 10 20 30 40 50 55 60
        self.assertEqual(stats["median_recovery_seconds"], 95.0)
        self.assertEqual(stats["by_category"], {"usage_limit": 9, "server_5xx": 1})
        self.store.request_retry_now(waiting, 2000.0)
        self.store.request_retry_now(waiting, 2001.0)
        self.assertEqual(self.store.statistics(since=500.0)["retry_now_requests"], 2)

    def test_T44_a_late_receipt_counts_once(self):
        for wait in (10, 20):
            self.outcome("recovered", wait, 90)
        self.outcome("completed_no_progress", 30, 5)
        self.outcome("recovery_turn_failed", 40, 5)
        late = self.outcome("submission_unknown", 70)
        stats = self.store.statistics()
        self.assertEqual(stats["outcomes"]["submission_unknown"], 1)
        self.assertAlmostEqual(stats["success_rate"], 2 / 5)
        # The receipt arrives: the record moves to what really happened.
        self.store.update(late, at=1100.0, state="turn_started", recovery_turn_id=new_turn())
        self.store.update(late, at=1150.0, state="turn_completed")
        self.store.update(late, at=1170.0, state="recovered", outcome_at=1170.0)
        stats = self.store.statistics()
        self.assertEqual(stats["outcomes"]["submission_unknown"], 0)
        self.assertEqual(stats["outcomes"]["recovered"], 3)
        self.assertEqual(stats["interruptions_detected"], 5)
        self.assertAlmostEqual(stats["success_rate"], 3 / 5)
        self.assertEqual(stats["median_recovery_seconds"], 90.0)

    def test_statistics_exclude_user_decisions_and_legacy_rows_from_the_rate(self):
        for _ in range(5):
            self.outcome("recovered", 10, 10)
        for state in ("handed_over", "stopped_by_user", "cancelled", "superseded", "superseded_by_user",
                      "resumed"):
            self.outcome(state, 10, 10)
        self.assertEqual(self.store.statistics()["success_rate"], 1.0)
        for state in ("completed_no_progress", "recovery_turn_failed", "outcome_unverified",
                      "retry_budget_exhausted", "no_progress_exhausted", "failed", "terminal_failure",
                      "submission_unknown"):
            self.outcome(state, 10, 10)
        self.assertAlmostEqual(self.store.statistics()["success_rate"], 5 / 13)

    def test_statistics_include_hidden_rows(self):
        for _ in range(5):
            self.outcome("recovered", 10, 10)
        before = self.store.statistics()
        self.assertEqual(self.store.hide_history(10 ** 6)["hidden"], 5)
        self.assertEqual(self.store.statistics(), before)


# ============================================================================ T37
def _tagged_store(tag, folder):
    """The store module exactly as a release shipped it."""
    try:
        text = subprocess.run(["git", "-C", str(REPO), "show", "%s:src/codex_auto_resume/store.py" % tag],
                              capture_output=True, check=True, text=True, encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        # CI fetches the tags for exactly these tests; there, a missing tag is a failure.
        if os.environ.get("CI"):
            raise AssertionError("tagged store %s unavailable on CI: %s" % (tag, exc)) from None
        raise unittest.SkipTest("tagged store %s unavailable: %s" % (tag, exc))
    # v0.5.x imports its sibling relatively; the classifier's categories are unchanged.
    text = text.replace("from . import failures", "from codex_auto_resume import failures")
    name = "tagged_store_" + tag.replace(".", "_")
    path = Path(folder) / (name + ".py")
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_old_state(module, root):
    """A state written by an old release: a row in every state it knew, claimed rows
    with a pending cancel, and a conversation switched off with a record waiting on it."""
    old = module.Store(root)
    try:
        old.set_enabled(True, 100)
        v2 = module.SCHEMA_VERSION == 2
        for index, state in enumerate(sorted(module.STATES)):
            key = "old-%02d" % index
            event = failure(key, THREAD, new_turn())
            if v2 and index % 2:
                event["category"] = "server_5xx"
            old.register(event, 111.0 + index, state=state if state in module.WAITING else "waiting_reset")
            sent = 150.0 + index
            if state in ("submitting", "queued"):
                old.update(key, state=state, submitted_at=sent,
                           **({"queue_id": str(uuid.uuid4())} if state == "queued" else {}))
                old.update(key, cancel_requested=True)
            elif state in ("resumed", "submission_unknown"):
                old.update(key, state=state, submitted_at=sent, queue_id=str(uuid.uuid4()),
                           resumed_at=sent + 5 if state == "resumed" else None,
                           last_error="queue_result_unknown_do_not_resend"
                           if state == "submission_unknown" else None)
            elif state not in module.WAITING:
                old.update(key, state=state, last_error="later_turn_exists")
        old.register(failure("old-disabled", OTHER, new_turn()), 140.0, state="waiting_poll")
        old.set_thread_enabled(OTHER, False)
        # Old releases had no identity-drift check: one turn under two identities.
        twin = new_turn()
        old.register(failure("old-twin-a", THREAD, twin), 141.0, state="waiting_poll")
        drifted = dict(failure("old-twin-b", THREAD, twin), completed_at=120.0)
        old.register(drifted, 142.0, state="waiting_poll")
    finally:
        old.close()


def raw_state(path):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        version = db.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(interruptions)")}
        rows = {row["interruption_id"]: dict(row) for row in db.execute("SELECT * FROM interruptions")}
        threads = {row[0]: row[1] for row in db.execute("SELECT thread_id, enabled FROM threads")}
        events = ([dict(row) for row in db.execute("SELECT * FROM events ORDER BY event_id")]
                  if "events" in tables else [])
    return {"version": version, "tables": tables, "columns": columns, "rows": rows,
            "threads": threads, "events": events}


class MigrationTests(unittest.TestCase):
    """T37: states written by the tagged v0.3.2 (schema 1), v0.5.6 and v0.5.7
    (schema 2) releases migrate linearly to schema 3 with every row preserved."""

    TAGS = (("v0.3.2", 1), ("v0.5.6", 2), ("v0.5.7", 2))

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.modules = {tag: _tagged_store(tag, cls.folder.name) for tag, _ in cls.TAGS}
        cls.fixtures = {}
        for tag, _version in cls.TAGS:
            root = Path(cls.folder.name) / ("fixture-" + tag)
            build_old_state(cls.modules[tag], root)
            cls.fixtures[tag] = root / "state.sqlite"

    @classmethod
    def tearDownClass(cls):
        for module in cls.modules.values():
            sys.modules.pop(module.__name__, None)
        cls.folder.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = 0

    def copy(self, tag) -> Path:
        self.runs += 1
        root = Path(self.temp.name) / ("state-%03d" % self.runs)
        root.mkdir()
        shutil.copyfile(self.fixtures[tag], root / "state.sqlite")
        return root

    def test_T37_fixtures_hold_every_state_the_old_release_knew(self):
        for tag, version in self.TAGS:
            state = raw_state(self.fixtures[tag])
            with self.subTest(tag=tag):
                self.assertEqual(state["version"], version)
                states = {row["state"] for row in state["rows"].values()}
                self.assertEqual(states, set(self.modules[tag].STATES))
                if version == 2:
                    self.assertEqual(states, set(machine.V2_STATES))
                    self.assertEqual(state["columns"], set(V2_COLUMNS))
                else:
                    self.assertEqual(state["columns"], set(V2_COLUMNS[:20]), "schema 1 had 20 columns")

    def test_T37_open_without_migrate_is_refused_and_touches_nothing(self):
        for tag, _version in self.TAGS:
            root = self.copy(tag)
            before = (root / "state.sqlite").read_bytes()
            with self.subTest(tag=tag):
                with self.assertRaises(UpgradePending):
                    Store(root)
                with self.assertRaises(UpgradePending):
                    Store(root, check=False)
                self.assertEqual((root / "state.sqlite").read_bytes(), before)
                self.assertEqual(list(root.glob("state.v*-backup-*.sqlite")), [])

    def test_T37_migration_preserves_every_row_and_backfills_the_chain(self):
        for tag, version in self.TAGS:
            root = self.copy(tag)
            before = raw_state(root / "state.sqlite")
            with self.subTest(tag=tag):
                with Store(root, migrate=True) as migrated:
                    records = {row["interruption_id"]: row for row in migrated.all_records()}
                    events = migrated.events()
                after = raw_state(root / "state.sqlite")
                self.assertEqual(after["version"], 3)
                self.assertTrue(V3_COLUMNS <= after["columns"], V3_COLUMNS - after["columns"])
                self.assertTrue({"events", "watcher_status"} <= after["tables"])
                self.assertEqual(set(after["rows"]), set(before["rows"]))
                self.assertEqual(after["threads"], before["threads"])
                self.assertEqual(after["threads"][OTHER], 0, "a disabled conversation stays disabled")
                for key, old in before["rows"].items():
                    new = after["rows"][key]
                    for column, value in old.items():
                        self.assertEqual(new[column], value, "%s.%s changed" % (key, column))
                    if version == 1:
                        self.assertEqual((new["category"], new["recovery_attempts"], new["no_progress_count"]),
                                         ("usage_limit", 0, 0))
                    self.assertEqual(new["chain_origin_id"], key)
                    self.assertEqual(new["chain_first_detected_at"], old["detected_at"])
                    self.assertEqual(new["legacy"], 1 if old["state"] == "resumed" else 0)
                    self.assertEqual(new["last_claim_at"], old["submitted_at"])
                    self.assertEqual(records[key]["state"], old["state"], "no row changes state")
                    if old["state"] == "resumed":
                        self.assertEqual(machine.public_code(records[key]), "delivered_legacy")
                claimed = [row for row in after["rows"].values() if row["state"] in ("submitting", "queued")]
                self.assertTrue(claimed and all(row["cancel_requested"] == 1 for row in claimed))
                codes = [event["code"] for event in events]
                self.assertEqual(codes.count("migrated"), 1)
                self.assertEqual(codes.count("disabled_threads_with_pending"), 1)
                pending = [event for event in events if event["code"] == "disabled_threads_with_pending"]
                self.assertEqual(pending[0]["value"], 1.0)
                backups = list(root.glob("state.v*-backup-*.sqlite"))
                self.assertEqual(len(backups), 1)
                copy = raw_state(backups[0])
                self.assertEqual((copy["version"], copy["rows"]), (version, before["rows"]))
                with closing(sqlite3.connect(root / "state.sqlite")) as db:
                    indexes = {row[1]: row for row in db.execute("PRAGMA index_list(interruptions)")}
                    covering = {name: [column[2] for column in db.execute("PRAGMA index_info(%s)" % name)]
                                for name in indexes}
                by_columns = {tuple(columns): indexes[name] for name, columns in covering.items()}
                # Section 2.1: the thread+turn index is deliberately not unique (the twins
                # above migrated), and no two records may ever own one recovery turn.
                self.assertEqual(by_columns[("thread_id", "turn_id")][2], 0)
                self.assertEqual(by_columns[("recovery_turn_id",)][2], 1)
                self.assertEqual(by_columns[("recovery_turn_id",)][4], 1, "partial: NULLs are not owners")
                self.assertIn(("thread_id", "last_claim_at"), by_columns)
                self.assertIn(("chain_origin_id",), by_columns)
                # Once migrated it opens as schema 3, and never migrates twice.
                with Store(root) as reopened:
                    self.assertEqual([event["code"] for event in reopened.events()].count("migrated"), 1)
                    self.assertEqual(len(reopened.all_records()), len(before["rows"]))
                    # The twins stay; a third identity for their turn is refused as drift.
                    twin = dict(failure("new-twin", THREAD, before["rows"]["old-twin-a"]["turn_id"]),
                                completed_at=130.0)
                    self.assertFalse(reopened.register(twin, 5000.0))

    def test_T37_a_newer_schema_is_refused_as_newer_and_left_alone(self):
        root = Path(self.temp.name) / "newer"
        Store(root).close()
        with closing(sqlite3.connect(root / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=4")
            db.commit()
        before = (root / "state.sqlite").read_bytes()
        for migrate in (False, True):
            with self.subTest(migrate=migrate), self.assertRaises(StateFromNewerVersion):
                Store(root, migrate=migrate)
        self.assertEqual((root / "state.sqlite").read_bytes(), before)

    def test_T19_T37_a_crash_during_migration_leaves_the_old_schema_or_the_new(self):
        """Every step runs in one BEGIN IMMEDIATE, so a crash at any statement leaves
        schema 2 exactly as it was or schema 3 complete - never a v3 number over v2
        columns - and the next open simply migrates again."""
        real_connect = sqlite3.connect
        for tag in ("v0.3.2", "v0.5.7"):
            original = raw_state(self.fixtures[tag])
            made = []

            def counting(*args, **kwargs):
                made.append(_Crashing(real_connect(*args, **kwargs), relaxed=True))
                return made[-1]

            root = self.copy(tag)
            with mock.patch.object(store_module.sqlite3, "connect", counting):
                Store(root, migrate=True).close()
            total = made[0].calls
            self.assertGreater(total, 20)
            retried_old = False
            for position in list(range(1, total + 1)) + ["commit"]:
                with self.subTest(tag=tag, statement=position):
                    root = self.copy(tag)
                    at, after = (total, False) if position == "commit" else (position, True)

                    def crashing(*args, **kwargs):
                        return _Crashing(real_connect(*args, **kwargs), at, after, relaxed=True)

                    with mock.patch.object(store_module.sqlite3, "connect", crashing):
                        with self.assertRaises(StoreError):
                            Store(root, migrate=True)
                    found = raw_state(root / "state.sqlite")
                    if found["version"] == original["version"]:
                        self.assertEqual(found["tables"], original["tables"])
                        self.assertEqual(found["columns"], original["columns"])
                        self.assertEqual(found["rows"], original["rows"])
                        # The old state, exactly: it migrates like the fixture does, so
                        # one retry from here is enough to show nothing was left behind.
                        if retried_old:
                            continue
                        retried_old = True
                    else:
                        self.assertEqual(found["version"], 3)
                        self.assertTrue(V3_COLUMNS <= found["columns"])
                        self.assertEqual([event["code"] for event in found["events"]].count("migrated"), 1)
                    with mock.patch.object(store_module.sqlite3, "connect", counting):
                        with Store(root, migrate=True) as retried:
                            self.assertEqual(len(retried.all_records()), len(original["rows"]))
                    self.assertEqual(raw_state(root / "state.sqlite")["version"], 3)


if __name__ == "__main__":
    unittest.main()
