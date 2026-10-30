"""Send notices to your phone or inbox, where the notices come from (v0.6.20, engine/push.py): at P20 core tells the plug
of each notice; a kind of the closed table, an event the person picked and a channel switched on make one outbox row a
channel, written only while it is on and recovery is not paused, at most 30 an hour; watched, nothing is written and
the journal keeps what it would have done; at P8 the courier is started where a row waits, at most once a minute, and
never waited for. Nothing of a notice but closed words and numbers reaches the outbox.

No courier is started: the launch is a seam.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, statement  # noqa: E402
from codex_auto_resume_advanced.engine import push  # noqa: E402
from codex_auto_resume_advanced.registry import PUSH_NOTICES  # noqa: E402
from codex_auto_resume_advanced.vocabulary import CourierEvent, JournalCode, OptionKey  # noqa: E402

CAP = "push_notices"


def told(kind="resumed", category="usage_limit", index=3, **more):
    return dict({"kind": kind, "category": category, "alias_index": index, "at": ac.NOW}, **more)


class MappingTests(unittest.TestCase):
    def test_each_notifier_kind_is_its_closed_event_and_others_are_not_pushed(self):
        self.assertEqual(push.event_of(told("interruption", "usage_limit")), CourierEvent.USAGE_LIMIT_DETECTED)
        self.assertIsNone(push.event_of(told("interruption", "network_transient")))
        for kind, event in (("resumed", "recovered"), ("failed", "failed"), ("stopped", "failed"),
                            ("needs_you", "needs_you"), ("memory_stopped", "stopped_unexpectedly"),
                            ("restarted", "restarted"), ("update_offered", "update_offered")):
            self.assertEqual(push.event_of(told(kind)), event, kind)
        for kind in ("starting", "unknown", "after_sleep", "demo", "near_limit", None, 3):
            self.assertIsNone(push.event_of(told(kind)), kind)
        self.assertIsNone(push.event_of("resumed"))

    def test_the_default_events_are_limit_recovered_failed_and_needs_you(self):
        for event in CourierEvent:
            if event == CourierEvent.TEST:
                continue
            self.assertEqual(push.picked(push.DEFAULT_EVENTS, event),
                             event in ("usage_limit_detected", "recovered", "failed", "needs_you"), event)
        self.assertEqual(push.EVENT_CHOICES[-1], 127)


class PushCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(capability="engine_present")
        self.plug_ = self.plug(PUSH_NOTICES)
        self.rt = self.plug_.runtime
        self.rt.arming.catalogs = statement.CATALOGS
        self.paused, self.launched = False, []
        code = self.rt._code_of(PUSH_NOTICES)
        code._paused = lambda paths: self.paused
        code._launch = lambda paths, now: self.launched.append(now)

    def on(self, state="armed", channels=("ntfy", "telegram")):
        result = self.arm(self.rt, CAP, state=state, warnings=[str(w) for w in self.rt.arming.warnings(PUSH_NOTICES)])
        self.assertTrue(result["done"], result)
        for channel in channels:
            self.rt.state.set_option(CAP, OptionKey(channel), 1, generation=self.rt.state.meta()["generation"],
                                     actor="dashboard")
        self.rt.states(fresh=True)

    def tell(self, facts):
        if self.plug_.wants(Point.NOTICE):
            self.plug_.notice(facts)

    def rows(self):
        with self.rt.state._read() as connection:
            if connection is None:
                return []
            return [dict(row) for row in connection.execute("SELECT * FROM outbox ORDER BY item_id")]


class NoticeTests(PushCase):
    def test_off_core_is_told_nothing_and_nothing_is_written(self):
        self.assertFalse(self.plug_.wants(Point.NOTICE))
        self.tell(told())
        self.assertEqual(self.rows(), [])

    def test_on_one_row_for_each_channel_switched_on_with_closed_words_only(self):
        self.on()
        self.tell(told(title="My secret project", thread_id="0a1b2c3d-0001-7000-8000-000000000001",
                       path=r"C:\Users\ExampleUser\repo"))
        rows = self.rows()
        self.assertEqual([(row["channel"], row["event"], row["category"], row["alias"], row["state"]) for row in rows],
                         [("ntfy", "recovered", "usage_limit", "task 3", "waiting"),
                          ("telegram", "recovered", "usage_limit", "task 3", "waiting")])
        self.rt.state.close()
        raw = Path(self.rt.state.path).read_bytes()
        for word in (b"My secret project", b"ExampleUser", b"0a1b2c3d-0001"):
            self.assertNotIn(word, raw)

    def test_an_event_not_picked_or_no_channel_on_writes_nothing(self):
        self.on(channels=())
        self.tell(told())
        self.assertEqual(self.rows(), [])
        self.on(channels=("ntfy",))
        self.tell(told("update_offered"))
        self.assertEqual(self.rows(), [], "update_offered is not picked by default")
        self.rt.state.set_option(CAP, OptionKey.PUSH_EVENTS, push.bit(CourierEvent.UPDATE_OFFERED),
                                 generation=self.rt.state.meta()["generation"], actor="dashboard")
        self.tell(told("update_offered"))
        self.tell(told("resumed"))
        self.assertEqual([row["event"] for row in self.rows()], ["update_offered"])

    def test_paused_or_unknown_nothing_is_written(self):
        self.on()
        for paused in (True, None):
            self.paused = paused
            self.tell(told())
        self.assertEqual(self.rows(), [])

    def test_watched_nothing_is_written_and_the_journal_keeps_what_it_would_have_done(self):
        self.on(state="shadow")
        self.tell(told())
        self.assertEqual(self.rows(), [])
        codes = [entry["code"] for entry in self.rt.state.journal(capability=CAP)]
        self.assertIn(JournalCode.WOULD_HAVE, codes)

    def test_at_most_thirty_an_hour(self):
        self.on()
        for _ in range(40):
            self.tell(told())
        self.assertEqual(len(self.rows()), 30)


class TickTests(PushCase):
    def test_the_courier_is_started_where_a_row_waits_and_never_waited_for(self):
        self.on()
        answer = self.rt.tick(None)
        self.assertIs(answer, DEFER, "nothing waits")
        self.tell(told())
        answer = self.rt.tick(None)
        began = time.monotonic()
        answer.run(lambda: None)
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(len(self.launched), 1)

    def test_a_courier_that_never_ends_leaves_the_tick_as_quick(self):
        """The real launch, with a Popen whose process never ends: the errand returns at once."""
        from unittest.mock import patch
        from codex_auto_resume_advanced.courier import launch
        from test_advanced_courier_process import Process
        self.on()
        self.tell(told())
        code = self.rt._code_of(PUSH_NOTICES)
        code._launch = lambda paths, now: launch.start_due(paths, now, popen=Process, adopt_it=lambda process: None)
        launch._STARTED.clear()
        self.addCleanup(launch._STARTED.clear)
        with patch("codex_auto_resume.startup.python_launcher", lambda: Path(r"C:\Python\pythonw.exe")):
            began = time.monotonic()
            self.rt.tick(None).run(lambda: None)
            self.assertLess(time.monotonic() - began, 1.0)


if __name__ == "__main__":
    unittest.main()
