"""v0.6.19 (the owner's decision of 2026-10-24): Rescan is "check all" - besides everything it did (each waiting recovery
looked at again, one retired only on proof of newer work), a person's Rescan in the Dashboard reads Codex's usage once
for every recovery that waits for a usage reset, with Retry now's own rules.

* One reading for several recoveries: a request each, all answered by the engine's one reading (its 30 seconds' cache).
* A reading of the last 30 seconds answers it: nothing more is read.
* Nothing brought forward: their next looks and Retry now's counts stay as they were (test_rescan holds the rest).
* Codex says the limit lifted: each goes on through every gate; still limited: nothing changes. The rows say what was
  read and that a Rescan asked it.
* Only the Dashboard's click reads: the control's rescan without it, or for anyone else, asks nothing; the bridge's
  `rescan` - the Dashboard's - asks it.
* Not under a Pause, Observe only, quiet hours or no internet, nor for a conversation switched off: nothing is asked,
  and the reply says why. With no watcher running nothing stays asked, and it says so.

Held against core's own engine, store and simulated Codex home (test_engine's Harness), with a judge of the test's own in
place of the one that reads a Codex home (rescan.judge_for), so nothing here reads this machine's Codex.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codexsim import RESET  # noqa: E402
from test_engine import T1, T2, TURN_A, TURN_B, Harness  # noqa: E402
from codex_auto_resume import config, control, controlcli, power  # noqa: E402
from codex_auto_resume.control import actions as control_actions  # noqa: E402
from codex_auto_resume.store.actions import RECHECKED  # noqa: E402

T3 = "33333333-3333-7333-8333-333333333333"
TURN_C = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
LIMITED = {"available": False, "reset_at": RESET, "limit_type": "x", "reason": "limited"}


def rechecked(_row, _kin):
    """The rescan's judge for this test: every record still the latest failure, left waiting."""
    return RECHECKED, None


class RescanCase(unittest.TestCase):
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

    def waiting(self, *threads):
        """Usage-limited conversations whose reset Codex gave is an hour ahead; their keys."""
        for thread, turn in threads:
            self.h.home.fail_usage(thread, turn)
            self.h.backend.loaded_map[thread] = "loaded"
        self.h.tick()
        keys = []
        for thread, _turn in threads:
            row = self.h.record(thread)
            self.assertEqual(row["state"], "waiting_reset")
            self.assertGreater(row["reset_at"], self.h.now)
            keys.append(row["interruption_id"])
        return keys

    def rescan(self, woke=True, **keywords):
        """A Rescan, as the Dashboard's bridge asks it (unless `keywords` say otherwise), on the harness's clock."""
        keywords.setdefault("read_usage", True)
        with mock.patch.object(control_actions.WakeEvent, "signal", lambda _self: woke), \
                mock.patch("time.time", lambda: self.h.now):
            return control.Control(self.paths).rescan_pending(rechecked, **keywords)

    def asked(self):
        return self.h.store.usage_checks_asked(self.h.now)

    def check(self, thread):
        with mock.patch("time.time", lambda: self.h.now):
            (row,) = [row for row in control.Control(self.paths).list_pending() if row["thread_id"] == thread]
        return row["usage_check"]


