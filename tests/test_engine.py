"""Scheduler scenarios against a real Store, a real Codex home and the real LocalSource.

Only the Codex *processes* are simulated (`codexsim.SimBackend`): the queue process,
the App Server's queue delete, the loaded-thread inventory, the usage probe, and the
desktop app taking the head of a thread's queue and starting a turn with it. Every
history and queue read goes through the production query layer against the tables
Codex itself writes, so a query that is wrong against the real schema fails here.

Numbered tests follow the required scenario list (1-18); the crash/uncertainty tests
after them cover what must never lead to a duplicate continuation; the `test_T..`
tests pin the v0.6 engine design (engine-design-v2 §10) at the engine level.

The lifecycle every scenario now follows: an accepted send is `queued`; when Codex
dispatches it the watch correlates the marker row's own turn (`turn_started`);
observing that turn moves it to `turn_completed`; and once `completed_at +
settle_seconds` has passed, on a later tick, it ends `recovered` (the turn produced
something) or `completed_no_progress`.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # codexsim lives next to this file

from codexsim import APP, BASE, RESET, USAGE_ERROR, CodexHome, SimBackend, new_id, transient_error  # noqa: E402
from codex_auto_resume import machine, settings  # noqa: E402
from codex_auto_resume.engine import BACKOFF_LADDER, Engine, backoff_delay  # noqa: E402
from codex_auto_resume.source import LocalSource, detect  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

SRC = str(Path(__file__).resolve().parents[1] / "src")
T1 = "11111111-1111-7111-8111-111111111111"
T2 = "22222222-2222-7222-8222-222222222222"
TURN_A = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
TURN_B = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"
TURN_C = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
DAY = 86400.0


# ------------------------------------------------------------------ Codex-side helpers
def fail_turn(home, thread_id, turn_id, *, usage=False, code="serverOverloaded", reset=None,
              error_json=None, completed=None):
    """Finish a running turn as a failure, the way Codex records one.

    A usage limit also gets the rollout events its reset hint is read from, ending
    exactly at the turn's end offset, as `CodexHome.fail_usage` does for a new turn.
    """
    completed = int(home.clock()) if completed is None else completed
    columns = {"status": "failed", "completed_at": completed}
    if usage:
        events = []
        if reset is not None:
            events.append({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                "limit_id": "codex", "primary": {"used_percent": 100, "resets_at": reset}}}})
        events.append({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id,
                                                        "error": {"codex_error_info": "usage_limit_exceeded"}}})
        columns["rollout_end_byte_offset"] = home._append(thread_id, events)
        columns["error_json"] = USAGE_ERROR
    else:
        columns["error_json"] = error_json or transient_error(code)
    home.set_turn(thread_id, turn_id, **columns)
    home.catch_up(thread_id)
    return turn_id


def dispatch_and_fail(home, thread_id, *, usage=False, progress=False, reset=None, code="serverOverloaded"):
    """Codex starts our queued continuation, and that turn fails."""
    turn = home.dispatch(thread_id, status="inProgress", progress=progress)
    if turn is None:
        raise AssertionError("nothing was queued to dispatch")
    return fail_turn(home, thread_id, turn, usage=usage, reset=reset, code=code)


def archive(home, thread_id):
    """The user archives the conversation: it stops being an eligible thread."""
    with home._db("state_5.sqlite") as db:
        db.execute("UPDATE threads SET archived=1 WHERE id=?", (thread_id,))


def drop_projection_table(home):
    with home._db("thread_history_1.sqlite") as db:
        db.execute("DROP TABLE thread_history_projection_state")


@contextmanager
def history_unavailable(home):
    """Codex's history database cannot be opened for a while (locked, moved, scanned)."""
    path = home.root / "thread_history_1.sqlite"
    aside = home.root / "thread_history_1.sqlite.aside"
    os.replace(path, aside)
    try:
        yield
    finally:
        os.replace(aside, path)


def raw_turn(home, **values):
    """Write one thread_turns row exactly as given, replacing every other row."""
    row = {"thread_id": T1, "turn_id": TURN_A, "rollout_ordinal": 1, "status": "failed",
           "error_json": USAGE_ERROR, "started_at": BASE, "completed_at": BASE}
    row.update(values)
    with home._db("thread_history_1.sqlite") as db:
        db.execute("DELETE FROM thread_turns")
        db.execute("INSERT INTO thread_turns (%s) VALUES (%s)"
                   % (",".join(row), ",".join("?" for _ in row)), tuple(row.values()))


class Harness:
    """A Store, a Codex home, the real LocalSource and a simulated backend, on one clock."""

    def __init__(self, root: Path, *, options=None, home=None, backend=None, notify=None, migrate=False):
        self.root = Path(root)
        self.now = BASE + 10.0
        self.store = Store(self.root, migrate=migrate)
        self.home = home or CodexHome(self.root / "codex-home")
        # Turns Codex finishes get realistic completion times on this clock.
        self.home.clock = lambda: self.now
        self.source = LocalSource(self.home.root)
        self.backend = backend or SimBackend(self.home)
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

    def watch(self, advance=0.0):
        """One pass of the one-second watch loop, without a full tick."""
        self.now += advance
        self.engine.watch()

    def records(self, thread_id=T1):
        return [row for row in self.store.all_records() if row["thread_id"] == thread_id]

    def record(self, thread_id=T1):
        rows = self.records(thread_id)
        return rows[0] if rows else None

    def codes(self, thread_id=T1):
        return [entry[1] for entry in self.logs if entry[0] == thread_id]

    def events(self, interruption_id):
        return [event["code"] for event in self.store.events(interruption_id)]

    def turn_ids(self, thread_id=T1):
        return [turn["turn_id"] for turn in self.home.turns(thread_id)]

    def close(self):
        self.store.close()


