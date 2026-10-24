"""The Dashboard's Advanced features page in the window itself: the reset actions (v0.6.14) and Pending's scheduled
group.

The window is compiled once for this module and every scenario_* below runs in one window process
(pagecase.PageCase); each makes its replies with this edition's real bridge in a home of its own, so nothing
here reads the real installation, the real Software\\Policies keys or a real Codex.

Held here: a message at a reset and a reset credit's rules are added from their forms, which offer the
windows, which reset, and the snapshot's conversations, asking first, and are cancelled, let go on counting
and used now, each request one the real bridge takes; Pending shows each rule still to act with Cancel,
read when the status's counts change; Longer reset messages says what it lets a message be.

GUI test module: compiles real executables, so it runs on its own.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_page_resets.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from pagecase import CSC, POWERSHELL, Bridge, PageCase, sent, snapshot  # noqa: E402


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    """The page driven as a person would, every scenario of this module in one window process."""

    # ---------------------------------------------------------------- the reset actions (AdvancedResets.cs)
    WORDS = "SENTINEL-reset: carry on with the release notes."

    @staticmethod
    def credit_rules(bridge):
        """Using a reset credit on, through the real bridge: a rule due that waits for a click (1), one held over a
        gap (2), the 5-hour window full now and the credits read - the same ids and generation in every home."""
        from codex_auto_resume_advanced.engine import resetwatch
        PageTests.watched(bridge, "reset_credit", state="armed")
        state = bridge.plug.runtime.state
        rules = []
        for ordinal in (1, 2):
            added = bridge("advanced-reset-add", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": ordinal,
                                                  "ask_first": True,
                                                  "generation": bridge("advanced-list", {})["result"]["generation"]})
            assert added["result"]["done"], added
            rules.append(added["result"]["rule"])
        state.change_rule(rules[0], state="ready", reason="ask_first", due_at=ac.NOW)
        state.change_rule(rules[1], state="held", reason="count_gap")
        state.save_windows([dict(resetwatch.blank("codex", 300), open_reset_at=int(ac.NOW) + 3600, open_full=True,
                                 seen_at=int(ac.NOW))])
        state.set_reading(read_at=int(ac.NOW), credits=3, expiry_known=1, nearest_expiry=int(ac.NOW) + 5 * 86400)
        return rules

    @classmethod
    def scenario_reset_message(cls, bridge):
        """A message at a reset on: the form offers the windows, which reset - only the next for the weekly one - and
        the snapshot's conversations; Add waits for words; added, asked first, the rule is a line with Cancel, which
        sends at once; declined, nothing is sent."""
        cls.watched(bridge, "reset_message", state="armed")
        script = cls.opening(bridge, "en")
        generation = script["advanced-list"][0]["result"]["generation"]
        reply = snapshot()
        thread = reply["pending"][1]["thread_id"]
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        added = bridge("advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 3,
                                              "thread_id": thread, "words": cls.WORDS, "generation": generation})
        after, listed = bridge("advanced-resets", {}), bridge("advanced-list", {})
        rule = added["result"]["rule"]
        cancelled = bridge("advanced-reset-cancel", {"rule": rule, "generation": listed["result"]["generation"]})
        gone, relisted = bridge("advanced-resets", {}), bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": "reset_message"},
                 {"do": "look"},                                                       # 0: no message yet
                 {"do": "reset_add", "family": "codex 10080"}, {"do": "look"},         # 1: weekly, no words: no Add
                 {"do": "reply", "key": "advanced-reset-add", "with": [added]},
                 {"do": "reply", "key": "advanced-resets", "with": [after]},
                 {"do": "reply", "key": "advanced-list", "with": [listed]},
                 {"do": "reset_add", "family": "codex 300", "ordinal": "3", "thread": thread, "words": cls.WORDS},
                 {"do": "look"},                                                       # 2: added
                 {"do": "reply", "key": "advanced-reset-cancel", "with": [cancelled]},
                 {"do": "reply", "key": "advanced-resets", "with": [gone]},
                 {"do": "reply", "key": "advanced-list", "with": [relisted]},
                 {"do": "reset_cancel", "rule": rule}, {"do": "look"},                 # 3: cancelled
                 {"do": "reset_add", "family": "codex 300", "ordinal": "1", "thread": thread, "words": "x"}]
        return "en", {"answers": [True, False], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "thread": thread, "rule": rule,
            "generations": [generation, listed["result"]["generation"]], "pending": reply["pending"]}

    @classmethod
    def scenario_reset_credit(cls, bridge):
        """Using a reset credit on: the reading, each rule a line - Go on counting for the held one, Use a reset credit
        now... for the due one and for the window full now - and a rule added with how often and Ask me first."""
        due, held = cls.credit_rules(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        # As where MU is not measured on the Codex in force: the count past the next one is unproven.
        script["advanced-resets"][0]["result"]["count_unproven"] = True
        done = {"ok": True, "result": {"done": True, "refusal": None, "rule": 9}}
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "reset_credit"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-reset-add", "with": [done]},
                 {"do": "reset_add", "family": "codex 10080", "repeat": "every", "ask": "ask"},
                 {"do": "reply", "key": "advanced-credit-now", "with": [done]},
                 {"do": "credit_now", "family": "codex 300"},
                 {"do": "credit_now", "rule": due},
                 {"do": "reply", "key": "advanced-reset-go-on", "with": [done]},
                 {"do": "reset_go_on", "rule": held}, {"do": "look"}]
        return "en", {"answers": [True, True, False], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "due": due, "held": held,
            "generation": script["advanced-list"][0]["result"]["generation"]}

    @classmethod
    def scenario_scheduled(cls, bridge):
        """Pending's one list (v0.6.19): no rule row while nothing is read; read when the status's counts change, a row for
        each rule still to act, with Cancel - and Go on counting for one held over a gap; not read again while they stay;
        let go on, and cancelled, read again and the row gone."""
        cls.watched(bridge, "reset_message", state="armed")
        reply = snapshot(on=1)
        thread = reply["pending"][0]["thread_id"]
        added = bridge("advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1,
                                              "thread_id": thread, "words": cls.WORDS,
                                              "generation": bridge("advanced-list", {})["result"]["generation"]})
        rule = added["result"]["rule"]
        bridge.plug.runtime.state.change_rule(rule, state="held", reason="count_gap")
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        counted = copy.deepcopy(reply)
        counted["status"]["advanced"].update(surfaces.status(bridge.plug.runtime))
        cancelled = bridge("advanced-reset-cancel", {"rule": rule,
                                                     "generation": script["advanced-list"][0]["result"]["generation"]})
        gone = bridge("advanced-resets", {})
        steps = [{"do": "snapshot", "reply": reply}, {"do": "page", "name": "pending"}, {"do": "look"},
                 {"do": "snapshot", "reply": counted}, {"do": "look"},
                 {"do": "snapshot", "reply": counted}, {"do": "look"},
                 {"do": "reply", "key": "advanced-reset-go-on",
                  "with": [{"ok": True, "result": {"done": True, "refusal": None, "rule": rule}}]},
                 {"do": "scheduled_go_on", "rule": rule},
                 {"do": "reply", "key": "advanced-reset-cancel", "with": [cancelled]},
                 {"do": "reply", "key": "advanced-resets", "with": [gone]},
                 {"do": "scheduled_cancel", "rule": rule}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "rule": rule, "pending": reply["pending"],
            "counts": counted["status"]["advanced"]}

    @classmethod
    def scenario_long_messages(cls, bridge):
        """Longer reset messages, an action with no card of its own: its limits say what it lets a message be."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "long_reset_message"},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- the reset actions
    def test_a_message_at_a_reset_is_added_from_the_form_asking_first_and_cancelled_at_once(self):
        result, expected = self.of("scenario_reset_message")
        words, thread, rule = expected["words"], expected["thread"], expected["rule"]
        empty, weekly, added, cancelled = result["looks"]
        self.assertEqual(empty["open"], "reset_message")
        form = empty["resets"]
        self.assertEqual(form["families"], ["The 5-hour limit", "The weekly limit"])
        self.assertEqual(form["ordinals"], ["The next one"] + ["%d from now" % n for n in range(2, 10)])
        label = "%s (%s)" % (expected["pending"][1]["name"], thread[:8])
        self.assertIn(label, form["conversations"], "a name two conversations share, told apart by the id")
        self.assertEqual(len(form["conversations"]), len(set(form["conversations"])), "two of one name are told apart")
        self.assertEqual((form["most"], form["count"], form["add"]), (2000, "0 of 2000 characters", False))
        card = next(card for card in empty["cards"] if card[0] == words["page.resets.message.title"])
        self.assertIn(words["page.resets.message.none"], card)
        self.assertNotIn(words["page.resets.unproven"], card, "MU passed on this Codex")
        self.assertEqual(weekly["resets"]["ordinals"], ["The next one"], "a weekly window offers only its next reset")
        self.assertIn("reset_add", result["disabled"], "no words, no Add")
        self.assertEqual(sent(result, "advanced-reset-add"),
                         [{"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 3, "thread_id": thread,
                           "words": self.WORDS, "generation": expected["generations"][0]}], "declined, nothing is sent")
        asked = words["page.confirm.reset_message"].replace("{window}", "the 5-hour limit").replace("{which}", "3 from now")
        self.assertEqual(result["asked"][0], asked.replace("{conversation}", label))
        self.assertEqual(len(result["asked"]), 2)
        self.assertEqual(added["note"], words["page.done.reset_added"])
        self.assertEqual(added["resets"]["cancels"], [rule])
        card = next(card for card in added["cards"] if card[0] == words["page.resets.message.title"])
        line = next(text for text in card if text.startswith("A message to "))
        self.assertIn(label, line)
        self.assertIn("(3 from now)", line)
        self.assertIn("\u201c%s\u201d" % self.WORDS, card)
        self.assertEqual(added["resets"]["words"], "", "what was added is not left in the box")
        self.assertEqual(sent(result, "advanced-reset-cancel"), [{"rule": rule, "generation": expected["generations"][1]}])
        self.assertEqual(cancelled["resets"]["cancels"], [])

    def test_a_reset_credit_rule_offers_go_on_and_use_now_and_is_added_with_how_often_and_asking(self):
        result, expected = self.of("scenario_reset_credit")
        words, due, held = expected["words"], expected["due"], expected["held"]
        shown, after = result["looks"]
        form = shown["resets"]
        self.assertEqual(form["repeat"], [words["page.resets.repeat.once"], words["page.resets.repeat.every"]])
        self.assertEqual(form["ask"], [words["page.resets.ask.no"], words["page.resets.ask.yes"]])
        self.assertEqual(form["conversations"], None, "a credit is for no conversation")
        self.assertEqual(form["cancels"], [due, held])
        self.assertEqual(form["go_ons"], [held])
        self.assertEqual(form["now"], [due, "codex 300"])
        card = next(card for card in shown["cards"] if card[0] == words["page.resets.credit.title"])
        self.assertTrue(card[1].startswith("Reset credits: 3 \u00b7 "), card[1])
        self.assertTrue(any(words["page.resets.state.ask_first"] in text for text in card))
        self.assertTrue(any(words["page.resets.state.count_gap"] in text for text in card))
        self.assertIn(words["page.resets.unproven"], card, "MU is not measured on this Codex")
        self.assertEqual(sent(result, "advanced-reset-add"),
                         [{"kind": "credit", "bucket": "codex", "minutes": 10080, "ordinal": 1, "repeat": True,
                           "ask_first": True, "generation": expected["generation"]}])
        self.assertEqual(sent(result, "advanced-credit-now"),
                         [{"bucket": "codex", "minutes": 300, "generation": expected["generation"]}], "declined, nothing")
        self.assertEqual(sent(result, "advanced-reset-go-on"), [{"rule": held, "generation": expected["generation"]}])
        self.assertEqual(result["asked"][1:], [words["page.confirm.credit_now"].replace("{window}", "the 5-hour limit")] * 2)
        self.assertEqual(after["note"], words["page.done.go_on"])

    def test_what_the_reset_forms_send_is_what_the_real_bridge_takes(self):
        from codex_auto_resume_advanced.control import sendnow
        message, _ = self.of("scenario_reset_message")
        credit, _ = self.of("scenario_reset_credit")
        with tempfile.TemporaryDirectory() as home, patch.object(sendnow, "wake", return_value=True):
            bridge = Bridge(Path(home))
            try:
                self.watched(bridge, "reset_message", state="armed")
                lines = [line for line in message["sent"] if line.startswith(("advanced-reset-add ", "advanced-reset-cancel "))]
                self.assertEqual(len(lines), 2, "one added, one cancelled")
                for line in lines:
                    with self.subTest(line):
                        reply = bridge.request(line)["result"]
                        self.assertTrue(reply["done"], reply)
            finally:
                bridge.close()
        with tempfile.TemporaryDirectory() as home, patch.object(sendnow, "wake", return_value=True):
            bridge = Bridge(Path(home))
            try:
                self.credit_rules(bridge)
                lines = [line for line in credit["sent"]
                         if line.startswith(("advanced-reset-add ", "advanced-credit-now ", "advanced-reset-go-on "))]
                self.assertEqual(len(lines), 3, "one added, one used now, one let go on")
                for line in lines:
                    with self.subTest(line):
                        reply = bridge.request(line)["result"]
                        self.assertTrue(reply["done"], reply)
            finally:
                bridge.close()

    def test_pending_shows_each_scheduled_rule_with_cancel_only_while_one_waits(self):
        """v0.6.19 (#50; the owner's decision of 2026-10-24): the rules are rows of Pending's one list after the
        recoveries, there only while one waits; no tab strip is ever built."""
        result, expected = self.of("scenario_scheduled")
        words, rule = expected["words"], expected["rule"]
        before, read, again, cancelled = result["looks"]
        key = "rule %d" % rule
        self.assertEqual(expected["counts"]["messages"], 1)
        self.assertEqual(before["page"], "pending")
        self.assertNotIn(key, before["scheduled"]["keys"])
        self.assertEqual(len(sent(result, "advanced-resets")), 3,
                         "read when the counts changed, after Go on counting and after Cancel")
        self.assertEqual(read["scheduled"]["keys"][-1], key)
        self.assertEqual(read["scheduled"]["kinds"][-1], "rule")
        cells = read["pending_rows"][-1]
        self.assertIn(expected["pending"][0]["name"], cells[0])
        self.assertEqual(cells[2], words["page.pending.kind.rule"])
        self.assertNotIn(self.WORDS, " ".join(cells), "Pending shows no words of a message")
        self.assertEqual(again["requests"], read["requests"], "the same counts read nothing again")
        generation = sent(result, "advanced-reset-cancel")[0]["generation"]
        self.assertEqual(sent(result, "advanced-reset-go-on"), [{"rule": rule, "generation": generation}])
        self.assertEqual(sent(result, "advanced-reset-cancel"), [{"rule": rule, "generation": generation}])
        self.assertNotIn(key, cancelled["scheduled"]["keys"])
        for look in result["looks"]:
            self.assertFalse(look["scheduled"]["tab_strip"])

    def test_longer_reset_messages_says_what_it_lets_a_message_be_and_has_no_report_card(self):
        result, expected = self.of("scenario_long_messages")
        words = expected["words"]
        (look,) = result["looks"]
        self.assertEqual(look["open"], "long_reset_message")
        limits = next(card for card in look["cards"] if card[0] == words["page.limits"])
        self.assertIn(words["page.long_limits"].replace("{n}", "2000"), limits)
        self.assertNotIn(words["page.action_limits"], limits)
        self.assertNotIn(words["page.report.title"], [card[0] for card in look["cards"]])


if __name__ == "__main__":
    unittest.main()
