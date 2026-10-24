"""v0.6.19 (issue #50; A12 amended by the owner on 2026-10-24): Retry now on a recovery that waits for a usage reset
reads usage once, at that moment - and only then, nothing on a schedule, nothing sent of its own.

If Codex's answer says the limit has lifted, the recorded reset is replaced by the newer one Codex's reading shows and
the recovery goes on through every gate as usual; still limited, unknown or a failed read changes nothing. The row says
when it checked and what it read; with no watcher running nothing is read, and Retry now says so. A later time a person
chose is never shortened and reads no usage. Retry now made at the store alone, as v0.6.10's scenarios make it, reads
nothing (tests/test_engine.py T31, frozen).

Held against core's own engine, store and simulated Codex home (test_engine's Harness).
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codexsim import RESET  # noqa: E402
from test_engine import T1, TURN_A, Harness  # noqa: E402
from codex_auto_resume import config, control, machine  # noqa: E402
from codex_auto_resume.control import actions as control_actions  # noqa: E402


class CheckCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = config.Paths(Path(temp.name) / "home")
        self.paths.ensure()
        self.h = Harness(self.paths.state_dir)
        self.addCleanup(self.h.close)
        self.h.enable()
        self.reads = 0
        usage = self.h.backend.usage

        def counted():
            self.reads += 1
            return usage()
        self.h.backend.usage = counted

    def waiting(self, loaded=True):
        """A usage-limited conversation whose reset Codex gave is an hour ahead."""
        self.h.home.fail_usage(T1, TURN_A)
        if loaded:
            self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "waiting_reset")
        self.assertGreater(row["reset_at"], self.h.now)
        return row["interruption_id"]

    def retry(self, key, woke=True):
        """A person's Retry now, as the Dashboard asks it - the watcher's wake answered as `woke` says."""
        with mock.patch.object(control_actions.WakeEvent, "signal", lambda _self: woke),                 mock.patch("time.time", lambda: self.h.now):          # the control layer on the harness's clock
            return control.Control(self.paths).request_retry_now(key)

    def sends(self):
        return len(self.h.backend.send_calls)

    def pending(self):
        with mock.patch("time.time", lambda: self.h.now):
            (row,) = [row for row in control.Control(self.paths).list_pending() if row["thread_id"] == T1]
        return row


class AvailableTests(CheckCase):
    def test_a_reading_that_says_available_lifts_the_reset_and_it_goes_on(self):
        """Fails with the check reverted: the reset an hour ahead holds it, and nothing is sent."""
        key = self.waiting()
        before = self.reads
        answer = self.retry(key)
        self.assertEqual(answer["usage_check"], "asked")
        self.h.tick(advance=1)
        self.assertEqual(self.reads - before, 1, "read once, at the click's look - the gates and the send's recheck reuse it (C9)")
        self.assertEqual(self.sends(), 1)
        row = self.h.record()
        self.assertLess(row["reset_at"], RESET, "the reset is the newer one Codex's reading showed")
        self.assertIn("usage_checked", self.h.events(key))
        self.assertEqual(self.pending()["usage_check"]["read"], "available")
        self.assertTrue(self.pending()["usage_check"]["continued"], "sent since the reading: the row says it went on")

    def test_available_still_meets_every_gate(self):
        """The reset lifted, a conversation the app does not hold still waits for it (A11): no send without every gate."""
        key = self.waiting(loaded=False)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.retry(key)
        self.h.tick(advance=1)
        self.assertEqual(self.sends(), 0)
        row = self.h.record()
        self.assertLess(row["reset_at"], RESET)
        self.assertEqual(row["last_error"], "notLoaded")
        check = self.pending()["usage_check"]
        self.assertEqual((check["lifted"], check["continued"]), (True, False),
                         "lifted, not continued: the row must not say it went on (the review of 2026-10-24)")

    def test_mcp_retry_now_asks_for_no_reading(self):
        """Only a person's Retry now in the Dashboard reads usage; MCP's retry_now behaves as before."""
        key = self.waiting()
        with mock.patch.object(control_actions.WakeEvent, "signal", lambda _self: True),                 mock.patch("time.time", lambda: self.h.now):
            answer = control.Control(self.paths).request_retry_now(key, actor="mcp")
        self.assertIsNone(answer["usage_check"])
        self.assertEqual(self.h.store.usage_checks_asked(self.h.now), {})
        before = self.reads
        self.h.tick(advance=1)
        self.assertEqual((self.reads, self.sends()), (before, 0))

    def test_the_request_is_taken_once(self):
        key = self.waiting(loaded=False)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.backend.usage_result = {"available": False, "reset_at": RESET, "limit_type": "x", "reason": "limited"}
        self.retry(key)
        self.h.tick(advance=1)
        reads = self.reads
        self.h.tick(advance=1)
        self.assertEqual(self.reads, reads, "a second look reads nothing more")
        self.assertEqual(self.h.store.usage_checks_asked(self.h.now), {})


class NothingReleasedTests(CheckCase):
    def test_still_limited_keeps_the_reset_codex_gave(self):
        """Fails with the reading taken as a release: a still-limited answer would lift the reset."""
        key = self.waiting()
        self.h.backend.usage_result = {"available": False, "reset_at": RESET, "limit_type": "x", "reason": "limited"}
        self.retry(key)
        self.h.tick(advance=1)
        row = self.h.record()
        self.assertEqual((row["state"], row["reset_at"], self.sends()), ("waiting_reset", RESET, 0))
        self.assertEqual(self.pending()["usage_check"], {"at": self.h.now, "read": "still_limited", "lifted": False, "why": None,
                                                        "continued": False})

    def test_an_unknown_or_failed_read_releases_nothing(self):
        for name, usage in (("unknown", lambda: {"available": None, "reason": "unknown"}),
                            ("failed", mock.Mock(side_effect=RuntimeError("no answer")))):
            with self.subTest(name):
                self.setUp()
                key = self.waiting()
                self.h.backend.usage = usage
                self.retry(key)
                self.h.tick(advance=1)
                row = self.h.record()
                self.assertEqual((row["state"], row["reset_at"], self.sends()), ("waiting_reset", RESET, 0))
                self.assertEqual(self.pending()["usage_check"]["read"], "unknown")

    def test_with_no_watcher_running_nothing_is_read_and_it_says_so(self):
        key = self.waiting()
        answer = self.retry(key, woke=False)
        self.assertEqual(answer["usage_check"], "not_running")
        self.assertIn("not running", answer["note"])
        self.assertEqual(self.h.store.usage_checks_asked(self.h.now), {}, "asked now or not at all")
        before = self.reads
        self.h.tick(advance=1)
        self.assertEqual((self.reads, self.sends()), (before, 0))

    def test_a_postponement_is_never_shortened_and_reads_no_usage(self):
        key = self.waiting()
        self.h.store.postpone(key, T1, self.h.now + 7200, self.h.now)
        self.assertGreater(self.h.record()["not_before"], self.h.now)
        answer = self.retry(key)
        self.assertIsNone(answer["usage_check"])
        before = self.reads
        self.h.tick(advance=1)
        self.assertEqual(self.reads, before)

    def test_a_pause_beats_the_click(self):
        key = self.waiting()
        self.h.store.set_enabled(False, self.h.now)
        answer = self.retry(key)
        self.assertEqual(answer["usage_check"], "paused", "no request, and the click says why (the review of 2026-10-24)")
        self.assertEqual(self.h.store.usage_checks_asked(self.h.now), {})

    def test_retry_now_made_at_the_store_alone_reads_nothing(self):
        """v0.6.10's own scenarios (test_engine T31, frozen) ask the store directly: the schedule moves, nothing is read."""
        key = self.waiting()
        before = self.reads
        self.h.store.request_retry_now(key, self.h.now)
        self.h.tick(advance=1)
        self.assertEqual((self.reads, self.sends()), (before, 0))
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["schedule"], ("WAIT", "waiting_reset"))


if __name__ == "__main__":
    unittest.main()