class EngineCase(unittest.TestCase):
    options = None

    def setUp(self):
        self.h = self.fresh()
        self.root = self.h.root

    def fresh(self, *, enable=True, **kwargs):
        """A harness of its own, for tests that need several independent runs."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        harness = Harness(Path(temp.name) / "state", options=kwargs.pop("options", self.options), **kwargs)
        self.addCleanup(harness.close)
        if enable:
            harness.enable()
        return harness

    # -- helpers -------------------------------------------------------------
    def ready_after_reset(self, h=None, thread_id=T1, turn_id=TURN_A, loaded=True):
        """Register a usage-limit failure and move the clock past reset + grace."""
        h = h or self.h
        h.home.fail_usage(thread_id, turn_id)
        if loaded:
            h.backend.loaded_map[thread_id] = "loaded"
        h.tick()
        h.now = RESET + 61

    def send_and_hold(self, h=None):
        """Send the continuation, and leave it waiting in Codex's queue."""
        h = h or self.h
        h.backend.after_accept = "queue"
        self.ready_after_reset(h)
        h.tick()
        row = h.record()
        self.assertEqual(row["state"], "queued")
        self.assertEqual(h.home.queued(T1), [row["queue_id"]])
        return row

    def follow(self, h=None):
        """Ticks enough for a dispatched, finished turn to be correlated and settled."""
        h = h or self.h
        h.tick(advance=6)
        h.tick(advance=10)

    def prompt(self, h=None):
        return (h or self.h).backend.send_calls[-1][1]

    def unknown_but_queued(self, h=None):
        """The queue process timed out, but Codex did enqueue our item."""
        h = h or self.h
        h.backend.after_accept = "queue"
        h.backend.default_outcome = "unknown"
        h.backend.on_send = lambda thread_id, prompt: h.home.enqueue(thread_id, prompt, client_id=new_id())
        self.ready_after_reset(h)
        h.tick()
        self.assertEqual(h.record()["state"], "submission_unknown")
        h.watch(advance=1)
        row = h.record()
        self.assertIsNotNone(row["queue_id"], "the watch has found our item")
        return row

    @staticmethod
    def dispatch_then_report_deleted(h):
        """U2: Codex started our item, and the delete still answers deleted:true."""
        def delete_queue(thread_id, queue_id):
            h.backend.deleted.append((thread_id, queue_id))
            h.home.dispatch(thread_id)
            return True
        h.backend.delete_queue = delete_queue

    def running(self, h=None, **kwargs):
        """Our continuation has started a turn that is still running."""
        h = h or self.h
        self.send_and_hold(h)
        turn = h.home.dispatch(T1, status="inProgress", **kwargs)
        h.tick(advance=1)
        row = h.record()
        self.assertEqual(row["state"], "turn_started")
        self.assertEqual(machine.public_code(row), "turn_running")
        return turn

    def assert_no_send(self, h=None):
        self.assertEqual((h or self.h).backend.send_calls, [])


