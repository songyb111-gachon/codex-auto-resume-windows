"""The courier's cards on the Advanced features page, and the status feed's line on the Overview (v0.6.20,
advanced/gui/AdvancedCourier.cs).

While Send notices to your phone or inbox is on, its column has "Where notices go" - each channel saved or not, its
switch, its boxes and Save, Forget, Send a test and, for Telegram, Pair this chat - and "Which notices go", a switch for
each event; the Choices card shows none of them again. Save sends the boxes once (advanced-courier-save) and clears
them; Send a test says the courier's one word; Pair this chat shows the code to send the bot. Off, there is no card. The
Overview gains "OpenAI status" only while the status carries a feed that says something is wrong. The window is driven
as the other page modules drive it (pagecase.py); its card is read from a reply made here, never from Credential
Manager.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import PageCase, sent, snapshot  # noqa: E402

PUSH = "push_notices"
TOPIC = "https://ntfy.example.com/a-topic-made-up-for-the-test"
EVENTS = ["usage_limit_detected", "recovered", "failed", "needs_you", "stopped_unexpectedly", "restarted",
          "update_offered"]


def courier(saved=("ntfy",), pairing=False):
    rows = [{"channel": channel, "on": channel in saved, "saved": channel in saved, "refused_today": 0,
             "tripped": False} for channel in ("ntfy", "webhook", "telegram", "email")]
    return {"ok": True, "result": {"done": True, "refusal": None, "channels": rows, "events": 15,
                                   "event_order": EVENTS,
                                   "telegram": {"token_saved": True, "paired": False, "pairing": pairing},
                                   "feed": None}}


def done(**more):
    return {"ok": True, "result": dict({"done": True, "refusal": None}, **more)}


class PageTests(PageCase):
    @classmethod
    def scenario_courier(cls, bridge):
        """On: both cards; a topic typed and saved; a test sent; Telegram paired."""
        cls.watched(bridge, PUSH, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-courier"] = [courier(pairing=True)] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": PUSH}, {"do": "look"},
                 {"do": "reply", "key": "advanced-courier-save", "with": [done(saved=True)]},
                 {"do": "courier_type", "into": "ntfy.url", "text": TOPIC},
                 {"do": "courier", "button": "save ntfy"},
                 {"do": "reply", "key": "advanced-courier-test", "with": [done(outcome="sent")]},
                 {"do": "courier", "button": "test ntfy"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-courier-save", "with": [done(code="042317", expires_at=1.0)]},
                 {"do": "courier", "button": "pair telegram"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_courier_off(cls, bridge):
        script = cls.opening(bridge, "en")
        script["advanced-courier"] = [courier()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": PUSH}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_feed(cls, bridge):
        """The Overview's line: shown for an outage, gone when the status carries none."""
        script = cls.opening(bridge, "en")
        wrong = snapshot()
        wrong["status"]["advanced"]["feed"] = {"word": "operational", "codex_word": "outage", "incidents": 1,
                                               "checked_at": 1.0}
        steps = [{"do": "snapshot", "reply": wrong}, {"do": "page", "name": "overview"}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    def card(self, look, title):
        return next((card for card in look["cards"] if card[0] == title), None)

    def test_on_both_cards_and_the_choices_card_shows_none_of_their_switches(self):
        result, expected = self.of("scenario_courier")
        words = expected["words"]
        first = result["looks"][0]
        where = self.card(first, words["page.courier.title"])
        self.assertIsNotNone(where, first["cards"])
        for channel in ("ntfy", "webhook", "telegram", "email"):
            self.assertIn(words["page.courier.channel." + channel], where)
        self.assertIn(words["page.courier.saved"], where)
        events = self.card(first, words["page.courier.events"])
        self.assertIsNotNone(events)
        for event in EVENTS:
            self.assertIn(words["page.push." + event], events)
        choices = self.card(first, words["page.options"])
        self.assertTrue(choices is None or not any(words["page.push." + event] in choices for event in EVENTS))

    def test_save_sends_the_boxes_once_a_test_says_its_word_and_pairing_shows_the_code(self):
        result, expected = self.of("scenario_courier")
        words = expected["words"]
        self.assertEqual(sent(result, "advanced-courier-save")[0], {"channel": "ntfy", "url": TOPIC})
        self.assertEqual(sent(result, "advanced-courier-test"), [{"channel": "ntfy"}])
        after_test = result["looks"][1]
        self.assertIn(words["page.courier.result.sent"], self.card(after_test, words["page.courier.title"]))
        self.assertEqual(sent(result, "advanced-courier-save")[1], {"channel": "telegram", "pair": True})
        paired = self.card(result["looks"][2], words["page.courier.title"])
        self.assertIn(words["page.courier.pair_code"].replace("{code}", "042317"), paired)
        self.assertEqual(result["disabled"], [])

    def test_off_there_is_no_card(self):
        result, expected = self.of("scenario_courier_off")
        self.assertIsNone(self.card(result["looks"][0], expected["words"]["page.courier.title"]))
        self.assertEqual(result["looks"][0]["courier_buttons"], [])

    def test_the_overview_says_openai_s_status_only_while_something_is_wrong(self):
        result, expected = self.of("scenario_feed")
        words = expected["words"]
        shown, gone = result["looks"]
        self.assertEqual(shown["feed"], words["page.feed.outage"])
        self.assertIsNone(gone["feed"])


if __name__ == "__main__":
    unittest.main()
