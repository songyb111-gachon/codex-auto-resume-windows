# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Pending is one list (v0.6.19, issue #50; the owner's decision of 2026-10-24), in the window itself.

No tab strip is ever built. The reset rules and the messages still to go are rows of Pending's one list after the
recoveries, told apart by its Kind column; the buttons follow the chosen row's kind - a recovery's Retry now, Cancel,
Timeline and Turn off; a message's Edit... (a waiting one), Go on and Cancel; a rule's Go on and Cancel - the others
hidden, in one group as wide as the widest kind's, so Cancel all and Rescan never move. Schedule a message... shows only
while the prompt queue stands. A double click on a waiting message opens its editor; its saved row is chosen when it
closes. Completed messages are History's rows, with Delete completed (N)... under them, which asks, sends exactly the ids
it shows and the generation it read, and says how many it deleted and kept. The Advanced page's prompt queue card holds
one line and a button to Pending - one place for one result. Driven through the page's own hooks with the real bridge's
answers, made in a home of its own.

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

WORDS = "Run the tests again, then carry on."


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def made(cls, bridge, queue=True, rule=False):
        """prompt_queue on, a message waiting at a time and one completed - its occurrence delivered - and, with `rule`, a
        message at a reset, through the real bridge; the dashboard reply with the status's counts as the watcher would
        write them."""
        if queue:
            cls.watched(bridge, "prompt_queue", state="armed")
        if rule:
            cls.watched(bridge, "reset_message", state="armed")
        reply = snapshot(on=1 if queue or rule else 0)
        thread = reply["pending"][0]["thread_id"]
        found = {}
        if queue:
            for name, words in (("waiting", "the words as written"), ("done", "already delivered")):
                added = bridge("advanced-prompt-add", {"thread_id": thread, "words": words, "trigger": "at_time",
                                                       "at": ac.NOW + 7200, "while_running": "wait",
                                                       "generation": bridge("advanced-list", {})["result"]["generation"]})
                found[name] = added["result"]["prompt"]
            bridge.plug.runtime.state.change_prompt(found["done"], state="done", reason="delivered", finished_at=ac.NOW)
        if rule:
            added = bridge("advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1,
                                                  "thread_id": thread, "words": WORDS,
                                                  "generation": bridge("advanced-list", {})["result"]["generation"]})
            found["rule"] = added["result"]["rule"]
        counted = copy.deepcopy(reply)
        counted["status"]["advanced"].update(surfaces.status(bridge.plug.runtime))
        return counted, found

    @staticmethod
    def index(look, key):
        return look["scheduled"]["keys"].index(key)

    @classmethod
    def scenario_list(cls, bridge):
        counted, found = cls.made(bridge, rule=True)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        listed = bridge("advanced-prompts", {})
        script["advanced-prompts"] = [listed]
        generation = script["advanced-list"][0]["result"]["generation"]
        edited = bridge("advanced-prompt-edit", {"prompt": found["waiting"], "words": "the words as edited",
                                                  "trigger": "at_time", "at": ac.NOW + 3600, "while_running": "wait",
                                                  "generation": generation})
        recoveries = len(counted["pending"])
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "pending"}, {"do": "look"},
                 {"do": "pending_select", "index": 0}, {"do": "look"},
                 {"do": "pending_select", "index": recoveries}, {"do": "look"},
                 {"do": "pending_select", "index": recoveries + 1}, {"do": "look"},
                 {"do": "pending_none"}, {"do": "look"},
                 {"do": "pending_select", "index": recoveries + 1},
                 {"do": "reply", "key": "advanced-prompt-edit", "with": [edited]},
                 {"do": "pending_open", "editor": {"words": "the words as edited", "press": "save"}},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "found": found, "generation": generation,
            "pending": counted["pending"]}

    @classmethod
    def scenario_list_ko(cls, bridge):
        """scenario_list's rows chosen in turn in Korean, where Turn on for this conversation (이 대화 다시 켜기) is the longer
        of the switch's two words."""
        counted, _found = cls.made(bridge, rule=True)
        script = cls.opening(bridge, "ko")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        recoveries = len(counted["pending"])
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "pending"},
                 {"do": "pending_select", "index": 0}, {"do": "look"},
                 {"do": "pending_select", "index": recoveries}, {"do": "look"},
                 {"do": "pending_select", "index": recoveries + 1}, {"do": "look"}]
        return "ko", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_history(cls, bridge):
        counted, found = cls.made(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        generation = script["advanced-list"][0]["result"]["generation"]
        cleared = bridge("advanced-prompts-clear-done", {"prompts": [found["done"]], "generation": generation})
        script["clear-history"] = [{"ok": True, "result": {"hidden": 6}}]
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "history"}, {"do": "look"},
                 {"do": "answer", "with": [True]},
                 {"do": "reply", "key": "advanced-prompts-clear-done", "with": [cleared]},
                 {"do": "scheduled_press", "button": "clear"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "found": found, "generation": generation,
            "history": counted["history"], "cleared": cleared}

    @classmethod
    def scenario_kept(cls, bridge):
        """Delete completed answered that one changed since the list was read: said so."""
        counted, found = cls.made(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        kept = copy.deepcopy(bridge("advanced-prompts", {}))
        kept["result"].update(deleted=0, skipped=1)
        script["clear-history"] = [{"ok": True, "result": {"hidden": 6}}]
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "history"},
                 {"do": "answer", "with": [True]},
                 {"do": "reply", "key": "advanced-prompts-clear-done", "with": [kept]},
                 {"do": "scheduled_press", "button": "clear"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_nothing(cls, bridge):
        """The prompt queue off and nothing scheduled: Pending exactly as the standard edition's."""
        counted, _found = cls.made(bridge, queue=False)
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "pending"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"pending": counted["pending"]}

    @classmethod
    def scenario_card(cls, bridge):
        """The Advanced page's card says where messages are made and managed, and its Schedule... opens the editor."""
        counted, _found = cls.made(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        steps = [{"do": "snapshot", "reply": counted}, {"do": "show"}, {"do": "choose", "id": "prompt_queue"},
                 {"do": "look"}, {"do": "scheduled_press", "button": "card_add", "editor": {"press": "cancel"}}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- tests
    def test_the_list_carries_all_three_kinds_and_no_strip_is_ever_built(self):
        """Fails with the strip back: the rules and the messages are on a tab of their own, not in Pending's list."""
        result, expected = self.of("scenario_list")
        found = expected["found"]
        opened = result["looks"][0]
        recoveries = len(expected["pending"])
        self.assertEqual(opened["scheduled"]["kinds"], [None] * recoveries + ["rule", "message"])
        self.assertEqual(opened["scheduled"]["keys"][recoveries:], ["rule %d" % found["rule"], "prompt %d" % found["waiting"]])
        for look in result["looks"]:
            self.assertFalse(look["scheduled"]["tab_strip"])

    def test_the_kind_column_tells_them_apart_and_a_message_says_its_send_mode_and_no_words(self):
        result, expected = self.of("scenario_list")
        words, found = expected["words"], expected["found"]
        opened = result["looks"][0]
        rule = opened["pending_rows"][self.index(opened, "rule %d" % found["rule"])]
        message = opened["pending_rows"][self.index(opened, "prompt %d" % found["waiting"])]
        self.assertEqual(rule[2], words["page.pending.kind.rule"])
        self.assertEqual(message[2], words["page.pending.kind.message"])
        message_chosen = result["looks"][3]
        self.assertIn(words["page.scheduled.mode.wait"], message_chosen["explain_empty"],
                      "what it does while a turn runs is said in Why it is waiting")
        self.assertIn(message[3], message_chosen["explain_empty"], "and when it goes")
        self.assertTrue(message[3], "its Next check cell says when it goes")
        self.assertIn(expected["pending"][0]["name"], message[0])
        self.assertNotIn("the words as written", " ".join(message))
        self.assertNotIn(WORDS, " ".join(rule))

    def test_the_buttons_follow_the_chosen_rows_kind_and_what_follows_never_moves(self):
        result, expected = self.of("scenario_list")
        words = expected["words"]
        _opened, recovery, rule, message, _none, _saved = result["looks"]
        english = {"retry": "Retry now", "timeline": "Timeline", "edit": words["page.queue.edit"],
                   "go_on": words["page.queue.go_on"], "add": words["page.scheduled.add"]}
        self.assertIn(english["retry"], recovery["pending_buttons"])
        self.assertIn(english["timeline"], recovery["pending_buttons"])
        self.assertNotIn(english["edit"], recovery["pending_buttons"])
        self.assertNotIn(english["go_on"], recovery["pending_buttons"])
        for look in (rule, message):
            self.assertNotIn(english["retry"], look["pending_buttons"])
            self.assertNotIn(english["timeline"], look["pending_buttons"])
            self.assertIn(english["go_on"], look["pending_buttons"])
        self.assertNotIn(english["edit"], rule["pending_buttons"])
        self.assertIn(english["edit"], message["pending_buttons"])
        self.assertTrue(message["scheduled"]["buttons"]["edit"], "a waiting message can be edited")
        none = result["looks"][4]
        for look in (recovery, rule, message, none):
            self.assertIn(english["add"], look["pending_buttons"], "Schedule... while the queue stands, whatever is chosen")
            self.assertTrue(look["scheduled"]["add_after_rescan"], "in the row, right after Rescan, never in the kind's group")
        lefts = {tuple(look["scheduled"]["later_lefts"]) for look in (recovery, rule, message)}
        self.assertEqual(len(lefts), 1, "Cancel all and Rescan stay where they are: %r" % lefts)

    def test_the_buttons_under_the_list_stand_one_gap_apart_whatever_row_is_chosen(self):
        """Fails with the room held for the widest kind's buttons left as a gap before Cancel all: after a message's three
        or a rule's two, and in Korean after the shorter words of the conversation switch (the owner, 2026-10-25)."""
        result, _expected = self.of("scenario_list")
        _opened, recovery, rule, message, none, _saved = result["looks"]
        looks = {"recovery": recovery, "rule": rule, "message": message, "none": none}
        korean, _ = self.of("scenario_list_ko")
        looks.update(zip(("ko recovery", "ko rule", "ko message"), korean["looks"]))
        for name, look in looks.items():
            gaps = look["scheduled"]["gaps"]
            self.assertGreaterEqual(len(gaps), 4, "%s: %r" % (name, look["pending_buttons"]))
            self.assertLessEqual(max(gaps) - min(gaps), 1, "%s: %r" % (name, gaps))
        lefts = {tuple(look["scheduled"]["later_lefts"]) for look in korean["looks"]}
        self.assertEqual(len(lefts), 1, "in Korean too, Cancel all and Rescan stay where they are: %r" % lefts)

    def test_the_editions_own_buttons_speak_the_windows_language(self):
        """Pending is built before the bridge's words can come; its Schedule..., Edit..., Go on and Cancel were then made
        in English and never said again in Korean (v0.6.19's live acceptance; the owner: "왜 스케쥴이라고 뜨지, 영어로?").
        Fails with the buttons not reworded when the words come (RewordPendingButtons)."""
        korean, _ = self.of("scenario_list_ko")
        for look in korean["looks"]:
            buttons = look["pending_buttons"]
            self.assertIn("예약...", buttons)
            for english in ("Schedule...", "Edit...", "Go on", "Cancel"):
                self.assertNotIn(english, buttons)

    def test_a_rules_next_check_is_short_and_no_cell_is_cut_short(self):
        """A rule's Next check is its limit and which reset, not the whole sentence (that is Why it is waiting's). At the
        window's opening size no cell past the conversation's is cut short in Korean, and in English, where the list has
        no room for every cell whole, only a long state gives way - a kind and a time stay whole. Fails with the sentence
        back in the cell, cut to "the 5-hour...", with a message's time measured as the countdown it never shows, which
        cut "매일 09:00" to "매일 09:...", or with the room left shared in proportion, which cut every column a little
        (the owner, 2026-10-25)."""
        result, expected = self.of("scenario_list")
        words, found = expected["words"], expected["found"]
        opened, _recovery, rule_chosen = result["looks"][:3]
        rule = opened["pending_rows"][self.index(opened, "rule %d" % found["rule"])]
        self.assertEqual(rule[3], words["page.resets.window.300"], "the next reset of its limit")
        self.assertIn(words["page.resets.window.300"], rule_chosen["explain_empty"], "the whole sentence is still said")
        korean, _ = self.of("scenario_list_ko")
        for look in korean["looks"]:
            self.assertEqual(look["pending_cut"], [], "ko")
        for look in (opened, rule_chosen):
            self.assertEqual([cell for cell in look["pending_cut"] if cell.split()[0].split("/")[1] != "1"], [],
                             "en: only a state gives way")

    def test_a_rules_status_is_a_short_word_and_its_whole_sentence_is_in_why_it_is_waiting(self):
        """Fails with the whole sentence back in the Status column, which cut the Next check column short."""
        result, expected = self.of("scenario_list")
        words, found = expected["words"], expected["found"]
        opened, _recovery, rule = result["looks"][:3]
        cells = opened["pending_rows"][self.index(opened, "rule %d" % found["rule"])]
        self.assertEqual(cells[1], words["page.queue.state.waiting"])
        self.assertIn(words["page.resets.state.starting"], rule["explain_empty"])

    def test_a_double_click_on_a_waiting_message_edits_it_and_the_saved_row_is_chosen_after(self):
        result, expected = self.of("scenario_list")
        saved = result["looks"][-1]
        (editor,) = result["dialogs"]
        self.assertTrue(editor["taken"])
        self.assertEqual(editor["words"], "the words as written", "opened filled with the row chosen")
        self.assertEqual(sent(result, "advanced-prompt-edit")[0]["prompt"], expected["found"]["waiting"])
        self.assertEqual(saved["scheduled"]["selected"], ["prompt %d" % expected["found"]["waiting"]])

    def test_history_lists_the_completed_messages_with_their_times_as_a_recoverys(self):
        """Fails with the message's own clock time back ("at 10:00" beside "2027-01-15 07:59")."""
        import re
        result, _expected = self.of("scenario_history")
        opened = result["looks"][0]
        done = opened["scheduled"]["history"][-1]
        recovery = opened["scheduled"]["history"][0]
        shape = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertTrue(shape.match(recovery[3]), recovery)
        self.assertTrue(shape.match(done[3]) and shape.match(done[4]), done)

    def test_one_clear_history_clears_the_recoveries_and_the_completed_messages(self):
        """Fails with Delete completed back beside Clear history: two buttons for one result."""
        result, expected = self.of("scenario_history")
        words = expected["words"]
        opened, cleared = result["looks"]
        self.assertEqual(opened["page"], "history")
        self.assertEqual(opened["scheduled"]["history_kinds"][-1], "message_done")
        done = opened["scheduled"]["history"][-1]
        self.assertEqual((done[1], done[2]), (words["page.scheduled.state.delivered"], words["page.pending.kind.message"]))
        self.assertNotIn("already delivered", " ".join(done), "History shows no words of a message")
        self.assertEqual(opened["scheduled"]["clear_text"], "Clear history")
        self.assertNotIn("page.scheduled.clear", words)
        self.assertEqual([text for text in opened["scheduled"]["history_buttons"] if "Delete" in text], [])
        self.assertTrue(opened["scheduled"]["buttons"]["clear"])
        finished = sum(1 for row in expected["history"] if row.get("outcome_at"))
        self.assertEqual(result["asked"][-1], words["page.confirm.clear_both"].replace("{n}", "1")
                         .replace("{recoveries}", str(finished)))
        self.assertIn("clear-history ", result["sent"], "the recoveries hidden as Clear history hides them")
        (request,) = sent(result, "advanced-prompts-clear-done")
        self.assertEqual(request, {"prompts": [expected["found"]["done"]], "generation": expected["generation"]})
        self.assertEqual(cleared["scheduled"]["history_note"], words["page.done.cleared"].replace("{deleted}", "1"))
        self.assertNotIn("message_done", cleared["scheduled"]["history_kinds"])

    def test_one_kept_because_it_changed_is_said(self):
        result, expected = self.of("scenario_kept")
        (look,) = result["looks"]
        self.assertEqual(look["scheduled"]["history_note"], expected["words"]["page.done.cleared_kept"]
                         .replace("{deleted}", "0").replace("{skipped}", "1"))

    def test_with_the_queue_off_and_nothing_scheduled_pending_is_the_standard_editions(self):
        result, expected = self.of("scenario_nothing")
        (look,) = result["looks"]
        self.assertFalse(look["scheduled"]["tab_strip"])
        self.assertEqual(look["scheduled"]["kinds"], [None] * len(expected["pending"]))
        self.assertNotIn("Schedule...", look["pending_buttons"])

    def test_the_advanced_features_card_keeps_its_schedule_button(self):
        """The card says a message is scheduled there or on Pending, and its Schedule... opens the editor there."""
        result, expected = self.of("scenario_card")
        words = expected["words"]
        on_card, there = result["looks"]
        card = next(card for card in on_card["cards"] if card[0] == words["page.queue.title"])
        self.assertIn(words["page.queue.moved"].replace("{pending}", "Pending"), card)
        self.assertNotIn("the words as written", " ".join(card), "no message is listed or written there any more")
        self.assertTrue(on_card["queue"]["go"], "the card's one button, Schedule..., is offered")
        self.assertEqual(there["page"], "advanced", "it opens the editor where it is")
        (editor,) = result["dialogs"]
        self.assertEqual((editor["title"], editor["words"]), (words["page.editor.title_new"], ""), "a new message")


if __name__ == "__main__":
    unittest.main()