class EngineScenarioTests(EngineCase):
    # -- 1-4: only real usage-limit failures are ever registered ------------
    def test_01_completed_thread_no_action(self):
        self.h.home.add_turn(T1, TURN_A, "completed")
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    def test_02_interrupted_thread_no_action(self):
        self.h.home.add_turn(T1, TURN_A, "interrupted", error_json=None)
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    def test_03_ordinary_failed_thread_no_action(self):
        for error in (json.dumps({"codexErrorInfo": "other"}), json.dumps({"codexErrorInfo": "badRequest"}),
                      json.dumps({"codexErrorInfo": "unauthorized"}),
                      json.dumps({"message": "tool error"}), None):
            with self.subTest(error=error):
                self.h.home.add_turn(new_id(), None, "failed", error_json=error, progress=False)
                self.h.tick()
                self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()

    def test_04_malformed_entry_no_action(self):
        self.h.home.add_thread(T1)
        # The control row is well formed and is detected, so every refusal below is
        # the malformation's doing and not a broken fixture.
        raw_turn(self.h.home)
        self.assertEqual(len(self.h.source.latest_failures(BASE - 3600)), 1)
        bad_rows = [
            {"thread_id": "--last"},
            {"completed_at": None},
            {"rollout_ordinal": "one"},
            {"status": "unknown-state"},
            {"error_json": "{not json"},
            {"started_at": BASE + 50},          # completed before it started
        ]
        for values in bad_rows:
            with self.subTest(row=values):
                raw_turn(self.h.home, **values)
                self.h.tick()
                self.assertEqual(self.h.store.all_records(), [])
        # Shapes that cannot even be stored in the table are refused by detection itself.
        for row in ({"thread_id": T1}, "failed usageLimitExceeded", None):
            with self.subTest(row=row):
                self.assertIsNone(detect(row))
        self.assert_no_send()

    # -- 5-6: exact thread tracking and de-duplication ----------------------
    def test_05_usage_limit_registers_exact_thread(self):
        self.h.home.fail_usage(T1, TURN_A)
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
        self.h.home.fail_usage(T1, TURN_A)
        original = self.h.source.latest_failures
        # The same failure reported twice in one read, and again on every poll.
        self.h.source.latest_failures = lambda since: original(since) * 2
        for _ in range(3):
            self.h.tick(advance=30)
        self.assertEqual(len(self.h.store.all_records()), 1)
        self.assertEqual(self.h.codes().count("usageLimitExceeded_detected"), 1)

    # -- 7-10: reset waiting and loaded-state gating -------------------------
    def test_07_before_reset_never_queues(self):
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        for _ in range(10):
            self.h.tick(advance=300)      # up to RESET + 10 < RESET + grace
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
        row = self.h.record()
        self.assertTrue(prompt.endswith(row["marker"]))
        self.assertEqual(row["state"], "queued")
        self.assertEqual(machine.public_code(row), "submitted")
        ours = self.h.turn_ids()[-1]                 # the desktop app ran it at once
        self.h.tick(advance=6)
        row = self.h.record()
        self.assertIn(row["state"], machine.OBSERVING)
        self.assertEqual(row["recovery_turn_id"], ours)
        self.assertEqual(row["resumed_at"], self.h.now)
        self.assertEqual(row["turn_started_at"], self.h.now)
        self.h.tick(advance=10)
        row = self.h.record()
        self.assertEqual(row["state"], "recovered")
        self.assertEqual(machine.public_code(row), "recovered")
        codes = self.h.codes()
        for expected in ("checking_eligibility", "loaded", "continuation_submitted", "turn_started", "recovered"):
            self.assertIn(expected, codes)
        self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 1, "a recovered interruption is never resent")

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
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.assertEqual(len(self.h.backend.send_calls), 1)

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
        self.h.home.fail_usage(T1, TURN_A, completed=BASE)
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
        self.h.home.fail_usage(T1, TURN_A)
        self.h.home.fail_usage(T2, TURN_B)
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
        self.h.home.fail_usage(T1, TURN_A)
        self.h.tick()
        home, backend = self.h.home, self.h.backend
        self.h.close()
        restarted = Harness(self.root, home=home, backend=backend)
        self.addCleanup(restarted.close)
        restarted.now = BASE + 20
        self.assertEqual(restarted.record()["state"], "waiting_reset")
        restarted.tick()
        self.assertEqual(backend.send_calls, [])
        backend.loaded_map[T1] = "loaded"
        restarted.now = RESET + 61
        restarted.tick()
        self.assertEqual([call[0] for call in backend.send_calls], [T1])
        self.follow(restarted)
        self.assertEqual(restarted.record()["state"], "recovered")
        self.assertEqual(len(backend.send_calls), 1)

    # -- 15: bounded backoff and never-resend-on-uncertainty -----------------
    def test_15_queue_launch_failure_uses_bounded_backoff_then_gives_up(self):
        self.assertEqual([backoff_delay(i) for i in (1, 2, 3, 4, 5, 9)], [30, 60, 120, 300, 300, 300])
        # The ladder itself is what is under test here, so the per-thread cooldown
        # (which a released claim also counts, see test_15e) is taken out of the way.
        self.h.engine.options["thread_cooldown_seconds"] = 0
        self.ready_after_reset()
        self.h.backend.default_outcome = "not_started"
        for retry, delay in enumerate(BACKOFF_LADDER, start=1):
            self.h.tick(advance=delay if retry > 1 else 0)
            row = self.h.record()
            self.assertEqual(row["state"], "waiting_retry")
            self.assertEqual(row["retry_count"], retry)
            self.assertEqual(row["next_retry_at"], self.h.now + delay)
            self.assertIsNone(row["submitted_at"])
            self.assertEqual(machine.public_code(row), "failed_retryable")
        self.h.tick(advance=300)
        row = self.h.record()
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["last_error"], "queue_launch_retry_limit")
        self.assertEqual(machine.public_code(row), "failed_terminal")
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

    def test_15e_a_launch_retry_still_respects_the_thread_cooldown(self):
        """§2.1: the cooldown counts coalesce(submitted_at, last_claim_at), so a claim
        whose process never started still counts - the cap bounds how often we try."""
        self.ready_after_reset()
        self.h.backend.default_outcome = "not_started"
        self.h.tick()
        claimed_at = self.h.record()["last_claim_at"]
        self.assertEqual(claimed_at, self.h.now)
        self.h.tick(advance=30)                  # the launch backoff is over...
        row = self.h.record()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(row["last_error"], "thread_submission_cooldown")   # ...the cooldown is not
        self.assertEqual(row["last_claim_at"], claimed_at)
        self.h.tick(advance=900)
        self.assertEqual(len(self.h.backend.send_calls), 2)

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
        self.h.home.fail_usage(T1, TURN_A, reset=RESET)
        self.h.home.fail_usage(T2, TURN_B, reset=RESET + 1800)
        self.h.backend.loaded_map.update({T1: "loaded", T2: "loaded"})
        self.h.tick()
        self.assertEqual({row["thread_id"] for row in self.h.store.pending()}, {T1, T2})
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])
        self.h.tick(advance=1800)
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1, T2])
        self.follow()
        self.assertEqual({row["thread_id"]: row["state"] for row in self.h.store.all_records()},
                         {T1: "recovered", T2: "recovered"})
        markers = {row["thread_id"]: row["marker"] for row in self.h.store.all_records()}
        for thread_id, prompt in self.h.backend.send_calls:
            self.assertTrue(prompt.endswith(markers[thread_id]), "each thread receives its own marker")
        turns = {row["thread_id"]: row["recovery_turn_id"] for row in self.h.store.all_records()}
        self.assertEqual(turns[T1], self.h.turn_ids(T1)[-1])
        self.assertEqual(turns[T2], self.h.turn_ids(T2)[-1])

    def test_18_one_thread_failure_never_resumes_another(self):
        self.h.home.fail_usage(T1, TURN_A)
        self.h.home.fail_usage(T2, TURN_B)
        self.h.backend.loaded_map.update({T1: "loaded", T2: "loaded"})
        self.h.backend.outcomes[T1] = "not_started"
        self.h.tick()
        self.h.now = RESET + 61
        self.h.tick()
        calls = self.h.backend.send_calls
        self.assertEqual(sorted(call[0] for call in calls), [T1, T2])
        self.assertEqual(self.h.record(T1)["state"], "waiting_retry")
        self.follow()
        self.assertEqual(self.h.record(T2)["state"], "recovered")
        self.assertEqual(self.h.home.turns(T1)[-1]["turn_id"], TURN_A, "nothing ran on T1")
        # T1's retries never touch T2, and a superseded T1 never sends anywhere.
        self.h.home.add_turn(T1, TURN_C, "completed")
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

    def test_crash_after_send_receipt_found_later_is_followed_to_its_outcome(self):
        self.ready_after_reset()
        row = self.h.record()
        self.h.store.reserve(row["interruption_id"], self.h.now)
        # The send reached Codex before the crash, and Codex ran it.
        self.h.home.enqueue(T1, "(continuation)\n\n" + row["marker"])
        ours = self.h.home.dispatch(T1)
        self.h.tick(advance=5)
        row = self.h.record()
        self.assertIn(row["state"], machine.OBSERVING)
        self.assertEqual(row["recovery_turn_id"], ours)
        self.h.tick(advance=10)
        self.assertEqual(self.h.record()["state"], "recovered")
        self.assert_no_send()

    def test_queued_transient_unknown_keeps_item_but_notloaded_withdraws_it(self):
        row = self.send_and_hold()
        # A momentary app-inventory gap is 'unknown', not 'notLoaded': the item stays.
        self.h.backend.app = None
        self.h.tick(advance=6)
        self.assertEqual(self.h.backend.deleted, [])
        self.assertEqual(self.h.record()["state"], "queued")
        # A definitive notLoaded (user unloaded the thread) takes the undelivered item back...
        self.h.backend.app = dict(APP)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick(advance=6)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        withdrawn = self.h.record()
        self.assertEqual(withdrawn["state"], "withdrawn_unconfirmed")
        self.assertEqual(withdrawn["withdraw_reason"], "not_loaded")
        self.assertTrue(withdrawn["withdraw_deleted"])
        self.assertEqual(machine.public_code(withdrawn), "withdrawing")
        # ...but a delete is not proof nothing ran: only once the delivery window has
        # passed with no marker and a current history does it end as failed.
        self.h.tick(advance=170)
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")
        self.h.tick(advance=11)
        self.assertEqual(self.h.record()["state"], "failed")
        self.assertEqual(machine.public_code(self.h.record()), "failed_terminal")
        for _ in range(3):
            self.h.tick(advance=600)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_queued_item_withdrawn_after_delivery_timeout_even_if_unknown(self):
        row = self.send_and_hold()
        self.h.backend.app = None                     # stays 'unknown' the whole time
        self.h.tick(advance=6)
        self.assertEqual(self.h.backend.deleted, [], "not yet past the delivery timeout")
        self.h.tick(advance=200)                      # now beyond delivery_timeout_seconds
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")
        self.assertEqual(self.h.record()["withdraw_reason"], "expired")
        self.h.tick(advance=181)
        self.assertEqual(self.h.record()["state"], "failed")
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_queue_cleanup_unconfirmed_is_terminal_unknown(self):
        self.send_and_hold()
        self.h.backend.delete_result = False          # Codex keeps refusing the delete
        self.h.tick(advance=200)                      # expired without receipt
        # Each delete starts a Codex process, so a failed one is tried again only after
        # delete_retry_seconds.
        for _ in range(4):
            self.h.tick(advance=self.h.engine.options["delete_retry_seconds"])
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "queue_cleanup_unconfirmed")
        self.assertEqual(len(self.h.backend.deleted), 5)
        self.h.tick(advance=1800)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
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
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        self.h.home.add_turn(T1, TURN_B, "completed", completed=BASE + 100)
        self.h.now = RESET + 61
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "superseded_by_user")

    def test_thread_cooldown_and_daily_cap(self):
        self.h.engine.options.update({"thread_cooldown_seconds": 900, "max_submissions_per_thread_per_day": 2})
        self.h.backend.after_accept = "queue"
        self.ready_after_reset()
        self.h.tick()
        first = self.h.record()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        # The continuation turn itself fails with another usage limit: the same task,
        # so a new record in the same chain.
        dispatch_and_fail(self.h.home, T1, usage=True, progress=True, reset=self.h.now + 60)
        self.h.tick(advance=30)
        second = self.h.records()[1]
        self.assertEqual(second["state"], "waiting_reset")
        self.assertEqual(second["parent_interruption_id"], first["interruption_id"])
        self.assertEqual(second["chain_origin_id"], first["interruption_id"])
        self.h.tick(advance=200)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        second = self.h.store.get(second["interruption_id"])
        self.assertEqual(second["last_error"], "thread_submission_cooldown")
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 2)
        dispatch_and_fail(self.h.home, T1, usage=True, progress=True, reset=self.h.now + 60)
        self.h.tick(advance=30)
        self.h.tick(advance=1000)
        third = self.h.records()[2]
        # The cap defers (never permanently abandons a valid interruption) and does not resend.
        self.assertEqual(third["state"], "waiting_retry")
        self.assertEqual(third["last_error"], "daily_submission_cap")
        self.assertGreater(third["next_retry_at"], self.h.now)
        self.assertEqual(len(self.h.backend.send_calls), 2)

    def test_history_unavailable_never_queues_and_recovers(self):
        self.ready_after_reset()
        with history_unavailable(self.h.home):
            self.h.tick()
            self.assert_no_send()
            self.assertIn((None, "detection_unavailable_no_submission", None), self.h.logs)
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_no_reset_timestamp_uses_conservative_polling(self):
        self.h.home.fail_usage(T1, TURN_A, reset=None)
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
        self.follow()
        # Whatever the continuation says, none of it - and not the marker - is logged.
        body = self.prompt().rsplit(self.h.record()["marker"], 1)[0].strip()
        self.assertTrue(body)
        dumps = (repr(self.h.logs), repr(self.h.notifications))
        for dump in dumps:
            self.assertNotIn(body[:24], dump)
            self.assertNotIn("codex-auto-resume:", dump)


