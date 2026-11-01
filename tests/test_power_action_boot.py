"""The power action counts only what Windows' current start can still run (v0.6.20 final).

Measured 2026-11-01 on the owner's PC: two conversations whose latest turn still said inProgress, begun 18 and 30 days
before (a crash's leftovers; nothing ran), and two items in Codex's queue, made 6 and 36 days before, held the power
action - and the account switch's restart, which asks the same - for good. LocalSource.activity now reads with the boot
time the watcher's heartbeat records: a latest turn that began before it says inProgress for good, by the rule a cut-off
recovery turn is judged by (domain/states.ended_by_boot, 2026-10-21), and an item queued before it (queued_items'
created_at_ms) is not counted; without a boot time both counts are None, which judge_activity reads as codex_unknown.

Every Codex home is codexsim's, in a temporary folder; no Codex runs and no real home is read.

    PYTHONPATH="src;tests" python -m unittest test_power_action_boot
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codexsim  # noqa: E402
from codex_auto_resume import poweraction as pa  # noqa: E402
from codex_auto_resume.codex import LocalSource  # noqa: E402
from codex_auto_resume.domain import states  # noqa: E402
from codex_auto_resume.domain.power_vocabulary import PowerWait  # noqa: E402
from codex_auto_resume.engine.outcome import OutcomeMixin  # noqa: E402

DAY = 86400
BOOTED = codexsim.BASE - 3 * DAY          # Windows started three days before codexsim's present


class HomeCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = codexsim.CodexHome(Path(folder.name))
        self.source = LocalSource(self.home.root)

    def activity(self, booted=BOOTED):
        return self.source.activity((), codexsim.BASE, booted=booted)

    def running_since(self, started):
        thread = codexsim.new_id()
        self.home.add_turn(thread, status="inProgress", started=int(started))
        return thread

    def queued_at(self, created):
        thread = codexsim.new_id()
        self.home.add_thread(thread)
        queue_id = self.home.enqueue(thread, "a message of the user's")
        with closing(sqlite3.connect(self.home.root / "queue_1.sqlite")) as db:
            db.execute("UPDATE queued_items SET created_at_ms=? WHERE id=?", (int(created * 1000), queue_id))
            db.commit()
        return queue_id


class BootTests(HomeCase):
    def test_a_turn_and_an_item_left_from_before_windows_started_count_as_nothing(self):
        """Fails with the change reverted: the 30-day-old turn runs and the 36-day-old item is queued, for good."""
        self.running_since(BOOTED - 30 * DAY)
        self.queued_at(BOOTED - 36 * DAY)
        found = self.activity()
        self.assertEqual((found["running"], found["queued"]), (0, 0))
        self.assertIsNone(pa.judge_activity(found))

    def test_a_turn_since_windows_started_still_holds_the_action(self):
        self.running_since(BOOTED + 60)
        self.assertEqual(pa.judge_activity(self.activity()), PowerWait.TURN_RUNNING)

    def test_an_item_queued_since_windows_started_still_holds_the_action(self):
        self.queued_at(BOOTED + 60)
        self.assertEqual(pa.judge_activity(self.activity()), PowerWait.QUEUED_INPUT)

    def test_the_margin_is_the_cut_off_rule_s(self):
        """A turn begun within BOOT_MARGIN of the boot is not one Windows' start ended (domain/states.ended_by_boot)."""
        self.running_since(BOOTED - states.BOOT_MARGIN + 1)
        self.assertEqual(self.activity()["running"], 1)
        self.assertEqual(OutcomeMixin.CUT_OFF_BOOT_MARGIN, states.BOOT_MARGIN)

    def test_no_boot_time_is_unknown_never_nothing_running(self):
        """Fails with the change reverted: without a boot time the counts were read as they stood."""
        for booted in (None, float("nan"), "yesterday", 0):
            with self.subTest(booted=booted):
                found = self.activity(booted)
                self.assertEqual((found["history"], found["running"], found["queued"]), (True, None, None))
                self.assertEqual(pa.judge_activity(found), PowerWait.CODEX_UNKNOWN)

    def test_an_item_with_no_creation_time_counts(self):
        thread = codexsim.new_id()
        self.home.add_thread(thread)
        self.home.enqueue(thread, "a message of the user's")            # created_at_ms left NULL
        self.assertEqual(self.activity()["queued"], 1)

    def test_a_queue_that_keeps_no_creation_time_counts_every_item(self):
        """A Codex whose queued_items has no created_at_ms: every item counts, as before - never fewer than are there."""
        self.queued_at(BOOTED - 36 * DAY)
        with closing(sqlite3.connect(self.home.root / "queue_1.sqlite")) as db:
            db.execute("ALTER TABLE queued_items DROP COLUMN created_at_ms")
            db.commit()
        self.assertEqual(self.activity()["queued"], 1)


class EngineTests(unittest.TestCase):
    def test_the_engine_reads_the_heartbeat_s_boot_time_and_none_is_unknown(self):
        from codex_auto_resume.engine import Engine
        asked = []

        class Source:
            def activity(self, threads, now, booted=None):
                asked.append(booted)
                return {"history": True, "running": 0, "queued": 0}

        class Heartbeat:
            def __init__(self, status):
                self.status = status

            def watcher_status(self):
                return self.status
        Engine(Heartbeat({"booted_at": BOOTED}), Source(), None, clock=lambda: codexsim.BASE).activity()
        Engine(Heartbeat(None), Source(), None, clock=lambda: codexsim.BASE).activity()
        self.assertEqual(asked, [BOOTED, None])


class RuleTests(unittest.TestCase):
    def test_ended_by_boot(self):
        self.assertTrue(states.ended_by_boot(BOOTED - 60, BOOTED))
        self.assertFalse(states.ended_by_boot(BOOTED - 1, BOOTED))
        self.assertFalse(states.ended_by_boot(BOOTED + 60, BOOTED))
        self.assertFalse(states.ended_by_boot(None, BOOTED))
        self.assertFalse(states.ended_by_boot(BOOTED - 60, None))


if __name__ == "__main__":
    unittest.main()
