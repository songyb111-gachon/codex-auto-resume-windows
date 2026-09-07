"""Scheduler scenarios with a real Store and fake read-only source / transport.

Numbered tests follow the required scenario list (1-18); the remaining tests
cover crash/uncertainty handling that must never lead to a duplicate resume.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from codex_auto_resume.engine import BACKOFF_LADDER, CONTINUATION, Engine, backoff_delay
from codex_auto_resume import settings
from codex_auto_resume.store import Store

SRC = str(Path(__file__).resolve().parents[1] / "src")
T1 = "11111111-1111-7111-8111-111111111111"
T2 = "22222222-2222-7222-8222-222222222222"
TURN_A = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
TURN_B = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"
TURN_C = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
QID = "0a1b2c3d-0006-7000-8000-000000000006"
QID2 = "0a1b2c3d-0007-7000-8000-000000000007"
APP = {"pid": 10, "created": 100, "path": "app", "server": {"pid": 20, "created": 200, "path": "codex"}}
BASE = 1788628000.0          # realistic unix seconds (source.epoch bounds)
RESET = BASE + 3600.0
USAGE_ERROR = json.dumps({"codexErrorInfo": "usageLimitExceeded"})


class FakeSource:
    def __init__(self):
        self.turns: dict[str, list[dict]] = {}
        self.hints: dict[tuple, dict] = {}
        self.delivered: set[tuple] = set()
        self.queued: dict[tuple, list[str]] = {}
        self.identities: dict[str, dict] = {}
        self.raise_on_read = False

    def add_turn(self, thread_id, turn_id, status, ordinal, *, completed=None, error_json=None,
                 started=None, final_agent_item_id=None):
        row = {"thread_id": thread_id, "turn_id": turn_id, "status": status, "rollout_ordinal": ordinal,
               "started_at": BASE - 100 if started is None else started,
               "completed_at": completed, "error_json": error_json,
               "final_agent_item_id": final_agent_item_id}
        self.turns.setdefault(thread_id, []).append(row)
        return row

    def fail_usage(self, thread_id, turn_id=TURN_A, ordinal=5, *, completed=BASE, reset=RESET, limit="codex:primary_hint"):
        self.add_turn(thread_id, turn_id, "failed", ordinal, completed=completed, error_json=USAGE_ERROR)
        self.hints[(thread_id, turn_id)] = {"reset_at": reset, "limit_type": limit, "uncertain": reset is None}

    def fail_transient(self, thread_id, turn_id=TURN_A, ordinal=5, *, completed=BASE, code="serverOverloaded"):
        self.add_turn(thread_id, turn_id, "failed", ordinal, completed=completed,
                      error_json=json.dumps({"codexErrorInfo": code}))

    def progress(self, thread_id, after_ordinal):
        """Lifecycle booleans only, mirroring the real content-free reader."""
        later = [row for row in self.turns.get(thread_id, []) if row["rollout_ordinal"] > after_ordinal]
        done = [row for row in later if row["status"] == "completed"]
        return {"later_turn": bool(later), "later_completed": bool(done),
                "assistant_reply": any(row.get("final_agent_item_id") for row in done)}

    def identity(self, thread_id):
        return self.identities.get(thread_id, {"name": None, "project": None, "cwd_basename": None})

    def latest(self, thread_id):
        if self.raise_on_read:
            raise RuntimeError("history unavailable")
        rows = self.turns.get(thread_id)
        return dict(max(rows, key=lambda r: r["rollout_ordinal"])) if rows else None

    def latest_failures(self, since):
        if self.raise_on_read:
            raise RuntimeError("history unavailable")
        result = []
        for thread_id in self.turns:
            row = self.latest(thread_id)
            if row["status"] == "failed" and row["completed_at"] is not None and row["completed_at"] >= since:
                result.append(row)
        return result

    def reset_hint(self, thread_id, turn_id):
        return dict(self.hints.get((thread_id, turn_id), {"reset_at": None, "limit_type": "unknown", "uncertain": True}))

    def delivery(self, thread_id, marker):
        latest = self.latest(thread_id)
        return {"delivered": (thread_id, marker) in self.delivered,
                "queued_ids": list(self.queued.get((thread_id, marker), [])),
                "latest_turn_id": latest["turn_id"] if latest else None}


class FakeBackend:
    def __init__(self, source: FakeSource):
        self.source = source
        self.app = dict(APP)
        self.loaded_map: dict[str, str] = {}
        self.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
        self.send_calls: list[tuple[str, str]] = []
        self.outcomes: dict[str, object] = {}
        self.default_outcome = "accepted"
        self.deliver_on_accept = True
        self.deleted: list[tuple[str, str]] = []
        self.delete_result = True
        self.identity_calls = 0

    def app_identity(self):
        self.identity_calls += 1
        return dict(self.app) if self.app else None

    def loaded(self, thread_id, app_identity):
        if not app_identity or app_identity != self.app:
            return "unknown"
        return self.loaded_map.get(thread_id, "notLoaded")

    def usage(self):
        return dict(self.usage_result)

    def send(self, thread_id, prompt):
        self.send_calls.append((thread_id, prompt))
        outcome = self.outcomes.get(thread_id, self.default_outcome)
        if callable(outcome):
            outcome = outcome()
        if outcome == "accepted":
            marker = prompt.rsplit("\n", 1)[-1]
            if self.deliver_on_accept:
                self.source.delivered.add((thread_id, marker))
            else:
                self.source.queued.setdefault((thread_id, marker), []).append(QID)
            return {"outcome": "accepted", "queue_id": QID}
        if outcome == "not_started":
            return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        if outcome == "raise":
            raise OSError("transport exploded")
        return {"outcome": "unknown", "error_code": "queue_timeout"}

    def delete_queue(self, thread_id, queue_id):
        self.deleted.append((thread_id, queue_id))
        if self.delete_result:
            for key, ids in list(self.source.queued.items()):
                if key[0] == thread_id and queue_id in ids:
                    ids.remove(queue_id)
        return self.delete_result


class Harness:
    def __init__(self, root: Path, *, options=None, source=None, backend=None, notify=None):
        self.root = root
        self.now = BASE + 10.0
        self.store = Store(root)
        self.source = source or FakeSource()
        self.backend = backend or FakeBackend(self.source)
        self.logs: list[tuple] = []
        self.options = {"reset_grace_seconds": 60, "state_poll_seconds": 60, "conservative_poll_seconds": 900,
                        "delivery_timeout_seconds": 180, **(options or {})}
        self.notifications: list[tuple] = []
        self.engine = Engine(self.store, self.source, self.backend, clock=lambda: self.now,
                             log=lambda *args: self.logs.append(args), options=self.options,
                             notify=notify or (lambda *args: self.notifications.append(args)))

    def enable(self, at=None):
        self.store.set_enabled(True, self.now if at is None else at)

    def tick(self, advance=0.0):
        self.now += advance
        self.engine.tick()

    def record(self, thread_id=T1):
        rows = [row for row in self.store.all_records() if row["thread_id"] == thread_id]
        return rows[0] if rows else None

    def codes(self, thread_id=T1):
        return [entry[1] for entry in self.logs if entry[0] == thread_id]

    def close(self):
        self.store.close()


class EngineScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"
        self.h = Harness(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.h.close)
        self.h.enable()

    # -- helpers -------------------------------------------------------------
    def ready_after_reset(self, thread_id=T1, loaded=True):
        """Register a usage-limit failure and move the clock past reset + grace."""
        self.h.source.fail_usage(thread_id)
        if loaded:
            self.h.backend.loaded_map[thread_id] = "loaded"
        self.h.tick()
        self.h.now = RESET + 61

    def assert_no_send(self):
        self.assertEqual(self.h.backend.send_calls, [])

    # -- 1-4: only real usage-limit failures are ever registered ------------
    def test_01_completed_thread_no_action(self):
        self.h.source.add_turn(T1, TURN_A, "completed", 5, completed=BASE)
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    def test_02_interrupted_thread_no_action(self):
        self.h.source.add_turn(T1, TURN_A, "interrupted", 5, completed=BASE, error_json=None)
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    def test_03_ordinary_failed_thread_no_action(self):
        for error in (json.dumps({"codexErrorInfo": "other"}), json.dumps({"codexErrorInfo": "badRequest"}),
                      json.dumps({"codexErrorInfo": "unauthorized"}),
                      json.dumps({"message": "tool error"}), None):
            with self.subTest(error=error):
                self.h.source.turns.clear()
                self.h.source.add_turn(T1, TURN_A, "failed", 5, completed=BASE, error_json=error)
                self.h.tick()
                self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    def test_04_malformed_entry_no_action(self):
        bad_rows = [
            {"thread_id": "--last", "turn_id": TURN_A, "status": "failed", "rollout_ordinal": 1, "started_at": BASE, "completed_at": BASE, "error_json": USAGE_ERROR},
            {"thread_id": T1, "turn_id": TURN_A, "status": "failed", "rollout_ordinal": 1, "started_at": BASE, "completed_at": None, "error_json": USAGE_ERROR},
            {"thread_id": T1, "turn_id": TURN_A, "status": "failed", "rollout_ordinal": "1", "started_at": BASE, "completed_at": BASE, "error_json": USAGE_ERROR},
            {"thread_id": T1, "turn_id": TURN_A, "status": "unknown-state", "rollout_ordinal": 1, "started_at": BASE, "completed_at": BASE, "error_json": USAGE_ERROR},
            {"thread_id": T1, "turn_id": TURN_A, "status": "failed", "rollout_ordinal": 1, "started_at": BASE, "completed_at": BASE, "error_json": "{not json"},
            {"thread_id": T1},
            "failed usageLimitExceeded",
        ]
        for row in bad_rows:
            with self.subTest(row=row):
                self.h.source.latest_failures = lambda since, row=row: [row]
                self.h.tick()
                self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    # -- 5-6: exact thread tracking and de-duplication ----------------------
    def test_05_usage_limit_registers_exact_thread(self):
        self.h.source.fail_usage(T1)
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["thread_id"], T1)
        self.assertEqual(row["turn_id"], TURN_A)
        self.assertEqual(row["state"], "waiting_reset")
        self.assertEqual(row["reset_at"], RESET)
        self.assertEqual(row["next_retry_at"], RESET + 60)
        self.assertIn("usageLimitExceeded_detected", self.h.codes())
        self.assertIn("reset_expected", self.h.codes())
        self.assert_no_send()

    def test_06_duplicate_usage_limit_entry_registers_once(self):
        self.h.source.fail_usage(T1)
        original = self.h.source.latest_failures
        self.h.source.latest_failures = lambda since: original(since) * 2
        for _ in range(3):
            self.h.tick(advance=30)
        self.assertEqual(len(self.h.store.all_records()), 1)
        self.assertEqual(self.h.codes().count("usageLimitExceeded_detected"), 1)

    # -- 7-10: reset waiting and loaded-state gating -------------------------
    def test_07_before_reset_never_queues(self):
        self.h.source.fail_usage(T1)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        for _ in range(10):
            self.h.tick(advance=300)      # up to RESET + 50 < RESET + grace
            self.assertLess(self.h.now, RESET + 60)
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "waiting_reset")
        self.assertEqual(self.h.backend.identity_calls, 0, "no process probing while waiting for reset")

    def test_08_after_reset_and_loaded_resumes_exact_thread(self):
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        thread_id, prompt = self.h.backend.send_calls[0]
        self.assertEqual(thread_id, T1)
        self.assertTrue(prompt.startswith(CONTINUATION))
        self.assertTrue(prompt.endswith(self.h.record()["marker"]))
        self.assertEqual(self.h.record()["state"], "queued")
        self.h.tick(advance=6)
        self.assertEqual(self.h.record()["state"], "resumed")
        self.assertEqual(self.h.record()["resumed_at"], self.h.now)
        codes = self.h.codes()
        for expected in ("checking_eligibility", "loaded", "continuation_submitted", "resume_confirmed"):
            self.assertIn(expected, codes)
        self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 1, "a resumed interruption is never resent")

    def test_09_after_reset_not_loaded_waits(self):
        self.ready_after_reset(loaded=False)
        self.h.tick()
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual(row["state"], "waiting_for_loaded_thread")
        self.assertEqual(row["last_error"], "notLoaded")
        self.assertEqual(row["next_retry_at"], self.h.now + 60)
        self.assertIn((T1, "waiting_for_loaded_thread", "notLoaded"), self.h.logs)
        for _ in range(20):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(self.h.logs.count((T1, "waiting_for_loaded_thread", "notLoaded")), 1, "no log spam")

    def test_10_not_loaded_then_user_opens_thread_resumes(self):
        self.ready_after_reset(loaded=False)
        self.h.tick()
        self.h.tick(advance=60)
        self.assert_no_send()
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=30)           # next_retry_at not yet reached
        self.assert_no_send()
        self.h.tick(advance=30)
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])
        self.h.tick(advance=6)
        self.assertEqual(self.h.record()["state"], "resumed")

    # -- 11-13: app closed, global kill switch, per-thread disable ----------
    def test_11_app_closed_never_queues(self):
        self.ready_after_reset()
        self.h.backend.app = None
        for _ in range(5):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "waiting_for_app")
        self.h.backend.app = dict(APP)
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_12_global_disable_is_immediate_kill_switch(self):
        self.ready_after_reset()
        self.h.store.set_enabled(False, self.h.now)
        for _ in range(5):
            self.h.tick(advance=120)
        self.assert_no_send()
        self.assertEqual(len(self.h.store.pending()), 1, "pending state is kept while disabled")
        self.h.store.set_enabled(True, self.h.now)
        self.h.tick(advance=1)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_12b_disabled_at_failure_time_is_not_detected_later_beyond_lookback(self):
        self.h.store.set_enabled(False, self.h.now)
        self.h.source.fail_usage(T1, completed=BASE)
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        # Re-enable far beyond the lookback window: the stale failure is ignored.
        self.h.now = BASE + 7 * 3600
        self.h.store.set_enabled(True, self.h.now)
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        # Within the lookback window it is still eligible.
        self.h.store.set_enabled(False, self.h.now)
        self.h.now = BASE + 2 * 3600
        self.h.store.set_enabled(True, self.h.now)
        self.h.tick()
        self.assertEqual(len(self.h.store.all_records()), 1)

    def test_13_thread_disabled_never_queues_but_other_thread_does(self):
        self.h.source.fail_usage(T1)
        self.h.source.fail_usage(T2, TURN_B)
        self.h.backend.loaded_map.update({T1: "loaded", T2: "loaded"})
        self.h.tick()                              # both registered while enabled
        self.h.store.set_thread_enabled(T1, False)
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T2])
        self.assertEqual(self.h.record(T1)["state"], "waiting_reset", "disabled thread record untouched")
        self.h.store.set_thread_enabled(T1, True)
        self.h.tick(advance=1)
        self.assertEqual(sorted(call[0] for call in self.h.backend.send_calls), [T1, T2])

    # -- 14: restart recovery -------------------------------------------------
    def test_14_watcher_restart_preserves_pending(self):
        self.h.source.fail_usage(T1)
        self.h.tick()
        source, backend = self.h.source, self.h.backend
        self.h.close()
        restarted = Harness(self.root, source=source, backend=backend)
        self.addCleanup(restarted.close)
        restarted.now = BASE + 20
        self.assertEqual(restarted.record()["state"], "waiting_reset")
        restarted.tick()
        self.assertEqual(backend.send_calls, [])
        backend.loaded_map[T1] = "loaded"
        restarted.now = RESET + 61
        restarted.tick()
        self.assertEqual([call[0] for call in backend.send_calls], [T1])
        restarted.tick(advance=6)
        self.assertEqual(restarted.record()["state"], "resumed")

    # -- 15: bounded backoff and never-resend-on-uncertainty -----------------
    def test_15_queue_launch_failure_uses_bounded_backoff_then_gives_up(self):
        self.assertEqual([backoff_delay(i) for i in (1, 2, 3, 4, 5, 9)], [30, 60, 120, 300, 300, 300])
        self.ready_after_reset()
        self.h.backend.default_outcome = "not_started"
        expected = list(BACKOFF_LADDER)
        for retry, delay in enumerate(expected, start=1):
            self.h.tick(advance=delay if retry > 1 else 0)
            row = self.h.record()
            self.assertEqual(row["state"], "waiting_retry")
            self.assertEqual(row["retry_count"], retry)
            self.assertEqual(row["next_retry_at"], self.h.now + delay)
            self.assertIsNone(row["submitted_at"])
        self.h.tick(advance=300)
        self.assertEqual(self.h.record()["state"], "failed")
        self.assertEqual(self.h.record()["last_error"], "queue_launch_retry_limit")
        self.assertEqual(len(self.h.backend.send_calls), 5)
        for _ in range(3):
            self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 5, "terminal failure never retries")

    def test_15b_unknown_send_outcome_is_never_resent(self):
        self.ready_after_reset()
        self.h.backend.default_outcome = "unknown"
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        for _ in range(10):
            self.h.tick(advance=1800)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertNotIn(self.h.record(), self.h.store.pending())

    def test_15c_transport_exception_is_treated_as_unknown(self):
        self.ready_after_reset()
        self.h.backend.default_outcome = "raise"
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.h.tick(advance=1800)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_15d_usage_still_unavailable_does_not_queue(self):
        self.ready_after_reset()
        self.h.backend.usage_result = {"available": False, "reset_at": RESET + 1800, "limit_type": "300m", "reason": "blocked"}
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "waiting_for_usage")
        self.assertEqual(self.h.record()["next_retry_at"], RESET + 1800 + 60)
        self.h.engine._usage_cache = None
        self.h.backend.usage_result = {"available": None, "reset_at": None, "limit_type": "unknown", "reason": "probe_failed"}
        self.h.tick(advance=1900)
        self.assert_no_send()
        self.assertEqual(self.h.record()["last_error"], "usage_unknown")
        self.h.engine._usage_cache = None
        self.h.backend.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    # -- 16: single writer per interruption even with two engines -----------
    def test_16_two_engines_on_same_state_send_once(self):
        self.ready_after_reset()
        second_store = Store(self.root)
        self.addCleanup(second_store.close)
        second = Engine(second_store, self.h.source, self.h.backend, clock=lambda: self.h.now, options=self.h.options)
        gate = threading.Event()
        original_send = self.h.backend.send

        def racing_send(thread_id, prompt):
            # While the first engine is inside its dispatch section, the second engine ticks.
            if not gate.is_set():
                gate.set()
                second.tick()
            return original_send(thread_id, prompt)

        self.h.backend.send = racing_send
        self.h.tick()
        second.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.h.record()["attempt_count"], 1)

    # -- 17-18: several threads at once, isolated failure handling ----------
    def test_17_multiple_threads_pending_resume_independently(self):
        self.h.source.fail_usage(T1, reset=RESET)
        self.h.source.fail_usage(T2, TURN_B, reset=RESET + 1800)
        self.h.backend.loaded_map.update({T1: "loaded", T2: "loaded"})
        self.h.tick()
        self.assertEqual({row["thread_id"] for row in self.h.store.pending()}, {T1, T2})
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])
        self.h.tick(advance=1800)
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1, T2])
        self.h.tick(advance=6)
        self.assertEqual({row["thread_id"]: row["state"] for row in self.h.store.all_records()}, {T1: "resumed", T2: "resumed"})
        markers = {row["thread_id"]: row["marker"] for row in self.h.store.all_records()}
        for thread_id, prompt in self.h.backend.send_calls:
            self.assertTrue(prompt.endswith(markers[thread_id]), "each thread receives its own marker")

    def test_18_one_thread_failure_never_resumes_another(self):
        self.h.source.fail_usage(T1)
        self.h.source.fail_usage(T2, TURN_B)
        self.h.backend.loaded_map.update({T1: "loaded", T2: "loaded"})
        self.h.backend.outcomes[T1] = "not_started"
        self.h.tick()
        self.h.now = RESET + 61
        self.h.tick()
        calls = self.h.backend.send_calls
        self.assertEqual(sorted(call[0] for call in calls), [T1, T2])
        self.assertEqual(self.h.record(T1)["state"], "waiting_retry")
        self.h.tick(advance=6)
        self.assertEqual(self.h.record(T2)["state"], "resumed")
        # T1's retries never touch T2, and a superseded T1 never sends anywhere.
        self.h.source.add_turn(T1, TURN_C, "completed", 9, completed=self.h.now)
        self.h.tick(advance=30)
        # A later turn on that exact thread names the reason precisely.
        self.assertEqual(self.h.record(T1)["state"], "superseded_by_user")
        self.assertEqual([call[0] for call in calls[2:]], [])

    # -- extra crash / uncertainty scenarios ---------------------------------
    def test_crash_after_reserve_before_send_never_resends(self):
        self.ready_after_reset()
        self.assertTrue(self.h.store.reserve(self.h.record()["interruption_id"], self.h.now))
        self.assertEqual(self.h.record()["state"], "submitting")
        # A restarted watcher only reconciles; without a receipt it stops in submission_unknown.
        for _ in range(3):
            self.h.tick(advance=50)
        self.assertEqual(self.h.record()["state"], "submitting")
        self.h.tick(advance=100)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        for _ in range(4):
            self.h.tick(advance=1800)
        self.assert_no_send()

    def test_crash_after_send_receipt_found_later_marks_resumed(self):
        self.ready_after_reset()
        row = self.h.record()
        self.h.store.reserve(row["interruption_id"], self.h.now)
        self.h.source.delivered.add((T1, row["marker"]))
        self.h.tick(advance=5)
        self.assertEqual(self.h.record()["state"], "resumed")
        self.assert_no_send()

    def test_queued_transient_unknown_keeps_item_but_notloaded_removes_it(self):
        self.ready_after_reset()
        self.h.backend.deliver_on_accept = False
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "queued")
        # A momentary app-inventory gap is 'unknown', not 'notLoaded': the item stays.
        self.h.backend.app = None
        self.h.tick(advance=6)
        self.assertEqual(self.h.backend.deleted, [])
        self.assertEqual(self.h.record()["state"], "queued")
        # A definitive notLoaded (user unloaded the thread) removes the undelivered item.
        self.h.backend.app = dict(APP)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick(advance=6)
        self.assertEqual(self.h.backend.deleted, [(T1, QID)])
        self.assertEqual(self.h.record()["state"], "failed")
        self.assertEqual(self.h.record()["last_error"], "owned_queue_removed")
        for _ in range(3):
            self.h.tick(advance=600)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_queued_item_removed_after_delivery_timeout_even_if_unknown(self):
        self.ready_after_reset()
        self.h.backend.deliver_on_accept = False
        self.h.tick()
        self.h.backend.app = None                     # stays 'unknown' the whole time
        self.h.tick(advance=6)
        self.assertEqual(self.h.backend.deleted, [], "not yet past the delivery timeout")
        self.h.tick(advance=200)                      # now beyond delivery_timeout_seconds
        self.assertEqual(self.h.backend.deleted, [(T1, QID)])
        self.assertEqual(self.h.record()["state"], "failed")

    def test_queue_cleanup_unconfirmed_is_terminal_unknown(self):
        self.ready_after_reset()
        self.h.backend.deliver_on_accept = False
        self.h.backend.delete_result = False
        self.h.tick()
        self.h.tick(advance=200)                     # expired without receipt
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.h.tick(advance=1800)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_unknown_loaded_state_never_queues(self):
        self.ready_after_reset()
        self.h.backend.loaded_map[T1] = "unknown"
        for _ in range(5):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(self.h.record()["last_error"], "loaded_state_unknown")

    def test_cancel_pending_thread_never_queues(self):
        self.ready_after_reset()
        self.h.store.cancel(T1, self.h.now)
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "cancelled")
        self.assertEqual(self.h.store.pending(), [])

    def test_superseded_when_user_continues_manually_before_reset(self):
        self.h.source.fail_usage(T1)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        self.h.source.add_turn(T1, TURN_B, "completed", 6, completed=BASE + 100)
        self.h.now = RESET + 61
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "superseded_by_user")

    def test_thread_cooldown_and_daily_cap(self):
        self.h.engine.options.update({"thread_cooldown_seconds": 900, "max_submissions_per_thread_per_day": 2})
        self.h.source.fail_usage(T1)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        self.h.now = RESET + 61
        self.h.tick()
        self.h.tick(advance=6)
        self.assertEqual(self.h.record()["state"], "resumed")
        # The continuation turn itself fails with another usage limit: a new interruption.
        self.h.source.fail_usage(T1, TURN_B, ordinal=7, completed=self.h.now, reset=self.h.now + 60)
        self.h.tick(advance=30)
        second = [row for row in self.h.store.all_records() if row["turn_id"] == TURN_B][0]
        self.assertEqual(second["state"], "waiting_reset")
        self.h.tick(advance=200)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        second = self.h.store.get(second["interruption_id"])
        self.assertEqual(second["last_error"], "thread_submission_cooldown")
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 2)
        self.h.tick(advance=6)
        self.h.source.fail_usage(T1, TURN_C, ordinal=9, completed=self.h.now, reset=self.h.now + 60)
        self.h.tick(advance=30)
        self.h.tick(advance=1000)
        third = [row for row in self.h.store.all_records() if row["turn_id"] == TURN_C][0]
        # The cap defers (never permanently abandons a valid interruption) and does not resend.
        self.assertEqual(third["state"], "waiting_retry")
        self.assertEqual(third["last_error"], "daily_submission_cap")
        self.assertGreater(third["next_retry_at"], self.h.now)
        self.assertEqual(len(self.h.backend.send_calls), 2)

    def test_history_unavailable_never_queues_and_recovers(self):
        self.ready_after_reset()
        self.h.source.raise_on_read = True
        self.h.tick()
        self.assert_no_send()
        self.assertIn((None, "detection_unavailable_no_submission", None), self.h.logs)
        self.h.source.raise_on_read = False
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_no_reset_timestamp_uses_conservative_polling(self):
        self.h.source.fail_usage(T1, reset=None)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "waiting_poll")
        self.assertIsNone(row["reset_at"])
        self.assertEqual(row["next_retry_at"], self.h.now + 900)
        self.assertIn("reset_unknown_conservative_poll", self.h.codes())
        self.h.tick(advance=899)
        self.assert_no_send()
        self.h.tick(advance=2)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_log_entries_never_contain_prompt_text(self):
        self.ready_after_reset()
        self.h.tick()
        self.h.tick(advance=6)
        dump = repr(self.h.logs)
        self.assertNotIn(CONTINUATION[:10], dump)
        self.assertNotIn("codex-auto-resume:", dump)


class SingleInstanceTests(unittest.TestCase):
    """Real Windows named mutex / stop event: a second watcher must not run."""

    @contextmanager
    def holder(self, name):
        code = (
            "import sys, time\n"
            f"sys.path.insert(0, {SRC!r})\n"
            "from codex_auto_resume.windows import Mutex\n"
            f"with Mutex({name!r}, timeout=0):\n"
            "    print('held', flush=True)\n"
            "    time.sleep(30)\n"
        )
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "held")
            yield process
        finally:
            process.kill()
            process.wait(timeout=10)
            if process.stdout:
                process.stdout.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows named objects")
    def test_16_duplicate_watcher_process_is_refused(self):
        from codex_auto_resume import config
        from codex_auto_resume.app import EXIT_BUSY, App
        from codex_auto_resume.windows import AdapterError, Mutex
        with tempfile.TemporaryDirectory() as temp:
            paths = config.Paths(temp)
            name = str(paths.state_dir)
            with self.holder(name):
                with self.assertRaisesRegex(AdapterError, "mutex_busy"):
                    with Mutex(name, timeout=0):
                        pass
                app = App(paths, console=False)
                self.assertEqual(app.run(once=True), EXIT_BUSY)
                self.assertIs(app.watcher_running(), True)
            self.assertIs(App(paths, console=False).watcher_running(), False)
            import logging
            _logger = logging.getLogger("codex_auto_resume")
            for _handler in list(_logger.handlers):
                _logger.removeHandler(_handler)
                _handler.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows named objects")
    def test_stop_event_wakes_waiter(self):
        from codex_auto_resume.windows import StopEvent
        with StopEvent("unit-test-stop") as event:
            self.assertFalse(event.wait(0.05))
            self.assertTrue(StopEvent("unit-test-stop").signal())
            self.assertTrue(event.wait(2))
        self.assertFalse(StopEvent("unit-test-stop").signal(), "no waiter -> nothing to signal")


if __name__ == "__main__":
    unittest.main()


class PolicyTests(unittest.TestCase):
    """User-configurable policy, and the line it must not cross.

    Everything here is a preference: which categories to recover, how long to wait, how
    many attempts to allow. None of it may reach a safety property, so the last tests
    assert what policy *cannot* do as firmly as the first assert what it can.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"
        self.addCleanup(self.temp.cleanup)

    def harness(self, **kwargs):
        harness = Harness(self.root, **kwargs)
        self.addCleanup(harness.close)
        return harness

    def test_a_switched_off_category_is_never_recorded(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.source.fail_transient(T1, code="serverOverloaded")
        harness.enable()
        harness.tick()
        self.assertIsNone(harness.record(T1))
        self.assertIn("category_recovery_disabled", harness.codes(T1))

    def test_a_switched_off_category_is_logged_once_not_every_poll(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.source.fail_transient(T1, code="serverOverloaded")
        harness.enable()
        for _ in range(4):
            harness.tick()
        self.assertEqual(harness.codes(T1).count("category_recovery_disabled"), 1)

    def test_a_switched_off_category_raises_no_notification(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.source.fail_transient(T1, code="serverOverloaded")
        harness.enable()
        harness.tick()
        self.assertEqual(harness.notifications, [])

    def test_other_categories_are_unaffected(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.source.fail_usage(T1)
        harness.enable()
        harness.tick()
        self.assertIsNotNone(harness.record(T1))

    def test_a_category_with_no_switch_is_still_recovered(self):
        # Absence of a toggle is not an instruction to stop.
        harness = self.harness()
        harness.engine.apply_policy(settings.defaults())
        self.assertTrue(harness.engine.recovers("some_future_category"))

    def test_the_timing_preset_sets_the_first_transient_wait(self):
        for preset, ladder in settings.RETRY_TIMING.items():
            with self.subTest(preset=preset):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                harness = Harness(Path(temp.name) / "state")
                self.addCleanup(harness.close)
                harness.engine.apply_policy(dict(settings.defaults(), retry_timing=preset))
                harness.source.fail_transient(T1, code="serverOverloaded")
                harness.enable()
                harness.tick()
                record = harness.record(T1)
                self.assertAlmostEqual(record["next_retry_at"] - harness.now, ladder[0], places=3)

    def test_the_attempt_budget_comes_from_the_settings(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), max_recovery_attempts=1))
        self.assertEqual(harness.engine.options["max_recovery_attempts"], 1)
        harness.engine.apply_policy(dict(settings.defaults(), max_no_progress=1))
        self.assertEqual(harness.engine.options["max_no_progress"], 1)

    def test_a_corrupt_settings_mapping_yields_the_conservative_defaults(self):
        harness = self.harness()
        harness.engine.apply_policy({"max_recovery_attempts": 10 ** 9, "retry_timing": "instant",
                                     "recover_timeout": "yes please"})
        self.assertEqual(harness.engine.options["max_recovery_attempts"],
                         settings.DEFAULTS["max_recovery_attempts"])
        self.assertEqual(harness.engine.options["retry_ladder"],
                         settings.RETRY_TIMING[settings.DEFAULT_TIMING])
        self.assertTrue(harness.engine.recovers("timeout"))

    def test_policy_cannot_reach_a_safety_gate(self):
        # The engine's safety options are not in the settings schema, so no settings
        # file - hand-edited, migrated or hostile - can move them.
        harness = self.harness()
        before = {key: harness.engine.options[key] for key in
                  ("delivery_timeout_seconds", "max_queue_retries",
                   "max_submissions_per_thread_per_day", "thread_cooldown_seconds",
                   "unknown_reconcile_window_seconds", "reset_grace_seconds")}
        harness.engine.apply_policy(dict(settings.defaults(),
                                         **{key: 0 for key in settings.FIELDS if key in before}))
        for key, value in before.items():
            self.assertEqual(harness.engine.options[key], value, key)

    def test_no_setting_names_an_engine_safety_option(self):
        reserved = {"delivery_timeout_seconds", "max_queue_retries",
                    "max_submissions_per_thread_per_day", "thread_cooldown_seconds",
                    "unknown_reconcile_window_seconds", "reset_grace_seconds",
                    "conservative_poll_seconds", "state_poll_seconds"}
        self.assertEqual(set(settings.FIELDS) & reserved, set())