class CorrelationTests(EngineCase):
    """§4.1 and §5: the engine follows its own continuation, not the thread."""

    def test_T01_the_recovery_turn_is_the_marker_rows_turn_not_the_latest(self):
        self.send_and_hold()
        ours = self.h.home.dispatch(T1)
        theirs = self.h.home.add_turn(T1)             # the user starts another turn before we look
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["recovery_turn_id"], ours)
        self.assertNotEqual(ours, theirs)
        self.h.tick(advance=10)
        self.assertEqual(self.h.record()["recovery_turn_id"], ours)

    def test_T01_the_recovery_turn_survives_a_watcher_restart(self):
        self.send_and_hold()
        ours = self.h.home.dispatch(T1)
        self.h.home.add_turn(T1)
        home, backend = self.h.home, self.h.backend
        self.h.close()
        restarted = Harness(self.root, home=home, backend=backend)
        self.addCleanup(restarted.close)
        restarted.now = self.h.now + 30
        restarted.tick()
        self.assertEqual(restarted.record()["recovery_turn_id"], ours)

    def test_T01_latest_turn_id_is_gone_from_the_source(self):
        for path in Path(SRC).rglob("*.py"):
            self.assertNotIn("latest_turn_id", path.read_text(encoding="utf-8"), str(path))

    def test_T02a_two_marker_rows_are_never_correlated(self):
        queue_id = self.send_and_hold()["queue_id"]
        prompt = self.prompt()
        self.h.home.add_turn(T1, user_text=prompt)
        self.h.home.add_turn(T1, user_text=prompt)
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "duplicate_marker")
        self.assertIsNone(row["recovery_turn_id"])
        # Our own queued item is still taken back.
        self.assertIn((T1, queue_id), self.h.backend.deleted)
        self.assertEqual(self.h.home.queued(T1), [])

    def test_T02b_marker_steered_into_someone_elses_turn_is_handed_over(self):
        row = self.send_and_hold()
        theirs = self.h.home.add_turn(T1, status="inProgress", user_text="their own message")
        self.h.home.remove_queued(row["queue_id"])
        self.h.home.add_item(T1, theirs, "userMessage", self.prompt())
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "handed_over")
        self.assertEqual(row["last_error"], "marker_not_turn_initiator")
        self.assertTrue(row["user_joined"])
        self.assertEqual(row["recovery_turn_id"], theirs, "lineage must know the turn is not ours to recover")

    def _held_with_client_id(self):
        row = self.send_and_hold()
        self.h.tick(advance=1)                        # the watch reads our item's client id
        row = self.h.record()
        self.assertIsNotNone(row["recovery_client_id"])
        self.h.home.remove_queued(row["queue_id"])
        return row

    def test_T02c_a_different_client_id_is_ambiguous(self):
        self._held_with_client_id()
        self.h.home.add_turn(T1, user_text=self.prompt(), client_id="someone-else-0001")
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "ambiguous_receipt")
        self.assertIsNone(row["recovery_turn_id"])

    def test_T02d_a_null_client_id_falls_back_to_the_marker_rules(self):
        self._held_with_client_id()
        ours = self.h.home.add_turn(T1, user_text=self.prompt(), client_id=None)
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertIn(row["state"], machine.OBSERVING)
        self.assertEqual(row["recovery_turn_id"], ours)

    def test_T02e_a_marker_at_or_before_the_failed_turn_is_ambiguous(self):
        row = self.send_and_hold()
        self.h.home.remove_queued(row["queue_id"])
        self.h.home.add_turn(T1, ordinal=4, user_text=self.prompt())
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "ambiguous_receipt")

    def test_T03_an_undetermined_turn_never_triggers_a_delete(self):
        row = self.send_and_hold()
        running = self.h.home.add_turn(T1, status="inProgress", user_text=None)
        for advance in (1, 1, 5, 30, 60, 200, 400):   # inside and well past the delivery timeout
            self.h.tick(advance=advance)
            self.assertEqual(self.h.backend.deleted, [])
            self.assertEqual(self.h.record()["state"], "queued")
        self.assertEqual(self.h.home.queued(T1), [row["queue_id"]])
        # Once that turn is known to be someone else's, the item is taken back.
        item = self.h.home.add_item(T1, running, "userMessage", "their own message")
        self.h.home.set_turn(T1, running, first_user_item_id=item)
        self.h.tick(advance=1)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.assertEqual(self.h.record()["withdraw_reason"], "superseded_by_user")

    def test_T04_a_marker_after_a_successful_delete_is_followed_not_superseded(self):
        triggers = {
            "superseded_by_user": (lambda h: h.home.add_turn(T1), 1, True),
            "not_loaded": (lambda h: h.backend.loaded_map.__setitem__(T1, "notLoaded"), 6, False),
            "expired": (lambda h: None, 181, False),
            "cancel": (lambda h: h.store.cancel_interruption(h.record()["interruption_id"], h.now), 1, False),
            "superseded": (lambda h: archive(h.home, T1), 1, True),
        }
        for reason, (trigger, advance, after_user) in triggers.items():
            with self.subTest(trigger=reason):
                h = self.fresh()
                self.send_and_hold(h)
                key = h.record()["interruption_id"]
                self.dispatch_then_report_deleted(h)
                trigger(h)
                h.tick(advance=advance)
                row = h.record()
                self.assertEqual(row["state"], "withdrawn_unconfirmed")
                self.assertEqual(row["withdraw_reason"], reason)
                self.assertTrue(row["withdraw_deleted"])
                ours = h.turn_ids()[-1]
                h.tick(advance=1)
                row = h.record()
                self.assertIn(row["state"], machine.OBSERVING)
                self.assertEqual(row["recovery_turn_id"], ours)
                self.assertIn("dispatched_despite_delete", h.events(key))
                # §5.4: after_user_work is set for the supersede reasons only.
                self.assertEqual(row["after_user_work"], after_user)
                h.tick(advance=10)
                self.assertNotEqual(h.record()["state"], "superseded_by_user")
                self.assertEqual(h.record()["state"], "recovered")
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_T05_a_withdrawal_that_nothing_followed_settles_per_reason(self):
        cases = {
            "cancel": (lambda h: h.store.cancel_interruption(h.record()["interruption_id"], h.now), 1, "cancelled"),
            "thread_disabled": (lambda h: h.store.set_thread_enabled(T1, False), 1, "cancelled"),
            "superseded_by_user": (lambda h: h.home.add_turn(T1), 1, "superseded_by_user"),
            "user_queued_input": (lambda h: h.home.enqueue(T1, "their own queued message"), 1, "superseded_by_user"),
            "superseded": (lambda h: archive(h.home, T1), 1, "superseded"),
            "not_loaded": (lambda h: h.backend.loaded_map.__setitem__(T1, "notLoaded"), 6, "failed"),
            "expired": (lambda h: None, 181, "failed"),
            "duplicate_owner": (lambda h: h.home.enqueue(T1, "(copy)\n\n" + h.record()["marker"]), 1, "superseded"),
        }
        for reason, (trigger, advance, final) in cases.items():
            with self.subTest(reason=reason):
                h = self.fresh()
                self.send_and_hold(h)
                trigger(h)
                h.tick(advance=advance)
                row = h.record()
                self.assertEqual(row["state"], "withdrawn_unconfirmed")
                self.assertEqual(row["withdraw_reason"], reason)
                h.tick(advance=100)
                self.assertEqual(h.record()["state"], "withdrawn_unconfirmed", "the window is not over")
                h.tick(advance=81)
                row = h.record()
                self.assertEqual(row["state"], final)
                if final == "failed":
                    self.assertEqual(machine.public_code(row), "failed_terminal")
                if reason == "duplicate_owner":
                    self.assertEqual(row["last_error"], "duplicate_owner")
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_T05_a_withdrawal_settled_over_a_stale_history_stays_unknown(self):
        self.send_and_hold()
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick(advance=6)
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")
        # Codex's history stops following its file right after the withdrawal, so a
        # dispatch of our item may simply not be visible yet.
        self.h.home.make_stale(T1)
        for _ in range(7):
            self.h.tick(advance=30)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "withdraw_unconfirmed")
        self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_T06_an_unknown_record_that_owns_a_queue_row_is_watched_whatever_its_schedule(self):
        row = self.unknown_but_queued()
        self.h.store.update(row["interruption_id"], at=self.h.now, next_retry_at=self.h.now + 900)
        self.h.home.add_turn(T1)                          # the user starts working
        self.h.watch(advance=1)
        self.h.watch(advance=1)
        self.assertIn((T1, row["queue_id"]), self.h.backend.deleted, "withdrawn within 2 s")
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")

    def test_T06_an_owned_queue_row_older_than_a_day_is_still_watched(self):
        row = self.unknown_but_queued()
        self.h.now += 25 * 3600
        self.h.home.add_turn(T1)
        self.h.watch(advance=1)
        self.assertIn((T1, row["queue_id"]), self.h.backend.deleted)

    def test_T07_a_turn_that_appears_during_the_send_is_seen_by_the_watch(self):
        self.h.backend.after_accept = "queue"
        self.h.backend.on_send = lambda thread_id, prompt: self.h.home.add_turn(thread_id)
        self.ready_after_reset()
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "queued")
        self.h.watch(advance=1)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.assertEqual(self.h.record()["withdraw_reason"], "superseded_by_user")

    def test_T08_a_change_between_claim_and_send_releases_the_claim(self):
        cases = {
            "cancel": (lambda h: h.store.cancel_interruption(h.record()["interruption_id"], h.now),
                       {"cancelled"}),
            "pause": (lambda h: h.store.set_enabled(False, h.now), machine.WAITING),
            "thread_disabled": (lambda h: h.store.set_thread_enabled(T1, False), machine.WAITING),
            "invalidated": (lambda h: h.home.add_turn(T1), {"superseded_by_user"}),
        }
        for name, (inject, targets) in cases.items():
            with self.subTest(change=name):
                h = self.fresh()
                self.ready_after_reset(h)
                original = h.store.reserve_detailed

                def claim_then_change(*args, _h=h, _inject=inject, _original=original, **kwargs):
                    result = _original(*args, **kwargs)
                    if result[0]:
                        _inject(_h)
                    return result

                h.store.reserve_detailed = claim_then_change
                h.tick()
                row = h.record()
                self.assertEqual(h.backend.send_calls, [])
                self.assertIn(row["state"], targets)
                self.assertEqual(row["retry_count"], 0)
                self.assertIsNone(row["submitted_at"])
                self.assertEqual(row["last_claim_at"], h.now)
                self.assertIn("release_claim", h.events(row["interruption_id"]))
                self.assertEqual([event for event, _detail in h.notifications], ["interruption"],
                                 "no toast before a send")

    def test_T09_foreign_queued_input_waits_before_the_send(self):
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        self.h.home.enqueue(T1, "their own queued message")
        self.h.now = RESET + 61
        self.h.tick()
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual(row["last_error"], "user_input_queued")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["no_newer_user_work"],
                         ("WAIT", "user_input_queued"))

    def test_T09_foreign_input_queued_behind_ours_takes_ours_back(self):
        row = self.send_and_hold()
        self.h.home.enqueue(T1, "their own queued message")
        self.h.tick(advance=1)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.assertEqual(self.h.record()["withdraw_reason"], "user_queued_input")
        self.h.tick(advance=181)
        self.assertEqual(self.h.record()["state"], "superseded_by_user")

    def test_T10_an_edited_queue_item_is_handed_over_without_a_delete(self):
        row = self.send_and_hold()
        self.h.home.edit_queued(row["queue_id"], "the user rewrote this")
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "handed_over")
        self.assertEqual(row["last_error"], "queued_item_edited")
        self.assertEqual(self.h.backend.deleted, [])
        self.assertEqual(self.h.home.queued(T1), [row["queue_id"]])

    def test_T45_a_marker_already_in_codex_releases_the_claim_as_a_duplicate_owner(self):
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        # Another installation derived the same marker and got there first.
        self.h.home.enqueue(T1, "(another engine)\n\n" + self.h.record()["marker"])
        self.h.now = RESET + 61
        self.h.tick()
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual(row["state"], "superseded")
        self.assertEqual(row["last_error"], "duplicate_owner")

    def test_T46_an_error_after_the_send_is_not_logged_as_no_submission(self):
        self.h.backend.after_accept = "queue"
        original = self.h.backend.send

        def send(thread_id, prompt):
            original(thread_id, prompt)
            return {"outcome": "accepted", "queue_id": "not-a-queue-id"}

        self.h.backend.send = send
        self.ready_after_reset()
        self.h.tick()
        self.assertIn("post_send_bookkeeping_failed", self.h.codes())
        self.assertNotIn("eligibility_check_failed_no_submission", self.h.codes())
        self.assertEqual(self.h.record()["state"], "submitting")
        # The watch resolves it from what is really in Codex's queue.
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "queued")
        self.assertEqual(self.h.home.queued(T1), [row["queue_id"]])
        self.assertEqual(len(self.h.backend.send_calls), 1)


