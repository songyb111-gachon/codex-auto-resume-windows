"""The usage and token analytics' cards on the Advanced features page (v0.6.20, advanced/gui/AdvancedAnalytics.cs).

While usage_analytics is on, its column has a Pace card - each window the meter reads, how full it is, the change over
the last hour and, where the bridge gives one, around when it would be full beside its reset - and a Tokens card: one
flat line a project with its five numbers, its conversations under it on demand, a total line, and Save as CSV...,
which sends the path the save dialog answered (never a file there already unless the dialog asked). Where MTOK failed,
the list says it shows lifetime totals. Off, there is no card. The window is driven as the other page modules drive it
(pagecase.py); the analytics' answers are scripted, so nothing here reads a Codex home.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests -p test_advanced_page_analytics.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, fullest_analytics, sent, snapshot  # noqa: E402

ANALYTICS = "usage_analytics"
TARGET = "C:\\scratch\\usage.csv"


def answer(changes=None):
    found = fullest_analytics()
    found.update(changes or {})
    return {"ok": True, "result": found}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def armed(cls, bridge):
        cls.watched(bridge, "usage_meter", state="armed")
        cls.watched(bridge, ANALYTICS, state="armed")

    @classmethod
    def scenario_analytics(cls, bridge):
        """On: both cards; a project's conversations shown, then the CSV saved where the dialog said."""
        cls.armed(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-analytics"] = [answer()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": ANALYTICS},
                 {"do": "look"}, {"do": "analytics_toggle", "project": "a" * 16}, {"do": "look"},
                 {"do": "save_to", "path": TARGET},
                 {"do": "reply", "key": "advanced-analytics-csv",
                  "with": [{"ok": True, "result": {"done": True, "refusal": None, "rows": 3}}]},
                 {"do": "press", "button": "analytics_save"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_analytics_refused(cls, bridge):
        """On: a save the bridge refuses because the file is there says so, in the report card's words."""
        cls.armed(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-analytics"] = [answer()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": ANALYTICS},
                 {"do": "save_to", "path": TARGET},
                 {"do": "reply", "key": "advanced-analytics-csv",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "file_exists"}}]},
                 {"do": "press", "button": "analytics_save"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_analytics_lifetime(cls, bridge):
        """On, where MTOK failed: the list says it shows lifetime totals, and a pace with too few readings says so."""
        cls.armed(bridge)
        script = cls.opening(bridge, "en")
        lifetime = fullest_analytics()
        script["advanced-analytics"] = [answer({"route": "lifetime", "measured": "fail", "behind": False,
                                                "projects": lifetime["projects"][1:], "paces": lifetime["paces"][1:]})]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": ANALYTICS},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_analytics_off(cls, bridge):
        """Off: no card, whatever the bridge would answer."""
        script = cls.opening(bridge, "en")
        script["advanced-analytics"] = [answer()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": ANALYTICS},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- reading the cards
    @staticmethod
    def card(look, title):
        return next((card for card in look["cards"] if card and card[0] == title), None)

    def tokens_title(self, words, days=90):
        return words["page.analytics.tokens"].replace("{n}", str(days))

    def test_on_the_pace_and_the_tokens_are_shown_and_a_project_opens_on_demand(self):
        result, expected = self.of("scenario_analytics")
        words = expected["words"]
        shown, opened, saved = result["looks"]
        pace = self.card(shown, words["page.analytics.pace"])
        self.assertIsNotNone(pace, "the pace card is shown while the capability is on")
        text = "\n".join(pace)
        self.assertIn("87.5", text)
        self.assertIn("+12.5", text)
        self.assertIn(words["page.analytics.eta"].split("{time}")[0].strip(), text)
        self.assertIn(words["page.analytics.not_enough"], text, "the weekly window has too few readings")
        tokens = self.card(shown, self.tokens_title(words))
        self.assertIsNotNone(tokens)
        self.assertIn(words["page.analytics.behind"], tokens)
        project = [line for line in tokens if line.startswith("P" * 71)]
        self.assertEqual(len(project), 1, tokens)
        self.assertIn("9,876,543,210", project[0])
        self.assertIn(words["page.analytics.lifetime"].replace("{n}", "123,456,789"), project[0])
        self.assertTrue(any(line.startswith(words["page.analytics.other"] + " · ") for line in tokens), "no label: Other")
        self.assertTrue(any(line.startswith(words["page.analytics.total"] + " · ") for line in tokens))
        self.assertFalse(any(line.startswith("L" * 71) for line in tokens), "conversations only on demand")
        after = self.card(opened, self.tokens_title(words))
        self.assertEqual(len([line for line in after if line.startswith("L" * 71)]), 1, "shown once its button is pressed")
        self.assertNotIn("analytics_toggle", result["disabled"])

    def test_save_sends_the_path_the_dialog_answered_and_says_it_saved(self):
        result, expected = self.of("scenario_analytics")
        self.assertEqual(sent(result, "advanced-analytics-csv"), [{"days": 90, "path": TARGET, "replace": False}])
        saved = self.card(result["looks"][2], self.tokens_title(expected["words"]))
        self.assertIn(expected["words"]["page.report.saved"], saved)

    def test_a_refused_save_says_why(self):
        result, expected = self.of("scenario_analytics_refused")
        (shown,) = result["looks"]
        tokens = self.card(shown, self.tokens_title(expected["words"]))
        self.assertIn(expected["words"]["page.report.refused.file_exists"], tokens)

    def test_where_mtok_failed_the_list_says_it_shows_lifetime_totals(self):
        result, expected = self.of("scenario_analytics_lifetime")
        words = expected["words"]
        (shown,) = result["looks"]
        tokens = self.card(shown, self.tokens_title(words))
        self.assertIn(words["page.analytics.lifetime_only"], tokens)
        self.assertNotIn(words["page.analytics.behind"], tokens)
        self.assertTrue(any(words["page.analytics.lifetime"].replace("{n}", "987,654,321") in line for line in tokens))

    def test_turned_off_there_is_no_card(self):
        result, expected = self.of("scenario_analytics_off")
        (shown,) = result["looks"]
        words = expected["words"]
        self.assertIsNone(self.card(shown, words["page.analytics.pace"]))
        self.assertIsNone(self.card(shown, self.tokens_title(words)))
        self.assertEqual(sent(result, "advanced-analytics-csv"), [])


if __name__ == "__main__":
    unittest.main()