class CheckAllTests(RescanCase):
    THREADS = ((T1, TURN_A), (T2, TURN_B), (T3, TURN_C))

    def test_one_reading_answers_every_recovery_that_waits_for_a_usage_reset(self):
        """Fails with the reading reverted: the resets an hour ahead hold all three, nothing read, nothing sent."""
        keys = self.waiting(*self.THREADS)
        before = self.reads
        answer = self.rescan()
        self.assertEqual((answer["usage_check"], answer["usage_asked"]), ("asked", 3))
        self.assertEqual(set(self.asked()), set(keys))
        self.h.tick(advance=1)
        self.assertEqual(self.reads - before, 1, "one reading for the three, not one each (C9)")
        for thread, _turn in self.THREADS:
            with self.subTest(thread):
                self.assertLess(self.h.record(thread)["reset_at"], RESET, "lifted to the newer reset")
                check = self.check(thread)
                self.assertEqual((check["read"], check["lifted"], check["source"]), ("available", True, "rescan"))
        self.assertGreaterEqual(len(self.h.backend.send_calls), 1, "it went on through every gate")
        self.assertEqual(self.asked(), {})

    def test_a_reading_of_the_last_30_seconds_answers_it(self):
        self.waiting(*self.THREADS[:2])
        self.h.engine.usage()                   # a reading just made
        before = self.reads
        self.rescan()
        self.h.tick(advance=1)
        self.assertEqual(self.reads, before, "the reading of a moment ago is the one")
        self.assertEqual((self.check(T1)["read"], self.check(T1)["source"]), ("available", "rescan"))

    def test_still_limited_changes_nothing_and_nothing_is_brought_forward(self):
        keys = self.waiting(*self.THREADS[:2])
        self.h.backend.usage_result = LIMITED
        before = {key: self.h.store.get(key) for key in keys}
        self.rescan()
        for key in keys:
            row = self.h.store.get(key)
            self.assertEqual((row["next_retry_at"], row["retry_now_count"]),
                             (before[key]["next_retry_at"], before[key]["retry_now_count"]),
                             "a Rescan brings no schedule forward; the reading is served at the next look")
        self.h.tick(advance=1)
        for thread in (T1, T2):
            row = self.h.record(thread)
            self.assertEqual((row["state"], row["reset_at"]), ("waiting_reset", RESET))
            check = self.check(thread)
            self.assertEqual((check["read"], check["source"]), ("still_limited", "rescan"))
        self.assertEqual(self.h.backend.send_calls, [])

    def test_with_no_watcher_running_nothing_stays_asked(self):
        self.waiting(*self.THREADS[:2])
        answer = self.rescan(woke=False)
        self.assertEqual((answer["usage_check"], answer["usage_asked"]), ("not_running", 0))
        self.assertEqual(self.asked(), {})

    def test_nothing_waiting_for_a_usage_reset_reads_nothing(self):
        answer = self.rescan()
        self.assertIsNone(answer["usage_check"])
        self.assertEqual(self.asked(), {})


class OnlyThePersonsClickTests(RescanCase):
    def test_the_controls_rescan_without_the_click_asks_nothing(self):
        """MCP or anything else that asks the control for a rescan reads no usage."""
        self.waiting((T1, TURN_A))
        for keywords in ({"read_usage": False}, {"read_usage": True, "actor": "mcp"}):
            with self.subTest(keywords):
                answer = self.rescan(**keywords)
                self.assertNotIn("usage_check", answer)
                self.assertEqual(self.asked(), {})
        before = self.reads
        self.h.tick(advance=1)
        self.assertEqual(self.reads, before)

    def test_the_dashboards_bridge_asks_it(self):
        seen = {}

        def rescan_pending(judge, **keywords):
            seen.update(keywords)
            return {}
        surface = control.Control(self.paths)
        with mock.patch("codex_auto_resume.rescan.judge_for", lambda _control: rechecked), \
                mock.patch.object(surface, "rescan_pending", rescan_pending):
            reply = controlcli.dispatch(surface, "rescan", {})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(seen, {"actor": "gui", "read_usage": True})


class NotReadTests(RescanCase):
    def test_what_stops_a_reading_is_said_and_nothing_is_asked(self):
        cases = {
            "paused": lambda: self.h.store.set_enabled(False, self.h.now),
            "observe_only": lambda: self.h.store.set_observe_only(True),
            "conversation_off": lambda: self.h.store.set_thread_enabled(T1, False, actor="gui"),
        }
        for why, make in cases.items():
            with self.subTest(why):
                self.setUp()
                self.waiting((T1, TURN_A))
                make()
                answer = self.rescan()
                self.assertEqual((answer["usage_check"], answer["usage_asked"]), (why, 0))
                self.assertEqual(self.asked(), {})

    def test_quiet_hours_and_no_internet(self):
        for why, patches in (("quiet_hours", [mock.patch.object(control_actions.quiet, "quiet_until",
                                                                 lambda now, values: now + 600)]),
                             ("offline", [mock.patch.object(power, "waits_for_network", lambda values: True),
                                          mock.patch.object(control_actions.network, "internet", lambda: False)])):
            with self.subTest(why):
                self.setUp()
                self.waiting((T1, TURN_A))
                for each in patches:
                    each.start()
                try:
                    answer = self.rescan()
                finally:
                    for each in patches:
                        each.stop()
                self.assertEqual((answer["usage_check"], answer["usage_asked"]), (why, 0))
                self.assertEqual(self.asked(), {})

    def test_a_conversation_switched_off_is_passed_over_beside_one_that_is_on(self):
        keys = self.waiting((T1, TURN_A), (T2, TURN_B))
        self.h.store.set_thread_enabled(T1, False, actor="gui")
        answer = self.rescan()
        self.assertEqual((answer["usage_check"], answer["usage_asked"]), ("asked", 1))
        self.assertEqual(set(self.asked()), {keys[1]})


if __name__ == "__main__":
    unittest.main()