class OutcomeTests(EngineCase):
    """§4.2-§4.3: what the recovery turn did, read from that turn alone."""

    def test_T13_a_turn_that_never_finishes_is_unverified_at_the_deadline(self):
        self.running()
        self.h.tick(advance=23 * 3600)
        self.assertEqual(self.h.record()["state"], "turn_started")
        self.h.tick(advance=3600)
        row = self.h.record()
        self.assertEqual(row["state"], "outcome_unverified")
        self.assertEqual(row["last_error"], "outcome_deadline")

    def test_T13_a_later_finished_turn_proves_the_row_is_stale(self):
        self.running()
        self.h.home.add_turn(T1)
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "outcome_unverified")
        self.assertEqual(row["last_error"], "stale_turn_row")

    def test_T13_an_interrupted_turn_was_stopped_by_the_user(self):
        turn = self.running()
        self.h.home.set_turn(T1, turn, status="interrupted", completed_at=int(self.h.now))
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["state"], "turn_completed")
        self.h.tick(advance=10)
        row = self.h.record()
        self.assertEqual(row["state"], "stopped_by_user")
        self.assertEqual(machine.public_code(row), "stopped_by_user")

    def test_T13_an_unknown_turn_status_is_unverified(self):
        turn = self.running()
        self.h.home.set_turn(T1, turn, status="somethingCodexAddedLater", completed_at=int(self.h.now))
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual(row["state"], "outcome_unverified")
        self.assertEqual(row["last_error"], "unknown_turn_status")

    def test_T13_an_unreadable_history_is_retried_until_the_deadline(self):
        self.running()
        with history_unavailable(self.h.home):
            self.h.tick(advance=3600)
            self.assertEqual(self.h.record()["state"], "turn_started", "unknown is never 'no progress'")
            self.h.tick(advance=23 * 3600)
            row = self.h.record()
        self.assertEqual(row["state"], "outcome_unverified")
        self.assertEqual(row["last_error"], "outcome_deadline")

    def test_T14_items_projected_after_completion_are_counted(self):
        self.send_and_hold()
        ours = self.h.home.dispatch(T1, progress=False)       # completed, agent item not projected yet
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["state"], "turn_completed")
        self.h.home.add_item(T1, ours, "agentMessage")
        self.h.tick(advance=5)
        self.assertEqual(self.h.record()["state"], "turn_completed", "still inside completed_at + 10 s")
        self.h.tick(advance=5)
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_T14_a_turn_first_seen_long_after_it_finished_still_waits_one_tick(self):
        self.send_and_hold()
        self.h.home.dispatch(T1, completed=int(self.h.now) - 30)
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["state"], "turn_completed")
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_T15_a_turn_that_produced_nothing_is_no_progress(self):
        self.send_and_hold()
        self.h.home.dispatch(T1, progress=False)
        self.follow()
        row = self.h.record()
        self.assertEqual(row["state"], "completed_no_progress")
        self.assertEqual(machine.public_code(row), "no_progress")
        outcomes = self.h.store.statistics()["outcomes"]
        self.assertEqual(outcomes["no_progress"], 1)
        self.assertEqual(outcomes["recovered"], 0)

    def test_T16_a_person_joining_the_turn_hands_it_over_and_blocks_its_child(self):
        for client_id in (None, "desktop-client-7"):
            with self.subTest(client_id=client_id):
                h = self.fresh()
                self.send_and_hold(h)
                turn = h.home.dispatch(T1, status="inProgress")
                h.home.add_item(T1, turn, "userMessage", "and also this", client_id)
                h.tick(advance=1)
                parent = h.record()
                self.assertEqual(parent["state"], "handed_over")
                self.assertEqual(parent["last_error"], "user_joined")
                self.assertTrue(parent["user_joined"])
                # That turn then fails: it is the person's work now, not ours to recover.
                fail_turn(h.home, T1, turn)
                h.tick(advance=1)
                child = h.records()[1]
                self.assertEqual(child["parent_interruption_id"], parent["interruption_id"])
                self.assertEqual(child["state"], "superseded")
                self.assertEqual(child["last_error"], "parent_handed_over")
                self.assertIsNone(child["last_claim_at"])
                for _ in range(3):
                    h.tick(advance=3600)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_T17_a_stuck_observed_record_does_not_block_a_newer_failure(self):
        self.running()
        # Codex crashed mid-turn: that row stays inProgress forever. The user carries on
        # in a turn of their own, which fails with a transient error.
        self.h.home.fail_transient(T1, completed=int(self.h.now))
        self.h.tick(advance=1)
        first, second = self.h.records()
        self.assertEqual(first["state"], "outcome_unverified")
        self.assertEqual(first["last_error"], "stale_turn_row")
        self.assertIsNone(second["parent_interruption_id"], "the user's turn is not our continuation")
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 2)
        self.assertEqual(self.h.store.get(second["interruption_id"])["state"], "queued")

    def test_T48_a_late_delivery_after_an_unknown_result_is_announced(self):
        self.h.backend.after_accept = "queue"
        self.h.backend.default_outcome = "unknown"
        self.h.backend.on_send = lambda thread_id, prompt: self.h.home.enqueue(thread_id, prompt)
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.h.home.dispatch(T1)
        self.h.tick(advance=1)
        announced = [(event, detail.get("state")) for event, detail in self.h.notifications]
        self.assertIn(("result", "submission_unknown"), announced)
        self.assertIn(("result", "turn_started"), announced)
        self.assertLess(announced.index(("result", "submission_unknown")),
                        announced.index(("result", "turn_started")))


