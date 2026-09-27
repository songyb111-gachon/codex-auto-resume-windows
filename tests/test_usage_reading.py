"""v0.6.11: Codex's usage, the last reading - kept in the heartbeat, shown with its age.

The engine reads usage when a recovery is due and nowhere else, as v0.6.10 did; the watcher now
keeps the last reading that had windows in its heartbeat, and the Overview, Pending, the popup, the
panel and get_status show it with how long ago it was made. What is kept is the allowlist the reply
was already cut down to - bucket, window, share used, length and reset time (B10, D2) - and nothing
else: no account, no plan, no credit. A stored reading that is not exactly that is no reading.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.codex.usage import parse_usage  # noqa: E402
from codex_auto_resume.domain import usage  # noqa: E402
from codex_auto_resume.runtime.loop import WatchLoop  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.ui import words  # noqa: E402
from codex_auto_resume.ui.popup import model  # noqa: E402
from test_engine import EngineCase  # noqa: E402

NOW = 1788628000.0
FIVE_HOURS = {"bucket": "codex", "window": "primary", "used_percent": 100, "window_minutes": 300,
              "reset_at": int(NOW) + 2540}
WEEK = {"bucket": "codex", "window": "secondary", "used_percent": 62.7, "window_minutes": 10080,
        "reset_at": int(NOW) + 3 * 86400}
REPLY = {"rateLimitsByLimitId": {"codex": {
    "primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": int(NOW) + 2540},
    "secondary": {"usedPercent": 62.7, "windowDurationMins": 10080, "resetsAt": int(NOW) + 3 * 86400},
    "planType": "example-plan", "credits": {"balance": 3}}},
    "account": {"email": "example-user@example.invalid"}}


def english(key, **fields):
    return l10n.text(key, "en", **fields)


class AllowlistTests(unittest.TestCase):
    def test_the_reply_is_kept_as_its_allowlisted_numbers_and_nothing_else(self):
        kept = usage.windows_of(parse_usage(REPLY))
        self.assertEqual(kept, [FIVE_HOURS, WEEK])
        text = usage.encode(kept)
        for leaked in ("example", "plan", "credit", "balance", "email", "account"):
            self.assertNotIn(leaked, text)
        self.assertEqual(usage.decode(text), kept)

    def test_anything_that_is_not_exactly_a_reading_is_none(self):
        bad = [dict(FIVE_HOURS, plan="x"), dict(FIVE_HOURS, bucket="team-account"), dict(FIVE_HOURS, window="third"),
               dict(FIVE_HOURS, used_percent=float("nan")), dict(FIVE_HOURS, used_percent=True),
               dict(FIVE_HOURS, used_percent=-1), dict(FIVE_HOURS, window_minutes=0),
               dict(FIVE_HOURS, window_minutes=5.0), dict(FIVE_HOURS, reset_at=12.5),
               {key: FIVE_HOURS[key] for key in usage.KEYS if key != "reset_at"}]
        for window in bad:
            with self.subTest(window=window):
                self.assertIsNone(usage.windows_of({"windows": [window]}))
                self.assertIsNone(usage.encode([window]))
        self.assertIsNone(usage.windows_of({"available": None, "reason": "usage_probe_unavailable"}))
        self.assertIsNone(usage.windows_of({"windows": []}))
        self.assertIsNone(usage.windows_of({"windows": [FIVE_HOURS] * (usage.MAX_WINDOWS + 1)}))
        for text in (None, "", "{", "[]", json.dumps({"windows": [FIVE_HOURS]}), "x" * (usage.MAX_TEXT + 1)):
            with self.subTest(text=text):
                self.assertIsNone(usage.decode(text))


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / "state")
        self.addCleanup(self.store.close)

    def beat(self, usage_reading=None):
        self.store.heartbeat(NOW, pid=1, session_id="example", started_at=NOW - 60, ok=True,
                             engine_state="verified", code_version="0.0.0", usage=usage_reading)

    def test_no_reading_until_one_is_made(self):
        self.beat()
        self.assertIsNone(self.store.watcher_status()["usage"])

    def test_the_last_reading_stays_until_another_replaces_it(self):
        self.beat((NOW - 120, [FIVE_HOURS, WEEK]))
        self.beat()
        self.assertEqual(self.store.watcher_status()["usage"], {"read_at": NOW - 120, "windows": [FIVE_HOURS, WEEK]})
        self.beat((NOW - 5, [WEEK]))
        self.assertEqual(self.store.watcher_status()["usage"], {"read_at": NOW - 5, "windows": [WEEK]})

    def test_a_reading_that_is_not_one_is_never_written_and_never_read(self):
        self.beat((NOW, [dict(WEEK, account="x")]))
        self.beat(("soon", [WEEK]))
        self.assertIsNone(self.store.watcher_status()["usage"])
        self.beat((NOW, [WEEK]))
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE watcher_status SET usage=?", (json.dumps([dict(WEEK, credits=3)]),))
        self.assertIsNone(self.store.watcher_status()["usage"])

    def test_the_watcher_hands_a_reading_over_once(self):
        class Engine:
            reading = (NOW - 120, [FIVE_HOURS])

            def last_usage(self):
                return self.reading
        loop, engine = WatchLoop(), Engine()
        self.assertEqual(loop._new_reading(engine), engine.reading)
        self.assertIsNone(loop._new_reading(engine), "the same reading is not written again")
        engine.reading = (NOW, [WEEK])
        self.assertEqual(loop._new_reading(engine), engine.reading)
        self.assertIsNone(loop._new_reading(None))


class EngineTests(EngineCase):
    def test_the_engine_keeps_what_it_read_and_reads_nothing_for_it(self):
        self.assertIsNone(self.h.engine.last_usage())
        reads = []
        self.h.backend.usage = lambda: reads.append(1) or parse_usage(REPLY)
        self.ready_after_reset()
        self.h.tick()
        self.assertTrue(reads, "a recovery came due, so usage was read - as v0.6.10 read it")
        before = len(reads)
        reading = self.h.engine.last_usage()
        self.assertEqual(reading[1], [FIVE_HOURS, WEEK])
        for _ in range(3):
            self.h.engine.last_usage()
        self.assertEqual(len(reads), before, "asking for the last reading reads nothing")

    def test_a_failed_read_leaves_no_reading(self):
        self.h.backend.usage_result = {"available": None, "reset_at": None, "limit_type": "unknown",
                                       "reason": "usage_probe_unavailable"}
        self.ready_after_reset()
        self.h.tick()
        self.assertIsNone(self.h.engine.last_usage())


class WordsTests(unittest.TestCase):
    def test_a_window_is_named_by_its_length(self):
        self.assertEqual([words.window_name(minutes, english) for minutes in (300, 10080, 1440, 2880, 45, None, 0)],
                         ["5-hour", "weekly", "1-day", "2-day", "45-minute", "limit", "limit"])
        self.assertEqual(words.share({"used_percent": 99.6}), 99)
        self.assertEqual(words.share({"used_percent": 130}), 100)

    def test_the_popup_says_the_reading_with_its_age(self):
        reading = {"read_at": NOW - 120, "windows": [dict(FIVE_HOURS, reset_at=None), dict(WEEK, reset_at=None)]}
        self.assertEqual(words.usage_line(reading, english, NOW),
                         "Codex usage, read 2m ago: 5-hour 100% · weekly 62%")
        self.assertIsNone(words.usage_line(None, english, NOW))
        status = {"watcher": {"usage": reading}}
        view = model.view_model([], status, l10n.catalog("en"), NOW)
        self.assertEqual(view["usage_note"], "Codex usage, read 2m ago: 5-hour 100% · weekly 62%")
        self.assertIsNone(model.view_model([], {"watcher": {"usage": None}}, l10n.catalog("en"), NOW)["usage_note"])

    def test_a_reset_later_today_is_its_time_and_any_other_its_day_and_time(self):
        today = time.mktime(time.localtime(NOW)[:3] + (12, 0, 0, 0, 0, -1))
        self.assertEqual(words.clock_time(today + 3600, today), "13:00")
        self.assertEqual(words.clock_time(today + 3 * 86400, today),
                         time.strftime("%Y-%m-%d %H:%M", time.localtime(today + 3 * 86400)))

    @unittest.skipUnless(shutil.which("node"), "needs Node to run the panel's own code")
    def test_the_panel_says_it_as_the_popup_does(self):
        from test_mcpui_v063 import run_javascript
        reading = {"read_at": NOW - 7200, "windows": [dict(FIVE_HOURS, reset_at=None), WEEK]}
        panel = run_javascript(["age", "windowName", "clockTime", "usageLine", "fill", "t"],
                               "process.stdout.write(JSON.stringify(usageLine(%s, %r)));" % (json.dumps(reading), NOW))
        self.assertEqual(panel, words.usage_line(reading, english, NOW))


if __name__ == "__main__":
    unittest.main()
