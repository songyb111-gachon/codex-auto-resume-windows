"""The loopback API's card and Telegram's on the Advanced features page (v0.6.22, advanced/gui/AdvancedRemote.cs).

While Read this PC's status from a browser or a script is on, its column has "Address and token": how the server stands, the
address with no token in it, whether a token is kept, Copy address and New token... - and off, no card and no read. Copy
address asks the bridge for the address carrying the token and hands it to the clipboard - here, to the test's list - and
the window keeps it nowhere; New token... asks first once there is a token to replace. The window is driven as the other
page modules drive it (pagecase.py); its card is read from replies made here, never from Credential Manager.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import PageCase, sent, snapshot  # noqa: E402

API = "local_api"
TELEGRAM = "telegram_remote"
ADDRESS = "http://127.0.0.1:47615/"
COPIED = ADDRESS + "#made-up-token-for-the-test"


def card(token=True, state="running", lan=False):
    return {"ok": True, "result": {"done": True, "refusal": None, "port": 47615, "url": ADDRESS, "token_saved": token,
                                   "state": state, "lan": lan, "actions": False}}


def telegram(paired=True, token=True, state="running", also=False, pairing=False):
    return {"ok": True, "result": {"done": True, "refusal": None, "paired": paired, "token_saved": token, "pairing": pairing,
                                   "state": state, "continue": also}}


def done(**more):
    return {"ok": True, "result": dict({"done": True, "refusal": None}, **more)}


class PageTests(PageCase):
    @classmethod
    def scenario_on(cls, bridge):
        """On, a token kept: the card; Copy address; a new token after asking."""
        cls.watched(bridge, API, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-api"] = [card()] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": API}, {"do": "look"},
                 {"do": "reply", "key": "advanced-api", "with": [done(copy_url=COPIED)]},
                 {"do": "remote", "button": "copy api"}, {"do": "look"},
                 {"do": "answer", "with": [True]},
                 {"do": "reply", "key": "advanced-api-token-new", "with": [done(copy_url=COPIED + "2")]},
                 {"do": "reply", "key": "advanced-api", "with": [card()] * 4},
                 {"do": "remote", "button": "token api"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_declined(cls, bridge):
        """A token kept, and the person says no to replacing it: nothing is asked of the bridge."""
        cls.watched(bridge, API, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-api"] = [card()] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": API},
                 {"do": "answer", "with": [False]}, {"do": "remote", "button": "token api"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_port_taken(cls, bridge):
        cls.watched(bridge, API, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-api"] = [card(token=True, state="port_taken")] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": API}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_no_token(cls, bridge):
        """On, none kept yet: no Copy address, and New token... asks nothing, there being nothing to replace."""
        cls.watched(bridge, API, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-api"] = [card(token=False, state="port_taken", lan=True)] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": API}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_off(cls, bridge):
        script = cls.opening(bridge, "en")
        script["advanced-api"] = [card()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": API}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_telegram(cls, bridge):
        """On, paired: the card and its four commands; Pair this chat shows the code to send the bot."""
        cls.watched(bridge, "push_notices", state="armed")
        cls.watched(bridge, TELEGRAM, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-remote-pair-state"] = [telegram()] * 4 + [telegram(pairing=True)] * 4
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": TELEGRAM}, {"do": "look"},
                 {"do": "reply", "key": "advanced-remote-pair-state", "with": [telegram(pairing=True)] * 4},
                 {"do": "reply", "key": "advanced-remote-pair-start", "with": [done(code="042317", expires_at=1.0)]},
                 {"do": "remote", "button": "pair telegram"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_telegram_more(cls, bridge):
        """Not paired, no token, stopped, and the second capability on: its two commands listed, no Pair."""
        cls.watched(bridge, "push_notices", state="armed")
        cls.watched(bridge, TELEGRAM, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-remote-pair-state"] = [telegram(paired=False, token=False, state="stopped", also=True)] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": TELEGRAM}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_telegram_off(cls, bridge):
        script = cls.opening(bridge, "en")
        script["advanced-remote-pair-state"] = [telegram()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": TELEGRAM}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    def card(self, look, title):
        return next((each for each in look["cards"] if each[0] == title), None)

    def test_on_the_card_says_how_it_stands_and_the_address_without_its_token(self):
        result, expected = self.of("scenario_on")
        words = expected["words"]
        first = result["looks"][0]
        where = self.card(first, words["page.api.card"])
        self.assertIsNotNone(where, first["cards"])
        self.assertIn(words["page.api.state.running"], where)
        self.assertTrue(any(ADDRESS in line for line in where))
        self.assertFalse(any("#" in line for line in where), "the token is never drawn")
        self.assertIn(words["page.api.token_kept"], where)
        self.assertEqual(first["remote_buttons"], ["copy api", "token api"])

    def test_copy_address_asks_with_copy_and_only_then_is_the_token_handed_on(self):
        result, _expected = self.of("scenario_on")
        self.assertEqual(result["looks"][0]["remote_copied"], [])
        self.assertIn({"copy": True}, sent(result, "advanced-api"))
        self.assertEqual(result["looks"][1]["remote_copied"], [COPIED])
        self.assertEqual(result["disabled"], [])

    def test_a_new_token_asks_first_and_is_copied(self):
        result, _expected = self.of("scenario_on")
        self.assertEqual(sent(result, "advanced-api-token-new"), [{}])
        self.assertEqual(result["looks"][2]["remote_copied"], [COPIED, COPIED + "2"])

    def test_it_asks_first_and_a_no_makes_no_token(self):
        """Fails with the question reverted: a press would make the old address useless with no word."""
        result, _expected = self.of("scenario_declined")
        self.assertEqual(sent(result, "advanced-api-token-new"), [])
        self.assertEqual(result["looks"][0]["remote_copied"], [])

    def test_with_no_token_there_is_no_copy_and_the_card_says_what_is_wrong(self):
        result, expected = self.of("scenario_no_token")
        words = expected["words"]
        look = result["looks"][0]
        where = self.card(look, words["page.api.card"])
        self.assertIn(words["page.api.no_token"], where)
        self.assertIn(words["page.api.state.port_taken"], where)
        self.assertIn(words["page.api.lan"], where)
        self.assertEqual(look["remote_buttons"], ["token api"])

    def test_while_another_program_holds_the_port_there_is_no_copy(self):
        """R7: fails with the card offering Copy address whatever the server's state."""
        result, expected = self.of("scenario_port_taken")
        self.assertEqual(result["looks"][0]["remote_buttons"], ["token api"])

    def test_telegram_s_card_lists_what_may_be_sent_and_pairing_shows_the_code(self):
        result, expected = self.of("scenario_telegram")
        words = expected["words"]
        first = self.card(result["looks"][0], words["page.remote.card"])
        self.assertIsNotNone(first, result["looks"][0]["cards"])
        self.assertIn(words["page.remote.state.running"], first)
        self.assertIn(words["page.remote.paired"], first)
        for name in ("status", "list", "cancel", "pause"):
            self.assertIn(words["page.remote.command." + name], first)
        for name in ("continue", "lift_pause"):
            self.assertNotIn(words["page.remote.command." + name], first, "only while that is on")
        self.assertEqual(result["looks"][0]["remote_buttons"], ["pair telegram"])
        self.assertEqual(sent(result, "advanced-remote-pair-start"), [{}])
        self.assertIn(words["page.courier.pair_code"].replace("{code}", "042317"),
                      self.card(result["looks"][1], words["page.remote.card"]))

    def test_telegram_s_card_with_nothing_saved_says_so_and_offers_no_pairing(self):
        result, expected = self.of("scenario_telegram_more")
        words = expected["words"]
        look = result["looks"][0]
        where = self.card(look, words["page.remote.card"])
        self.assertIn(words["page.remote.not_paired"], where)
        self.assertIn(words["page.remote.state.stopped"], where)
        for name in ("continue", "lift_pause"):
            self.assertIn(words["page.remote.command." + name], where)
        self.assertEqual(look["remote_buttons"], [])

    def test_telegram_off_there_is_no_card_and_it_is_not_read(self):
        result, expected = self.of("scenario_telegram_off")
        self.assertIsNone(self.card(result["looks"][0], expected["words"]["page.remote.card"]))
        self.assertEqual(sent(result, "advanced-remote-pair-state"), [])

    def test_off_there_is_no_card_and_it_is_not_read(self):
        result, expected = self.of("scenario_off")
        self.assertIsNone(self.card(result["looks"][0], expected["words"]["page.api.card"]))
        self.assertEqual(result["looks"][0]["remote_buttons"], [])
        self.assertEqual(sent(result, "advanced-api"), [])


if __name__ == "__main__":
    unittest.main()