class PauseAndCancelTests(EngineCase):
    """§7.1-§7.2: Pause and Cancel reach a continuation that is already in Codex."""

    def test_T21_cancel_of_an_unknown_record_that_is_still_queued(self):
        row = self.unknown_but_queued()
        result = self.h.store.cancel_interruption(row["interruption_id"], self.h.now)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertTrue(row["cancel_requested"])
        self.h.watch(advance=1)
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")
        self.assertEqual(self.h.record()["withdraw_reason"], "cancel")
        self.h.tick(advance=181)
        self.assertEqual(self.h.record()["state"], "cancelled")
        self.assertEqual(self.h.home.queued(T1), [])
        # §7.2 lists submission_unknown with the records a cancel still acts on (the
        # watch withdraws its row), so the call reports a change, not "already finished".
        self.assertTrue(result["changed"])
        self.assertEqual(result["effects"][row["interruption_id"]], "cancel_requested")

    def test_T21_cancel_on_a_finished_record_blocks_a_later_child(self):
        turn = self.running()
        self.h.tick(advance=24 * 3600)
        parent = self.h.record()
        self.assertEqual(parent["state"], "outcome_unverified")
        self.h.store.cancel_interruption(parent["interruption_id"], self.h.now)
        self.assertTrue(self.h.store.get(parent["interruption_id"])["cancel_requested"])
        # The turn's row finally ends, as a failure of our continuation.
        fail_turn(self.h.home, T1, turn)
        self.h.tick(advance=1)
        child = self.h.records()[1]
        self.assertEqual(child["state"], "cancelled")
        self.assertEqual(child["last_error"], "parent_cancelled")
        # A true no-op: everything in the chain is already stopped.
        again = self.h.store.cancel_interruption(child["interruption_id"], self.h.now)
        self.assertFalse(again["changed"])

    def test_T22_cancel_racing_the_send_marks_and_the_watch_withdraws(self):
        self.h.backend.after_accept = "queue"

        def cancel_during_send(thread_id, prompt):
            self.h.store.cancel_interruption(self.h.record(thread_id)["interruption_id"], self.h.now)

        self.h.backend.on_send = cancel_during_send
        self.ready_after_reset()
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "queued", "a possibly-sent record is never cancelled outright")
        self.assertTrue(row["cancel_requested"])
        self.h.tick(advance=1)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.h.tick(advance=181)
        self.assertEqual(self.h.record()["state"], "cancelled")
        self.assertEqual(self.h.home.queued(T1), [], "no untracked row is left in Codex")

    def test_T24_pause_withdraws_and_returns_the_record_to_waiting(self):
        self.h.engine.options["max_submissions_per_thread_per_day"] = 1
        row = self.send_and_hold()
        claimed = row["last_claim_at"]
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick(advance=1)
        withdrawn = self.h.record()
        self.assertEqual(withdrawn["state"], "withdrawn_unconfirmed")
        self.assertEqual(withdrawn["withdraw_reason"], "paused")
        self.h.tick(advance=181)
        row = self.h.record()
        self.assertIn(row["state"], machine.WAITING)
        self.assertIsNone(row["submitted_at"])
        self.assertIsNone(row["queue_id"])
        self.assertEqual(row["last_claim_at"], claimed)
        self.assertIsNotNone(row["first_queued_at"])
        # The released claim still counts: with a cap of one, nothing more is sent today.
        self.h.store.set_enabled(True, self.h.now)
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["last_error"], "daily_submission_cap")
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_T24_a_paused_withdrawal_that_ran_anyway_is_followed(self):
        self.send_and_hold()
        key = self.h.record()["interruption_id"]
        self.dispatch_then_report_deleted(self.h)
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick(advance=1)
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertIn(row["state"], machine.OBSERVING)
        self.assertIn("dispatched_while_paused", self.h.events(key))

    def test_T24_a_paused_withdrawal_over_a_stale_history_is_never_released(self):
        self.send_and_hold()
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")
        self.h.home.make_stale(T1)
        for _ in range(7):
            self.h.tick(advance=30)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "withdraw_unconfirmed")

    def test_T25_while_paused_the_watch_still_runs_and_cancel_is_honoured(self):
        row = self.send_and_hold()
        self.h.store.set_enabled(False, self.h.now)
        self.h.store.cancel_interruption(row["interruption_id"], self.h.now)
        self.h.tick(advance=1)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.assertEqual(self.h.record()["withdraw_reason"], "cancel")
        self.h.tick(advance=181)
        self.assertEqual(self.h.record()["state"], "cancelled")

    def test_T25_while_paused_the_other_deletes_are_not_suspended(self):
        triggers = {
            "not_loaded": (lambda h: h.backend.loaded_map.__setitem__(T1, "notLoaded"), 6),
            "expired": (lambda h: None, 181),
            "invalid": (lambda h: archive(h.home, T1), 1),
        }
        for name, (trigger, advance) in triggers.items():
            with self.subTest(trigger=name):
                h = self.fresh()
                row = self.send_and_hold(h)
                h.store.set_enabled(False, h.now)
                trigger(h)
                h.tick(advance=advance)
                self.assertEqual(h.backend.deleted, [(T1, row["queue_id"])])
                self.assertEqual(h.record()["state"], "withdrawn_unconfirmed")


