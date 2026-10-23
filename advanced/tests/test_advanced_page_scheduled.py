# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Pending's Recoveries | Scheduled tabs in the window itself (v0.6.19, issue #50): the strip only while the prompt queue
stands or anything is scheduled; Scheduled a flat list of the reset rules and messages still to go, with Schedule a
message..., Edit... (a waiting one), Cancel and Go on on the row chosen; the editor's saved row chosen when it closes; the
Done section with Delete completed (N)..., which asks, sends exactly the ids it shows and the generation it read, and says
how many it deleted and kept. The Advanced page's prompt queue card holds one line and Go to Scheduled - one place for one
result. Driven through the page's own hooks with the real bridge's answers, made in a home of its own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_scheduled.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def made(cls, bridge, queue=True):
        """prompt_queue on, a message waiting at a time and one completed - its occurrence delivered - through the
        real bridge; the dashboard reply with the status's counts as the watcher would write them."""
        if queue:
            cls.watched(bridge, "prompt_queue", state="armed")
        reply = snapshot(on=1 if queue else 0)
        thread = reply["pending"][0]["thread_id"]
        found = {}
        if queue:
            for name, words in (("waiting", "the words as written"), ("done", "already delivered")):
                added = bridge("advanced-prompt-add", {"thread_id": thread, "words": words, "trigger": "at_time",
                                                       "at": ac.NOW + 7200, "while_running": "wait",
                                                       "generation": bridge("advanced-list", {})["result"]["generation"]})
                found[name] = added["result"]["prompt"]
            bridge.plug.runtime.state.change_prompt(found["done"], state="done", reason="delivered", finished_at=ac.NOW)
        counted = copy.deepcopy(reply)
        counted["status"]["advanced"].update(surfaces.status(bridge.plug.runtime))
        return counted, found

    @classmethod
    def scenario_tabs(cls, bridge):
        counted, found = cls.made(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        listed = bridge("advanced-prompts", {})
        script["advanced-prompts"] = [listed]
        generation = script["advanced-list"][0]["result"]["generation"]
        edited = bridge("advanced-prompt-edit", {"prompt": found["waiting"], "words": "the words as edited",
                                                  "trigger": "at_time", "at": ac.NOW + 3600, "while_running": "wait",
                                                  "generation": generation})
        cleared = bridge("advanced-prompts-clear-done", {"prompts": [found["done"]], "generation": generation})
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "pending"}, {"do": "look"},
                 {"do": "tab", "name": "scheduled"}, {"do": "look"},
                 {"do": "scheduled_choose", "key": "prompt %d" % found["waiting"]}, {"do": "look"},
                 {"do": "reply", "key": "advanced-prompt-edit", "with": [edited]},
                 {"do": "scheduled_press", "button": "edit",
                  "editor": {"words": "the words as edited", "press": "save"}},
                 {"do": "look"},
                 {"do": "answer", "with": [True]},
                 {"do": "reply", "key": "advanced-prompts-clear-done", "with": [cleared]},
                 {"do": "scheduled_press", "button": "clear"}, {"do": "look"},
                 {"do": "tab", "name": "recoveries"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "found": found, "generation": generation,
            "pending": counted["pending"], "cleared": cleared}

    @classmethod
    def scenario_kept(cls, bridge):
        """Delete completed answered that one changed since the list was read: said so."""
        counted, found = cls.made(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        kept = copy.deepcopy(bridge("advanced-prompts", {}))
        kept["result"].update(deleted=0, skipped=1)
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "pending"},
                 {"do": "tab", "name": "scheduled"}, {"do": "answer", "with": [True]},
                 {"do": "reply", "key": "advanced-prompts-clear-done", "with": [kept]},
                 {"do": "scheduled_press", "button": "clear"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_nothing(cls, bridge):
        """The prompt queue off and nothing scheduled: no strip - Pending exactly as the standard edition's."""
        counted, _found = cls.made(bridge, queue=False)
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "pending"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_card(cls, bridge):
        """The Advanced page's card says where messages are scheduled, and Go to Scheduled goes there."""
        counted, _found = cls.made(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        steps = [{"do": "snapshot", "reply": counted}, {"do": "show"}, {"do": "choose", "id": "prompt_queue"},
                 {"do": "look"}, {"do": "press", "button": "queue_go"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- tests
    def test_the_strip_shows_two_tabs_and_recoveries_is_pending_as_it_was(self):
        """Fails with the tabs reverted: Pending has no Scheduled tab."""
        result, expected = self.of("scenario_tabs")
        words = expected["words"]
        opened, scheduled, chosen, saved, cleared, back = result["looks"]
        self.assertTrue(opened["scheduled"]["tabs_shown"])
        self.assertEqual(opened["scheduled"]["tabs"], [words["page.pending.recoveries"],
                                                       words["page.pending.scheduled"].replace("{n}", "1")])
        self.assertEqual(opened["scheduled"]["chosen"], "recoveries")
        self.assertEqual(len(opened["pending_rows"]), len(expected["pending"]), "the recoveries are all there")
        self.assertEqual(scheduled["scheduled"]["chosen"], "scheduled")
        self.assertEqual(back["scheduled"]["chosen"], "recoveries")

    def test_scheduled_lists_each_message_with_its_send_mode_and_no_words(self):
        result, expected = self.of("scenario_tabs")
        words = expected["words"]
        _opened, scheduled, _chosen, _saved, _cleared, _back = result["looks"]
        self.assertEqual(scheduled["scheduled"]["keys"], ["prompt %d" % expected["found"]["waiting"]])
        (cells,) = scheduled["scheduled"]["rows"]
        self.assertIn(expected["pending"][0]["name"], cells[0])
        self.assertEqual(cells[3], words["page.scheduled.mode.wait"])
        self.assertNotIn("the words as written", " ".join(cells))

    def test_edit_is_for_the_waiting_row_chosen_and_the_saved_row_is_chosen_after(self):
        result, expected = self.of("scenario_tabs")
        _opened, scheduled, chosen, saved, _cleared, _back = result["looks"]
        self.assertFalse(scheduled["scheduled"]["buttons"]["edit"], "nothing chosen yet")
        self.assertTrue(chosen["scheduled"]["buttons"]["edit"])
        self.assertTrue(chosen["scheduled"]["buttons"]["add"])
        (editor,) = result["dialogs"]
        self.assertTrue(editor["taken"])
        self.assertEqual(editor["words"], "the words as written", "opened filled with the row chosen")
        self.assertEqual(sent(result, "advanced-prompt-edit")[0]["prompt"], expected["found"]["waiting"])
        self.assertEqual(saved["scheduled"]["selected"], ["prompt %d" % expected["found"]["waiting"]])
        self.assertEqual(saved["scheduled"]["chosen"], "scheduled", "back on the Scheduled tab")

    def test_delete_completed_asks_sends_the_ids_shown_and_says_what_it_did(self):
        result, expected = self.of("scenario_tabs")
        words = expected["words"]
        _opened, scheduled, _chosen, _saved, cleared, _back = result["looks"]
        self.assertTrue(scheduled["scheduled"]["done_shown"])
        self.assertEqual(len(scheduled["scheduled"]["done"]), 1)
        self.assertEqual(scheduled["scheduled"]["clear_text"], words["page.scheduled.clear"].replace("{n}", "1"))
        self.assertEqual(result["asked"][-1], words["page.confirm.clear"].replace("{n}", "1"))
        (request,) = sent(result, "advanced-prompts-clear-done")
        self.assertEqual(request, {"prompts": [expected["found"]["done"]], "generation": expected["generation"]})
        self.assertEqual(cleared["scheduled"]["note"], words["page.done.cleared"].replace("{deleted}", "1"))
        self.assertFalse(cleared["scheduled"]["done_shown"], (cleared["scheduled"], expected["cleared"]))

    def test_one_kept_because_it_changed_is_said(self):
        result, expected = self.of("scenario_kept")
        (look,) = result["looks"]
        self.assertEqual(look["scheduled"]["note"], expected["words"]["page.done.cleared_kept"]
                         .replace("{deleted}", "0").replace("{skipped}", "1"))

    def test_with_the_queue_off_and_nothing_scheduled_there_is_no_strip(self):
        result, _expected = self.of("scenario_nothing")
        (look,) = result["looks"]
        self.assertFalse(look["scheduled"]["tabs_shown"])
        self.assertEqual(look["scheduled"]["chosen"], "recoveries")

    def test_the_advanced_page_card_points_to_scheduled_and_goes_there(self):
        result, expected = self.of("scenario_card")
        words = expected["words"]
        on_card, there = result["looks"]
        card = next(card for card in on_card["cards"] if card[0] == words["page.queue.title"])
        self.assertIn(words["page.queue.moved"].replace("{pending}", "Pending")
                      .replace("{scheduled}", words["page.scheduled"]), card)
        self.assertNotIn("the words as written", " ".join(card), "no message is listed or written there any more")
        self.assertEqual((there["page"], there["scheduled"]["chosen"]), ("pending", "scheduled"))


if __name__ == "__main__":
    unittest.main()
