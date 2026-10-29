"""Show OpenAI's service status (v0.6.20, courier/feed.py, engine/feed.py, surfaces.feed_view): one GET of a constant
address, reduced to two words and a count from recorded Statuspage replies - degraded, an outage, an oversized or
garbled reply unknown; read at P8 only while a recovery waits in a usage limit or a connection failure and the last
reading is old enough; shown on the Overview only while it says something is wrong; and never the input of a gate,
a plug answer or any decision.

No request reaches the network: the opener is a fake.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_courier_http import Opener, Reply  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.courier import feed  # noqa: E402
from codex_auto_resume_advanced.registry import STATUS_FEED  # noqa: E402

PACKAGE = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"


def summary(indicator="none", codex="operational", incidents=0, name="Codex in ChatGPT Desktop"):
    return json.dumps({"page": {"id": "x", "name": "OpenAI"}, "status": {"indicator": indicator, "description": "d"},
                       "components": [{"name": "APIs", "status": "major_outage"},
                                      {"name": name, "status": codex}],
                       "incidents": [{"name": "Something happened"}] * incidents}).encode()


class ParseTests(unittest.TestCase):
    def test_the_address_is_the_constant_status_page(self):
        self.assertEqual(feed.SUMMARY_URL, "https://status.openai.com/api/v2/summary.json")

    def test_recorded_replies_become_two_words_and_a_count(self):
        self.assertEqual(feed.parse(summary()), ("operational", "operational", 0))
        self.assertEqual(feed.parse(summary("minor", "degraded_performance", 2)), ("degraded", "degraded", 2))
        self.assertEqual(feed.parse(summary("major", "partial_outage", 1)), ("outage", "degraded", 1))
        self.assertEqual(feed.parse(summary("critical", "major_outage", 300)), ("outage", "outage", 99))
        self.assertEqual(feed.parse(summary("maintenance", "under_maintenance")), ("unknown", "unknown", 0))
        self.assertEqual(feed.parse(summary(name="ChatGPT")), ("operational", "unknown", 0), "no Codex component")

    def test_oversized_garbled_or_odd_replies_are_unknown(self):
        for raw in (b"x" * 70000, b"<html>", b"[]", b'{"status": "none"}', "é".encode("latin-1"), None,
                    json.dumps({"status": {"indicator": 3}, "components": "x", "incidents": "y"}).encode()):
            with self.subTest(raw=raw[:20] if raw else raw):
                self.assertEqual(feed.parse(raw)[1], "unknown")
        self.assertEqual(feed.parse(b"{" + b" " * 70000 + b"}"), feed.UNKNOWN)


class FeedCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(capability="engine_present")
        self.rt = self.runtime(STATUS_FEED)
        self.rt.arming.catalogs = statement.CATALOGS
        self.launched = []
        self.rt._code_of(STATUS_FEED)._launch = lambda paths, now: self.launched.append(now)

    def on(self):
        result = self.arm(self.rt, "status_feed", warnings=[str(w) for w in self.rt.arming.warnings(STATUS_FEED)])
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)


class View:
    def __init__(self, *categories):
        self.rows = [{"state": "waiting_reset", "category": category} for category in categories]

    def records_in(self, states):
        return [row for row in self.rows if row["state"] in states]


class RefreshTests(FeedCase):
    def test_a_reading_is_kept_and_counted_and_a_refusal_keeps_the_words(self):
        self.on()
        self.assertEqual(feed.refresh(self.rt, opener=Opener(Reply(200, summary("minor"))), now=ac.NOW),
                         ("degraded", "operational", 0))
        self.assertEqual(feed.read(self.rt.state), {"checked_at": ac.NOW, "word": "degraded",
                                                    "codex_word": "operational", "incidents": 0})
        failing = Opener(error=urllib.error.URLError(TimeoutError()))
        self.assertIsNone(feed.refresh(self.rt, opener=failing, now=ac.NOW + 600))
        self.assertEqual(feed.read(self.rt.state)["word"], "degraded")
        self.assertEqual(feed.read(self.rt.state)["checked_at"], ac.NOW + 600)
        (request, _timeout), = failing.requests
        self.assertEqual((request.get_method(), request.full_url), ("GET", feed.SUMMARY_URL))
        codes = [entry["code"] for entry in self.rt.state.journal(capability="status_feed")]
        self.assertEqual(codes[-2:], ["feed.checked", "feed.refused"])


class TickTests(FeedCase):
    def look(self, view, after=0):
        self.now += after
        answer = self.rt.tick(view)
        if answer is not DEFER:
            answer.run(lambda: None)

    def test_read_only_while_a_limit_or_connection_failure_waits(self):
        self.on()
        self.look(View())
        self.look(View("terminal_invalid"))
        self.assertEqual(self.launched, [])
        self.look(View("usage_limit"))
        self.assertEqual(len(self.launched), 1)
        self.look(View("network_transient"))
        self.assertEqual(len(self.launched), 2, "no reading kept yet: due again")

    def test_not_again_until_the_chosen_minutes_pass(self):
        self.on()
        feed.save(self.rt.state, ("degraded", "degraded", 1), self.now)
        self.look(View("usage_limit"), after=9 * 60)
        self.assertEqual(self.launched, [])
        self.look(View("usage_limit"), after=60)
        self.assertEqual(len(self.launched), 1)

    def test_off_nothing_is_read(self):
        self.look(View("usage_limit"))
        self.assertEqual(self.launched, [])


class SurfaceTests(FeedCase):
    def test_the_overview_line_only_while_it_is_on_and_something_is_wrong(self):
        feed.save(self.rt.state, ("degraded", "operational", 1), ac.NOW)
        self.assertEqual(surfaces.feed_view(self.rt), {}, "off")
        self.on()
        self.assertEqual(surfaces.feed_view(self.rt)["feed"]["word"], "degraded")
        self.assertIn("feed", surfaces.status(self.rt))
        for words in (("operational", "operational"), ("unknown", "unknown"), ("operational", "unknown")):
            feed.save(self.rt.state, (*words, 0), ac.NOW)
            self.assertEqual(surfaces.feed_view(self.rt), {}, words)
        feed.save(self.rt.state, ("operational", "outage", 0), ac.NOW)
        self.assertEqual(surfaces.feed_view(self.rt)["feed"]["codex_word"], "outage")


class NeverAGateTests(unittest.TestCase):
    def test_only_the_feed_s_own_modules_and_the_surfaces_read_the_feed_table(self):
        allowed = {"courier/feed.py", "engine/feed.py", "surfaces.py", "control/courier.py", "state/choices.py",
                   "state/schema.py", "state/journal.py", "registry.py"}
        readers = set()
        for path in PACKAGE.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\bFROM feed\b|\bINTO feed\b|courier\.feed|courier import feed|\bfeed_read\b|scoped\.feed\(",
                         text):
                readers.add(path.relative_to(PACKAGE).as_posix())
        self.assertLessEqual(readers, allowed)
        for name in ("runtime.py", "ledger.py", "arming.py", "plug.py"):
            self.assertNotIn("feed", (PACKAGE / name).read_text(encoding="utf-8").replace("feedback", ""), name)

    def test_its_code_answers_at_no_gate(self):
        from codex_auto_resume.domain.plug import Point
        self.assertEqual(STATUS_FEED.points, frozenset({Point.TICK}))


if __name__ == "__main__":
    unittest.main()