class GateTests(EngineCase):
    """§6-§7.8: freshness, the schedule gate, usage expiry and the thread filter."""

    def test_T31_a_future_reset_is_a_wait_with_a_reason(self):
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        key = self.h.record()["interruption_id"]
        accepted, eligible = self.h.store.request_retry_now(key, self.h.now)
        self.assertTrue(accepted)
        self.assertEqual(eligible, RESET)
        self.h.tick(advance=1)
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual(row["state"], "waiting_reset")
        self.assertEqual(row["last_error"], "waiting_reset")
        self.assertEqual(row["reset_at"], RESET)
        self.assertEqual(row["next_retry_at"], RESET + 60)
        self.assertEqual(machine.decode_gates(row["gate_eval"])["schedule"], ("WAIT", "waiting_reset"))

    def test_T32_a_history_that_stays_behind_its_file_blocks_the_send(self):
        self.ready_after_reset()
        self.h.home.make_stale(T1)
        self.h.backend.app = None                    # the app is closed while the lag builds up
        for _ in range(3):
            self.h.tick()
            self.h.now += 60
        self.h.backend.app = dict(APP)
        self.h.tick()
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual(row["last_error"], "projection_stale")
        self.assertEqual(machine.public_code(row), "waiting_thread")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["identity"], ("UNKNOWN", "projection_stale"))
        self.h.home.catch_up(T1)
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_T32_a_short_lag_does_not_block(self):
        self.ready_after_reset()
        self.h.home.make_stale(T1)
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_T32_a_stale_history_withdraws_the_owned_row_and_never_releases_it(self):
        row = self.send_and_hold()
        self.h.home.make_stale(T1)
        for _ in range(5):
            self.h.tick(advance=30)
        self.assertEqual(self.h.backend.deleted, [(T1, row["queue_id"])])
        self.assertEqual(self.h.record()["withdraw_reason"], "projection_stale")
        self.h.tick(advance=181)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertEqual(row["last_error"], "withdraw_unconfirmed")
        self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_T32_a_missing_projection_table_blocks_compatibility(self):
        self.ready_after_reset()
        drop_projection_table(self.h.home)
        self.h.tick()
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual(row["last_error"], "projection_table_missing")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["engine_compatible"],
                         ("BLOCK", "projection_table_missing"))

    def test_T28_a_weekly_limit_never_expires_before_its_reset(self):
        weekly = BASE + 7 * DAY
        self.h.home.fail_usage(T1, TURN_A, reset=weekly)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.backend.usage_result = {"available": False, "reset_at": weekly, "limit_type": "weekly", "reason": "blocked"}
        self.h.tick()
        self.assertEqual(self.h.record()["reset_at"], weekly)
        while self.h.now < weekly + DAY - 3600:
            self.h.tick(advance=6 * 3600 if self.h.now < weekly else 3600)
            self.assertNotEqual(self.h.record()["state"], "terminal_failure", self.h.now - weekly)
        self.h.tick(advance=3600)
        row = self.h.record()
        self.assertEqual(row["state"], "terminal_failure")
        self.assertEqual(row["last_error"], "usage_not_restored_after_reset")
        self.assert_no_send()

    def test_T28_the_never_available_limit_is_seven_days(self):
        self.assertEqual(self.h.engine.options["usage_never_available_seconds"], 7 * DAY)

    def test_T28_only_unavailable_time_between_probes_accumulates(self):
        # The limit is shortened to six hours so the run stays short; the shape of the
        # rule, not the policy number, is what is under test (the number is pinned above).
        h = self.fresh(options={"usage_never_available_seconds": 6 * 3600})
        h.home.fail_usage(T1, TURN_A, reset=None)
        h.backend.loaded_map[T1] = "loaded"
        blocked = {"available": False, "reset_at": None, "limit_type": "unknown", "reason": "blocked"}
        h.backend.usage_result = dict(blocked)
        h.tick()

        def run(hours, step=900):
            for _ in range(int(hours * 3600 / step)):
                h.tick(advance=step)

        run(3)
        h.backend.app = None                          # the app is closed for half a day
        run(12, step=3600)
        h.backend.app = dict(APP)
        h.backend.usage_result = {"available": None, "reset_at": None, "limit_type": "unknown",
                                  "reason": "probe_failed"}
        run(6, step=3600)                             # the probe cannot tell for six hours
        h.backend.usage_result = dict(blocked)
        run(3)
        row = h.record()
        # A day has passed on the clock, but only the blocked stretches were counted.
        self.assertNotEqual(row["state"], "terminal_failure")
        self.assertLess(row["usage_unavailable_seconds"], 6 * 3600)
        run(1)
        row = h.record()
        self.assertEqual(row["state"], "terminal_failure")
        self.assertEqual(row["last_error"], "usage_never_available")
        self.assert_no_send(h)

    def test_T47_a_subagent_or_non_desktop_thread_is_never_detected(self):
        subagent, cli = new_id(), new_id()
        self.h.home.add_thread(subagent, thread_source="subagent")
        self.h.home.add_thread(cli, originator="codex_cli_rs")
        for thread_id in (subagent, cli):
            self.h.home.fail_usage(thread_id)
            self.h.backend.loaded_map[thread_id] = "loaded"
        self.h.tick()
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(self.h.store.all_records(), [])
        self.assert_no_send()


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
        harness.home.fail_transient(T1, code="serverOverloaded")
        harness.enable()
        harness.tick()
        self.assertIsNone(harness.record(T1))
        self.assertIn("category_recovery_disabled", harness.codes(T1))

    def test_a_switched_off_category_is_logged_once_not_every_poll(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.home.fail_transient(T1, code="serverOverloaded")
        harness.enable()
        for _ in range(4):
            harness.tick()
        self.assertEqual(harness.codes(T1).count("category_recovery_disabled"), 1)

    def test_a_switched_off_category_raises_no_notification(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.home.fail_transient(T1, code="serverOverloaded")
        harness.enable()
        harness.tick()
        self.assertEqual(harness.notifications, [])

    def test_other_categories_are_unaffected(self):
        harness = self.harness()
        harness.engine.apply_policy(dict(settings.defaults(), recover_server_5xx=False))
        harness.home.fail_usage(T1)
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
                harness.home.fail_transient(T1, code="serverOverloaded")
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

    def test_the_chain_cap_can_be_lowered_but_never_raised_past_ten(self):
        harness = self.harness()
        self.assertEqual(harness.engine.options["max_chain_continuations"], 6)
        harness.engine.apply_policy(dict(settings.defaults(), max_chain_continuations=1))
        self.assertEqual(harness.engine.options["max_chain_continuations"], 1)
        harness.engine.apply_policy(dict(settings.defaults(), max_chain_continuations=50))
        self.assertLessEqual(harness.engine.options["max_chain_continuations"], 10)

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
                   "unknown_reconcile_window_seconds", "reset_grace_seconds",
                   "settle_seconds", "projection_grace_seconds", "max_withdraw_attempts",
                   "usage_never_available_seconds", "usage_after_reset_seconds")}
        harness.engine.apply_policy(dict(settings.defaults(),
                                         **{key: 0 for key in settings.FIELDS if key in before}))
        for key, value in before.items():
            self.assertEqual(harness.engine.options[key], value, key)

    def test_no_setting_names_an_engine_safety_option(self):
        reserved = {"delivery_timeout_seconds", "max_queue_retries",
                    "max_submissions_per_thread_per_day", "thread_cooldown_seconds",
                    "unknown_reconcile_window_seconds", "reset_grace_seconds",
                    "conservative_poll_seconds", "state_poll_seconds",
                    "settle_seconds", "projection_grace_seconds", "loaded_check_seconds",
                    "max_withdraw_attempts", "usage_never_available_seconds",
                    "usage_after_reset_seconds"}
        self.assertEqual(set(settings.FIELDS) & reserved, set())


if __name__ == "__main__":
    unittest.main()
