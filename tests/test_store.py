from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_auto_resume.store import TERMINAL, Store, StoreError


THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
OTHER = "0a1b2c3d-0003-7000-8000-000000000003"


def failure(key="a" * 64, thread_id=THREAD):
    return {
        "thread_id": thread_id, "turn_id": TURN, "completed_at": 110.0,
        "started_at": 105.0, "ordinal": 2, "interruption_id": key,
        "reset_at": 150.0, "limit_type": "codex.primary", "uncertain": True,
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "owned-state"
        self.store = Store(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)

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
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.store.reserve(key, 151)
        self.store.update(key, state="submission_unknown")
        with self.assertRaises(StoreError):
            self.store.update(key, state="waiting_retry", submitted_at=None)
        self.store.update(key, state="queued", queue_id=OTHER)
        self.store.update(key, state="resumed", resumed_at=160)
        self.assertFalse(self.store.reserve(key, 170))

    def test_proven_no_launch_can_reach_terminal_retry_limit(self):
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.store.reserve(key, 151)
        self.store.update(key, state="failed", submitted_at=None, retry_count=5,
                          last_error="queue_launch_retry_limit")
        self.assertFalse(self.store.reserve(key, 200))

    def test_cancel_only_target_thread_and_keep_sent_for_reconciliation(self):
        self.store.register(failure(), 111)
        self.store.register(failure("b" * 64, OTHER), 111)
        self.store.cancel(THREAD, 115)
        self.assertFalse(self.store.thread_enabled(THREAD))
        self.assertEqual(self.store.get("a" * 64)["state"], "cancelled")
        self.assertEqual(len(self.store.pending()), 1)
        self.store.set_enabled(True, 100)
        self.store.reserve("b" * 64, 151)
        self.store.cancel(OTHER, 152)
        self.assertEqual(self.store.get("b" * 64)["state"], "submitting")
        self.assertTrue(self.store.get("b" * 64)["cancel_requested"])

    def test_submitted_at_alone_blocks_a_second_reservation(self):
        # Defense in depth: even if a record is forced back into a WAITING state while
        # submitted_at survives, it must never be reserved again (that is a double send).
        key = "a" * 64
        self.store.register(failure(), 111)
        self.store.set_enabled(True, 100)
        self.assertTrue(self.store.reserve(key, 151))
        self.store.update(key, state="waiting_retry")      # submitted_at deliberately kept
        row = self.store.get(key)
        self.assertIsNotNone(row["submitted_at"], "precondition: the send may have happened")
        self.assertIn(row["state"], {"waiting_retry"})
        self.assertFalse(self.store.reserve(key, 200), "a possible prior send must never be repeated")

    def test_register_persists_its_schedule_in_one_transaction(self):
        event = failure()
        self.assertTrue(self.store.register(event, 111, state="waiting_poll", next_retry_at=999))
        row = self.store.get(event["interruption_id"])
        self.assertEqual(row["state"], "waiting_poll")
        self.assertEqual(row["next_retry_at"], 999)
        with self.assertRaises(StoreError):
            self.store.register(failure("b" * 64), 111, state="queued")

    def test_terminal_never_reactivated(self):
        self.store.register(failure(), 111)
        self.store.update("a" * 64, state="resumed", resumed_at=160)
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.status_counts(), {"resumed": 1})
        with self.assertRaises(StoreError):
            self.store.update("a" * 64, state="waiting_reset")

    def test_update_rejects_identity_unknown_state_and_nonfinite_time(self):
        self.store.register(failure(), 111)
        for changes in ({"thread_id": OTHER}, {"state": "anything"}, {"reset_at": float("inf")},
                        {"retry_count": -1}, {"last_error": "line1\nline2"}):
            with self.subTest(changes=changes), self.assertRaises(StoreError):
                self.store.update("a" * 64, **changes)
        self.assertEqual(self.store.get("a" * 64)["state"], "waiting_reset")

    def test_bad_fixture_rejected_without_partial_insert(self):
        for field, value in (("thread_id", "--last"), ("interruption_id", "a\nb"),
                             ("completed_at", float("nan")), ("uncertain", 2), ("ordinal", -1)):
            event = failure()
            event[field] = value
            with self.subTest(field=field), self.assertRaises(StoreError):
                self.store.register(event, 111)
        self.assertEqual(self.store.all_records(), [])

    def test_corrupt_database_fails_without_reset(self):
        self.store.close()
        (self.root / "state.sqlite").write_bytes(b"not a sqlite file")
        with self.assertRaises(StoreError):
            Store(self.root)
        self.assertEqual((self.root / "state.sqlite").read_bytes(), b"not a sqlite file")

    def test_newer_schema_and_unknown_record_state_fail_closed(self):
        self.store.register(failure(), 111)
        self.store.close()
        with closing(sqlite3.connect(self.root / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=3")     # a schema from a future version
            db.commit()
        with self.assertRaises(StoreError):
            Store(self.root)
        with closing(sqlite3.connect(self.root / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=2")
            db.execute("UPDATE interruptions SET state='unexpected'")
            db.commit()
        with self.assertRaises(StoreError):
            Store(self.root)

    def test_invalid_settings_fail_closed(self):
        self.store.close()
        with closing(sqlite3.connect(self.root / "state.sqlite")) as db:
            db.execute("UPDATE settings SET poll_seconds=0")
            db.commit()
        with self.assertRaises(StoreError):
            Store(self.root)

    def test_existing_empty_state_is_never_silently_reset(self):
        self.store.close()
        (self.root / "state.sqlite").write_bytes(b"")
        with self.assertRaises(StoreError):
            Store(self.root)
        self.assertEqual((self.root / "state.sqlite").read_bytes(), b"")


class RestoreBudgetTests(unittest.TestCase):
    """Running out of attempts is the one terminal stop a person may undo.

    `update` refuses to reactivate any terminal record, which is what keeps a finished,
    cancelled or uncertainly-submitted recovery from being restarted by a stray write.
    These tests pin the exception down to exactly the two exhausted states and assert
    that everything else stays refused, since a wider hole here would quietly re-open
    the no-resend guarantee.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "owned-state")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.key = failure()["interruption_id"]
        self.store.register(failure(), 100)

    def exhaust(self, state="retry_budget_exhausted"):
        self.store.update(self.key, state=state, recovery_attempts=4, no_progress_count=3,
                          last_error="ran out of attempts")

    def test_restores_the_two_exhausted_states(self):
        for state in ("retry_budget_exhausted", "no_progress_exhausted"):
            with self.subTest(state=state):
                if self.store.get(self.key)["state"] != "waiting_reset":
                    self.store.update(self.key, state="waiting_backoff")
                self.exhaust(state)
                self.assertTrue(self.store.restore_budget(self.key, 500))
                record = self.store.get(self.key)
                self.assertEqual(record["state"], "waiting_backoff")
                self.assertEqual(record["recovery_attempts"], 0)
                self.assertEqual(record["no_progress_count"], 0)
                self.assertIsNone(record["last_error"])
                self.assertEqual(record["next_retry_at"], 500)

    def test_refuses_every_other_terminal_state(self):
        others = sorted(TERMINAL - {"retry_budget_exhausted", "no_progress_exhausted"})
        for index, state in enumerate(others):
            with self.subTest(state=state):
                # A distinct id per state: reusing one would leave the record already
                # terminal and the setup would fail before it proved anything.
                key = "c" * 62 + "%02d" % index
                self.store.register(failure(key=key), 100)
                self.store.update(key, state="submitting", submitted_at=110.0)
                self.store.update(key, state=state)
                self.assertFalse(self.store.restore_budget(key, 500))
                self.assertEqual(self.store.get(key)["state"], state)

    def test_refuses_a_waiting_record(self):
        self.assertFalse(self.store.restore_budget(self.key, 500))

    def test_refuses_an_unknown_interruption(self):
        self.assertFalse(self.store.restore_budget("f" * 64, 500))

    def test_refuses_a_cancelled_record(self):
        self.exhaust()
        self.store.update(self.key, cancel_requested=True)
        self.assertFalse(self.store.restore_budget(self.key, 500))

    def test_never_reactivates_something_that_may_have_been_sent(self):
        # An exhausted record should not carry a submission stamp, but if one ever did,
        # restoring its budget would be a resend of an uncertain send.
        self.store.update(self.key, state="submitting", submitted_at=110.0)
        self.store.update(self.key, state="retry_budget_exhausted")
        self.assertFalse(self.store.restore_budget(self.key, 500))

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


if __name__ == "__main__":
    unittest.main()
