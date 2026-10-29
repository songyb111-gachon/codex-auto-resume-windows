"""The Advanced features page's Codex account card (v0.6.20, account_switch: advanced/gui/AdvancedAccount.cs).

While Switch the Codex account is on or watched, its column has a card "Codex account": the account signed in - its plan
and its masked address, as the bridge answers advanced-account - and under it, until MAL has passed, how to switch in
Codex (the narrower route); once it has, and the capability is on, Sign out and sign in with another account..., which
asks first, then sends advanced-account-switch and reads the card again: "Waiting for the sign-in in your browser...",
with the button greyed, until the card says how it ended. Off, there is no card and nothing is read. The window is
driven as the other page modules drive it (pagecase.py); every advanced-account reply is the test's own, so no Codex
is asked.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402

CAP = "account_switch"
MASK = "s•••@e•••.com"


def account(button=False, switch=None, present=True):
    return {"ok": True, "result": {"done": True, "refusal": None, "present": present,
                                   "plan": "plus" if present else None, "kind": "chatgpt" if present else None,
                                   "mask": MASK if present else None, "button": button, "switch": switch}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def opened(cls, bridge, state, replies, more=(), answers=()):
        if state is not None:
            cls.watched(bridge, CAP, state=state)
        script = cls.opening(bridge, "en")
        script["advanced-account"] = list(replies)
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": CAP},
                 {"do": "look"}] + list(more)
        return "en", {"answers": list(answers), "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_unmeasured(cls, bridge):
        """On, MAL not passed: the account and how to switch in Codex; no button."""
        return cls.opened(bridge, "armed", [account()])

    @classmethod
    def scenario_switch(cls, bridge):
        """On, MAL passed: the button asks, sends the switch, and the card waits, then says how it ended."""
        more = [{"do": "reply", "key": "advanced-account-switch",
                 "with": [{"ok": True, "result": {"done": True, "refusal": None, "switch": "waiting"}}]},
                {"do": "reply", "key": "advanced-account", "with": [account(True, "waiting", present=None)]},
                {"do": "press", "button": "account_switch"}, {"do": "look"},
                {"do": "reply", "key": "advanced-account", "with": [account(True, "signed_in")]},
                {"do": "poll_account"}, {"do": "look"}]
        return cls.opened(bridge, "armed", [account(True)], more, answers=[True])

    @classmethod
    def scenario_declined(cls, bridge):
        """The question answered No: nothing is sent."""
        return cls.opened(bridge, "armed", [account(True)], [{"do": "press", "button": "account_switch"},
                                                           {"do": "look"}], answers=[False])

    @classmethod
    def scenario_signed_out_watched(cls, bridge):
        """Watched, signed out: the card says so, and offers no button."""
        return cls.opened(bridge, "shadow", [account(present=False)])

    @classmethod
    def scenario_off(cls, bridge):
        """Off: no card, and advanced-account is never asked."""
        return cls.opened(bridge, None, [account(True)])

    def card(self, look, words):
        found = [card for card in look["cards"] if card and card[0] == words["page.account.title"]]
        return found[0] if found else None

    def test_unmeasured_it_shows_the_account_and_how_to_switch_in_codex(self):
        result, expected = self.of("scenario_unmeasured")
        words = expected["words"]
        card = self.card(result["looks"][0], words)
        self.assertIsNotNone(card)
        self.assertIn(words["page.account.signed_in"].replace("{account}", "Plus · " + MASK), card)
        self.assertIn(words["page.account.guidance"], card)
        self.assertIsNone(result["looks"][0]["account_switch"])

    def test_the_button_asks_first_then_waits_and_says_how_it_ended(self):
        result, expected = self.of("scenario_switch")
        words = expected["words"]
        first, waiting, ended = result["looks"]
        self.assertTrue(first["account_switch"])
        self.assertEqual(result["asked"], [words["page.confirm.account_switch"]])
        self.assertEqual(sent(result, "advanced-account-switch"), [{}])
        self.assertIn(words["page.account.waiting"], self.card(waiting, words))
        self.assertFalse(waiting["account_switch"], "greyed while the sign-in waits")
        self.assertIn(words["page.account.result.signed_in"], self.card(ended, words))
        self.assertTrue(ended["account_switch"])

    def test_declined_nothing_is_sent(self):
        result, _expected = self.of("scenario_declined")
        self.assertEqual(sent(result, "advanced-account-switch"), [])

    def test_watched_and_signed_out_it_says_so_and_offers_no_button(self):
        result, expected = self.of("scenario_signed_out_watched")
        words = expected["words"]
        self.assertIn(words["page.account.signed_out"], self.card(result["looks"][0], words))
        self.assertIsNone(result["looks"][0]["account_switch"])

    def test_off_there_is_no_card_and_nothing_is_read(self):
        result, expected = self.of("scenario_off")
        self.assertIsNone(self.card(result["looks"][0], expected["words"]))
        self.assertEqual(sent(result, "advanced-account"), [])


if __name__ == "__main__":
    unittest.main()
