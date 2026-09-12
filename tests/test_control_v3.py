"""The control operations added with schema 3, and the upgrade window.

Cancel now stops one task and everything that continues it, rather than a whole
conversation; Clear history hides and never deletes; statistics and the timeline are
content-free; and while an older watcher still owns an unmigrated state, the actions
that only reduce automation keep working while everything else says why it cannot.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import config, control, machine
from codex_auto_resume.store import Store

ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN_A = "0a1b2c3d-0002-7000-8000-00000000000a"
TURN_B = "0a1b2c3d-0002-7000-8000-00000000000b"
TURN_C = "0a1b2c3d-0002-7000-8000-00000000000c"
KEY_A, KEY_B, KEY_C = "a" * 64, "b" * 64, "c" * 64


def detection(key, turn, category="server_5xx", ordinal=2):
    return {"thread_id": THREAD, "turn_id": turn, "completed_at": 110.0, "started_at": 105.0,
            "ordinal": ordinal, "interruption_id": key, "reset_at": None,
            "limit_type": category, "uncertain": False, "category": category}


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = config.Paths(Path(self.temporary.name))
        self.paths.ensure()
        self.control = control.Control(self.paths)
        for name, value in (("watcher_running", False), ("startup_enabled", False)):
            guard = patch.object(control.Control, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)

    def store(self):
        return Store(self.paths.state_dir)


class ChainCancelTests(Base):
    def chain(self):
        """A parent whose continuation turn failed, and the child that failure made."""
        with self.store() as store:
            store.set_enabled(True, 100.0)
            store.register(detection(KEY_A, TURN_A), 100.0, state="waiting_backoff", next_retry_at=100.0)
            limits = {"max_recovery_attempts": 9, "max_no_progress": 9, "max_chain_continuations": 9}
            self.assertTrue(store.reserve(KEY_A, 101.0, limits=limits))
            store.update(KEY_A, state="queued", queue_id="0a1b2c3d-0009-7000-8000-000000000009")
            store.correlate(KEY_A, TURN_B, 102.0)
            store.register(detection(KEY_B, TURN_B, ordinal=3), 103.0, state="waiting_backoff",
                           next_retry_at=103.0, limits=limits)
            return store.get(KEY_B)

    def test_cancel_reaches_every_record_of_the_task_and_no_other(self):
        child = self.chain()
        self.assertEqual(child["parent_interruption_id"], KEY_A)
        with self.store() as store:
            store.register(detection(KEY_C, TURN_C, ordinal=9), 104.0, state="waiting_backoff",
                           next_retry_at=104.0)
        result = self.control.cancel_interruption(KEY_B)
        self.assertTrue(result["changed"])
        self.assertEqual(result["effects"][KEY_B], "cancelled")
        # The parent is running in Codex: it is marked, never forced into "cancelled".
        self.assertEqual(result["effects"][KEY_A], "cancel_requested")
        with self.store() as store:
            self.assertEqual(store.get(KEY_A)["state"], "turn_started")
            self.assertTrue(store.get(KEY_A)["cancel_requested"])
            # A separate task on the same conversation is untouched, and so is the
            # conversation's own switch.
            self.assertEqual(store.get(KEY_C)["state"], "waiting_backoff")
            self.assertTrue(store.thread_enabled(THREAD))

    def test_cancelling_a_finished_task_says_so(self):
        with self.store() as store:
            store.register(detection(KEY_A, TURN_A), 100.0)
            store.update(KEY_A, state="superseded")
        result = self.control.cancel_interruption(KEY_A)
        self.assertFalse(result["changed"])
        self.assertIn("nothing to stop", result["message"])


class HistoryAndStatisticsTests(Base):
    def test_clear_history_hides_finished_records_and_keeps_them_counting(self):
        with self.store() as store:
            store.register(detection(KEY_A, TURN_A), 100.0)
            store.update(KEY_A, state="superseded")
            store.register(detection(KEY_B, TURN_B, ordinal=3), 100.0)
        result = self.control.clear_history()
        self.assertEqual(result, {"hidden": 1, "kept": 1})
        self.assertEqual([item["interruption_id"] for item in self.control.history()], [KEY_B])
        # Hidden is display only: the record is still there for every safety decision.
        self.assertEqual(len(self.control.list_pending(include_terminal=True)), 2)
        self.assertEqual(self.control.statistics()["interruptions_detected"], 2)

    def test_the_timeline_is_content_free(self):
        with self.store() as store:
            store.register(detection(KEY_A, TURN_A), 100.0)
        events = self.control.timeline(KEY_A)["events"]
        self.assertEqual(events[0]["code"], "detected")
        allowed = {"event_id", "at", "interruption_id", "code", "from_state", "to_state", "reason",
                   "actor", "turn_ref", "flags", "value", "to_code"}
        for event in events:
            self.assertEqual(set(event), allowed)
            # Derived from the state, from the closed public vocabulary - never free text.
            self.assertIn(event["to_code"], set(machine.PUBLIC_CODES) | {None})
        self.assertEqual(events[0]["to_code"], "waiting_reset")

    def test_the_timeline_code_is_the_code_the_listing_shows(self):
        # Derived from the state alone, a release after a queue process that never
        # started read "scheduled" in the timeline and "failed_retryable" in Pending -
        # two words for one moment of one record.
        with self.store() as store:
            store.set_enabled(True, 100.0)
            store.register(detection(KEY_A, TURN_A), 100.0, state="waiting_backoff", next_retry_at=100.0)
            self.assertTrue(store.reserve(KEY_A, 101.0))
            self.assertTrue(store.release_claim(KEY_A, "waiting_retry", "queue_process_not_started", 102.0))
        listed = self.control.list_pending()[0]
        self.assertEqual(listed["code"], "failed_retryable")
        events = self.control.timeline(KEY_A)["events"]
        released = [event for event in events
                    if (event["from_state"], event["to_state"]) == ("submitting", "waiting_retry")]
        self.assertEqual(len(released), 1)
        self.assertEqual(released[0]["to_code"], listed["code"])
        # Retry now moves only the schedule and leaves the stored reason alone, so the
        # record still lists as failed_retryable - and its event must say the same.
        self.control.request_retry_now(KEY_A)
        self.assertEqual(self.control.list_pending()[0]["code"], "failed_retryable")
        last = self.control.timeline(KEY_A)["events"][-1]
        self.assertEqual(last["reason"], "retry_now")
        self.assertEqual(last["to_code"], "failed_retryable")

    def test_listing_carries_the_public_code_and_overlays(self):
        with self.store() as store:
            store.register(detection(KEY_A, TURN_A), 100.0, state="waiting_backoff")
        self.control.set_enabled(False)
        item = self.control.list_pending()[0]
        self.assertEqual(item["code"], "scheduled")
        self.assertIn("paused", item["overlays"])


class ThreadSwitchTests(Base):
    def test_a_conversation_can_be_switched_back_on(self):
        self.control.cancel_thread(THREAD)
        self.assertEqual(self.control.set_thread_enabled(THREAD, True), {"thread_id": THREAD, "enabled": True})

    def test_the_switch_needs_an_exact_id(self):
        with self.assertRaises(control.ControlError):
            self.control.set_thread_enabled(THREAD.upper(), True)


class RetryNowTests(Base):
    def test_a_future_usage_reset_is_named_rather_than_promised_away(self):
        with self.store() as store:
            record = dict(detection(KEY_A, TURN_A, category="usage_limit"), reset_at=4102444000.0)
            store.register(record, 100.0)
        result = self.control.request_retry_now(KEY_A)
        self.assertEqual(result["eligible_at"], 4102444000.0)
        self.assertIn("reset", result["note"])
        self.assertFalse(result["woke"], "no watcher is running to wake")

    def test_a_running_recovery_is_refused_with_the_reason(self):
        with self.store() as store:
            store.set_enabled(True, 100.0)
            store.register(detection(KEY_A, TURN_A), 100.0, next_retry_at=100.0)
            store.reserve(KEY_A, 101.0)
        with self.assertRaises(control.ControlError) as caught:
            self.control.request_retry_now(KEY_A)
        self.assertIn("being sent", str(caught.exception))


def legacy_store_module(tag):
    """The store module exactly as a tagged release shipped it.

    Skipped where the tag is not in the checkout, except on CI, which fetches the tags
    for exactly these tests: there a missing tag is a failure, not a quiet skip.
    """
    import os
    shown = subprocess.run(["git", "-C", str(ROOT), "show", tag + ":src/codex_auto_resume/store.py"],
                           capture_output=True, text=True, encoding="utf-8")
    if shown.returncode != 0:
        if os.environ.get("CI"):
            raise AssertionError("%s is not in this checkout; CI must fetch the tags" % tag)
        raise unittest.SkipTest("%s is not in this checkout" % tag)
    source = shown.stdout
    source = source.replace("from . import failures", "from codex_auto_resume import failures")
    folder = Path(tempfile.mkdtemp())
    path = folder / ("store_%s.py" % tag.replace(".", "_"))
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(sys.platform == "win32", "Windows named objects")
class UpgradeWindowTests(Base):
    """T35: an older watcher still owns a schema-2 state."""

    @contextmanager
    def older_watcher(self):
        code = ("import sys, time\n"
                "sys.path.insert(0, %r)\n"
                "from codex_auto_resume.windows import Mutex\n"
                "with Mutex(%r, timeout=0):\n"
                "    print('held', flush=True)\n"
                "    time.sleep(60)\n" % (SRC, str(self.paths.state_dir)))
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "held")
            yield
        finally:
            process.kill()
            process.wait(timeout=10)
            process.stdout.close()

    def v2_state(self):
        old = legacy_store_module("v0.5.7")
        with old.Store(self.paths.state_dir) as store:
            store.register(detection(KEY_A, TURN_A), 100.0)
        self.assertEqual(self.version(), 2)

    def version(self):
        db = sqlite3.connect(self.paths.state_dir / "state.sqlite")
        try:
            return db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()

    def test_only_what_reduces_automation_works_until_the_old_watcher_stops(self):
        self.v2_state()
        with self.older_watcher():
            self.assertEqual(self.control.set_enabled(False), {"enabled": False})
            self.control.cancel_thread(THREAD)
            status = self.control.get_status()
            self.assertTrue(status["upgrade_pending"])
            with self.assertRaises(control.ControlError) as caught:
                self.control.list_pending()
            self.assertIn("Upgrade pending", str(caught.exception))
            self.assertEqual(self.version(), 2, "nothing migrates under an older watcher")
        # Once it has gone, the next call upgrades under the mutex, and the thread-wide
        # cancel made during the window is still there.
        listed = self.control.list_pending(include_terminal=True)
        self.assertEqual(self.version(), 3)
        self.assertEqual(listed[0]["state"], "cancelled")
        self.assertFalse(listed[0]["thread_enabled"])

    def test_a_newer_state_is_never_called_damage(self):
        with self.store():
            pass
        with closing(sqlite3.connect(self.paths.state_dir / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=4")
            db.commit()
        with self.assertRaises(control.ControlError) as caught:
            self.control.list_pending()
        self.assertIn("newer version", str(caught.exception))
        self.assertIn("do not delete", str(caught.exception))


class WatcherIdentityTests(Base):
    """What a status read can, and cannot, prove about a handover.

    `app.py` writes `config.version()` into the heartbeat on every tick, so the moment an
    upgrade replaces the files a still-running *old* watcher starts reporting the *new*
    version. `code_version` therefore cannot prove that a restart happened, and anything
    that waits for it to change is waiting for something that has already changed. What can
    prove it is the pair the store has recorded all along and this layer used to drop: a
    `started_at` that moved, from a watcher that still holds the single-instance mutex.
    """

    def heartbeat(self, pid=4321, started_at=100.0, code_version="0.6.0", now=200.0):
        with self.store() as store:
            store.heartbeat(now, pid=pid, session_id="session", started_at=started_at,
                            ok=True, engine_state="verified", code_version=code_version)
        return self.control.get_status()["watcher"]

    def test_the_status_carries_the_identity_of_the_watcher_that_wrote_it(self):
        watcher = self.heartbeat()
        self.assertEqual(watcher["pid"], 4321)
        self.assertEqual(watcher["started_at"], 100.0)

    def test_a_restart_shows_in_the_start_time_and_never_in_the_version(self):
        before = self.heartbeat(code_version="0.6.0")
        # The upgrade lands. The same process keeps ticking and now reports the new
        # version, because the version is read from the files it was upgraded under.
        during = self.heartbeat(code_version="0.7.0")
        self.assertNotEqual(during["code_version"], before["code_version"])
        self.assertEqual(during["started_at"], before["started_at"])
        self.assertEqual(during["pid"], before["pid"])
        # The handover itself: another process, with a start of its own.
        after = self.heartbeat(pid=9876, started_at=500.0, code_version="0.7.0")
        self.assertNotEqual(after["started_at"], before["started_at"])
        self.assertNotEqual(after["pid"], before["pid"])

    def test_a_state_no_watcher_has_written_to_reports_nothing(self):
        with self.store():
            pass
        watcher = self.control.get_status()["watcher"]
        self.assertIsNone(watcher["pid"])
        self.assertIsNone(watcher["started_at"])


if __name__ == "__main__":
    unittest.main()
