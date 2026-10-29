# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""#50's follow-through in the window itself (v0.6.20): a delivered message chosen on History offers Follow through...,
and that button or a double click on the row opens a dialog in the window's material - its rows on History's card -
that asks the bridge once (advanced-prompt-follow) and shows the message's sending and delivery, the limit that cut its
turn off, where the recovery of that turn stands, and how it ended, with one line saying how the turn was tied to the
message (exactly, or by time). Nothing is offered on a recovery's row. Driven through the page's own hooks, the dialog
built and never shown, with the real bridge's answers made in a home of its own - Codex's history and core's records
handed to control/follow.py by the scenario, never read from this machine.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_follow.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, ok, sent, snapshot, strings  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.control import follow  # noqa: E402
from test_advanced_prompt_follow import RECOVERY, TURN, cut, marked  # noqa: E402

RECORD = "ab" * 32


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def made(cls, bridge, locale, linked):
        """prompt_queue on and one message delivered, through the real bridge; its follow-through answered by
        control/follow.py from records the scenario gives - linked exactly through a cut-off and its recovery cut off
        again (`linked` "exact"), or by time. Then History, its message row chosen, the button pressed and the row
        double-clicked, and a recovery's row chosen."""
        cls.watched(bridge, "prompt_queue", state="armed")
        reply = snapshot(on=1)
        thread = reply["pending"][0]["thread_id"]
        added = bridge("advanced-prompt-add", {"thread_id": thread, "words": "already delivered", "trigger": "at_time",
                                               "at": ac.NOW + 7200, "while_running": "wait",
                                               "generation": bridge("advanced-list", {})["result"]["generation"]})
        prompt = added["result"]["prompt"]
        state = bridge.plug.runtime.state
        state.change_prompt(prompt, state="done", reason="delivered", record_id=RECORD, sent_at=ac.NOW - 120,
                            finished_at=ac.NOW - 60)
        first = cut(TURN, "recovered", thread=thread, started=ac.NOW - 119, detected=ac.NOW + 600, recovery=RECOVERY,
                    outcome=ac.NOW + 4800)
        second = cut(RECOVERY, "waiting_reset", thread=thread, started=ac.NOW + 4500, detected=ac.NOW + 5000,
                     parent=first["interruption_id"], limit="10080m")
        found = [marked(TURN, "failed")] if linked == "exact" else None
        with patch.object(follow, "_records", lambda runtime, wanted: [first, second] if wanted == thread else []):
            answer = follow.view(bridge.plug.runtime, prompt, reader=lambda wanted, record: found)
        counted = copy.deepcopy(reply)
        counted["status"]["advanced"].update(surfaces.status(bridge.plug.runtime))
        script = cls.opening(bridge, locale)
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        script["advanced-prompt-follow"] = [ok(answer), ok(answer)]
        at = len(counted["history"])
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "history"},
                 {"do": "history_select", "index": at}, {"do": "look"},
                 {"do": "history_follow", "by": "button"}, {"do": "history_follow", "by": "double"},
                 {"do": "history_select", "index": 0}, {"do": "look"}, {"do": "history_follow", "by": "button"}]
        return locale, {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "prompt": prompt, "answer": answer, "at": at}

    @classmethod
    def scenario_exact(cls, bridge):
        return cls.made(bridge, "en", "exact")

    @classmethod
    def scenario_time_ko(cls, bridge):
        return cls.made(bridge, "ko", "time")

    # ---------------------------------------------------------------- tests
    def test_a_delivered_message_is_followed_to_the_end_of_its_work(self):
        """Fails with the dialog reverted: History offers nothing for a delivered message, and nothing is asked."""
        result, expected = self.of("scenario_exact")
        words, answer = expected["words"], expected["answer"]
        codes = strings("en")["strings"]
        self.assertEqual((answer["link"], [step["turn_id"] for step in answer["steps"]], answer["end"]),
                         ("exact", [TURN, RECOVERY], "waiting"), "the bridge's answer the page shows")
        chosen = result["looks"][0]["scheduled"]
        self.assertEqual(chosen["history_kinds"][expected["at"]], "message_done")
        self.assertTrue(chosen["buttons"]["follow"], "offered for the delivered message")
        self.assertIn(words["page.follow.button"], chosen["history_buttons"])
        by_button, by_double = result["dialogs"]
        self.assertEqual(by_button, by_double, "the button and a double click open the same")
        self.assertEqual(sent(result, "advanced-prompt-follow"), [{"prompt": expected["prompt"]}] * 2)
        self.assertTrue(by_button["title"].startswith(words["page.follow.title"]))
        self.assertEqual(by_button["said"], words["page.follow.link.exact"])
        self.assertEqual(by_button["list_card"], "", "its list is on History's card")
        self.assertEqual((by_button["buttons"], by_button["accept"]), (["Close"], True))
        events = [row[1] for row in by_button["rows"]]
        self.assertEqual(events, [
            words["page.follow.sent"], words["page.follow.delivered_turn"],
            words["page.follow.cut"].replace("{limit}", words["page.resets.window.300"]),
            words["page.follow.recovery"].replace("{state}", codes["code.recovered"]),
            words["page.follow.cut"].replace("{limit}", words["page.resets.window.10080"]),
            words["page.follow.reset"],
            words["page.follow.recovery"].replace("{state}", codes["code.waiting_reset"]),
            words["page.follow.end.waiting"]])
        self.assertTrue(all(row[0] for row in by_button["rows"][:-2]), "each step its time")
        self.assertEqual(by_button["rows"][-1][0], "", "the end is no time of its own")

    def test_a_recovery_s_row_offers_nothing(self):
        result, _expected = self.of("scenario_exact")
        self.assertFalse(result["looks"][1]["scheduled"]["buttons"]["follow"])
        self.assertIn("history_follow", result["disabled"])
        self.assertEqual(len(result["dialogs"]), 2, "nothing opened for the recovery")

    def test_linked_by_time_says_so_in_korean(self):
        result, expected = self.of("scenario_time_ko")
        words, answer = expected["words"], expected["answer"]
        self.assertEqual(answer["link"], "time")
        dialog = result["dialogs"][0]
        self.assertEqual(dialog["said"], words["page.follow.link.time"])
        self.assertEqual(dialog["rows"][1][1], words["page.follow.delivered"], "no claim that it started the turn")


if __name__ == "__main__":
    unittest.main()
