# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The Dashboard asks for one status-feed reading when it opens (v0.6.22 reachability audit, M16).

The status feed's statement promises a reading "once when the Dashboard opens" (statement.status_feed.does), and the bridge
answers `advanced-feed-refresh` (control/courier.py feed_refresh), but no window sent it. The window now sends it once,
after the first Advanced listing it reads says the capability stands on (its state in the list the window already reads:
no new status field); watched or off it sends nothing, and later reads do not send it again. The answer is not read - the
next snapshot's feed shows it - and nothing else in the window sends the command. The window is driven as the other page
modules drive it (pagecase.py), against the real bridge's listing of a home of its own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest advanced/tests/test_advanced_page_feed_refresh.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guiscan  # noqa: E402
from advancedcase import ROOT  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402

FEED = "status_feed"


def scenario(bridge, state):
    if state is not None:
        PageCase.watched(bridge, FEED, state=state)
    script = PageCase.opening(bridge, "en")
    # Opened, then every read the page makes again: a second snapshot and the page shown.
    steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "snapshot", "reply": snapshot()}]
    return "en", {"script": script, "steps": steps}, {}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def scenario_on(cls, bridge):
        return scenario(bridge, "armed")

    @classmethod
    def scenario_watched(cls, bridge):
        return scenario(bridge, "shadow")

    @classmethod
    def scenario_off(cls, bridge):
        return scenario(bridge, None)

    def test_on_it_asks_for_one_reading_once_however_often_the_page_is_read(self):
        result, _expected = self.of("scenario_on")
        self.assertEqual(sent(result, "advanced-feed-refresh"), [{}])
        self.assertGreater(len(sent(result, "advanced-list")), 1, "the page read the list again, and did not ask again")

    def test_watched_or_off_it_asks_for_nothing(self):
        for name in ("scenario_watched", "scenario_off"):
            with self.subTest(name):
                result, _expected = self.of(name)
                self.assertEqual(sent(result, "advanced-feed-refresh"), [])


class SourceTests(unittest.TestCase):
    def test_only_the_listing_hook_sends_it_and_a_failure_says_nothing(self):
        courier = (ROOT / "advanced" / "gui" / "AdvancedCourier.cs").read_text(encoding="utf-8")
        hook = guiscan._block(courier, courier.index("private void FeedListingApplied"))
        self.assertIn('Str(item, "state") != StateArmed', hook)
        self.assertIn("if (feedAsked || advancedListing == null) return;", hook)
        self.assertIn('AdvancedCall("advanced-feed-refresh", "{}", false, delegate(Dictionary<string, object> reply) { });', hook)
        sources = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "advanced" / "gui").glob("*.cs"))
        sources += "".join(path.read_text(encoding="utf-8") for path in (ROOT / "gui").glob("*.cs"))
        self.assertEqual(sources.count('"advanced-feed-refresh"'), 1)
        page = (ROOT / "advanced" / "gui" / "AdvancedPage.cs").read_text(encoding="utf-8")
        self.assertIn("FeedListingApplied();", guiscan._block(page, page.index("private void ShowAdvancedList")))


if __name__ == "__main__":
    unittest.main()
