# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The Advanced features page's cards say a failed measurement failed (the owner, 2026-10-31; v0.6.20 final).

The Codex account card says its sign-out and sign-in button is hidden because its measurement failed on this Codex where the
bridge says MAL failed (`measurement_failed`), and "until it has been measured" where there is no record. The same holds for
the lines that rest on a measurement: Keep a conversation going's held count (MK), the reset credit's past-the-next-one count
(MU) and its ask-first note (MR). Each reply is the real bridge's, with the failed flags the test sets; nothing reads Codex.

GUI test module: compiles real executables, so it runs on its own.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_page_failed_measurement.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, snapshot  # noqa: E402

MASK = "s•••@e•••.com"


def account(failed):
    return {"ok": True, "result": {"done": True, "refusal": None, "present": True, "plan": "plus", "kind": "chatgpt",
                                   "mask": MASK, "button": False, "measurement_failed": failed, "switch": None}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def shown(cls, bridge, capability, state, change=None, account_reply=None):
        cls.watched(bridge, capability, state=state)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-keep-going"] = [bridge("advanced-keep-going", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        if account_reply is not None:
            script["advanced-account"] = [account_reply]
        if change is not None:
            change(script)
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": capability},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_account_failed(cls, bridge):
        return cls.shown(bridge, "account_switch", "shadow", account_reply=account(True))

    @classmethod
    def scenario_account_unmeasured(cls, bridge):
        return cls.shown(bridge, "account_switch", "shadow", account_reply=account(False))

    @staticmethod
    def keep(script, failed):
        answer = script["advanced-keep-going"][0]["result"]
        answer["count_capped"], answer["count_failed"] = True, failed

    @classmethod
    def scenario_keep_failed(cls, bridge):
        return cls.shown(bridge, "keep_going", "shadow", lambda script: cls.keep(script, True))

    @classmethod
    def scenario_keep_unmeasured(cls, bridge):
        return cls.shown(bridge, "keep_going", "shadow", lambda script: cls.keep(script, False))

    @staticmethod
    def resets(script, failed):
        answer = script["advanced-resets"][0]["result"]
        answer["count_unproven"], answer["count_failed"], answer["credit_failed"] = True, failed, failed

    @classmethod
    def scenario_resets_failed(cls, bridge):
        return cls.shown(bridge, "reset_credit", "shadow", lambda script: cls.resets(script, True))

    @classmethod
    def scenario_resets_unmeasured(cls, bridge):
        return cls.shown(bridge, "reset_credit", "shadow", lambda script: cls.resets(script, False))

    def lines(self, name, title):
        result, expected = self.of(name)
        (look,) = result["looks"]
        words = expected["words"]
        card = next(card for card in look["cards"] if card and card[0] == words[title])
        return words, card

    def test_the_account_card_says_the_button_is_hidden_because_its_measurement_failed(self):
        words, card = self.lines("scenario_account_failed", "page.account.title")
        self.assertIn(words["page.account.guidance_failed"], card)
        self.assertNotIn(words["page.account.guidance"], card)
        self.assertIn("failed", words["page.account.guidance_failed"])

    def test_the_account_card_with_no_record_says_not_measured_yet(self):
        words, card = self.lines("scenario_account_unmeasured", "page.account.title")
        self.assertIn(words["page.account.guidance"], card)
        self.assertNotIn(words["page.account.guidance_failed"], card)

    def test_keep_going_says_its_count_is_held_because_the_measurement_failed(self):
        words, card = self.lines("scenario_keep_failed", "page.keep.title")
        self.assertIn(words["page.keep.capped_failed"].replace("{n}", "3"), card)
        self.assertNotIn(words["page.keep.capped"].replace("{n}", "3"), card)

    def test_keep_going_with_no_record_says_until_measured(self):
        words, card = self.lines("scenario_keep_unmeasured", "page.keep.title")
        self.assertIn(words["page.keep.capped"].replace("{n}", "3"), card)
        self.assertNotIn(words["page.keep.capped_failed"].replace("{n}", "3"), card)

    def test_the_reset_credit_card_says_its_count_and_its_ask_first_note_rest_on_a_failed_measurement(self):
        words, card = self.lines("scenario_resets_failed", "page.resets.credit.title")
        for failed, old in (("page.resets.unproven_failed", "page.resets.unproven"),
                            ("page.resets.ask.note_failed", "page.resets.ask.note")):
            self.assertIn(words[failed], card)
            self.assertNotIn(words[old], card)

    def test_the_reset_credit_card_with_no_record_says_until_measured(self):
        words, card = self.lines("scenario_resets_unmeasured", "page.resets.credit.title")
        for failed, old in (("page.resets.unproven_failed", "page.resets.unproven"),
                            ("page.resets.ask.note_failed", "page.resets.ask.note")):
            self.assertIn(words[old], card)
            self.assertNotIn(words[failed], card)


if __name__ == "__main__":
    unittest.main()
