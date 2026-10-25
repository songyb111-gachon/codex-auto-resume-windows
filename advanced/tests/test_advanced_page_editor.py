# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The prompt queue's editor in the window itself (v0.6.19, issue #50): a child dialog in the Dashboard's design, the one
place a message is scheduled or changed - its words at the reading size, the send mode with Wait until it ends marked
recommended and preselected, Save and return as the accent button; saved, it closes and the saved row is the one to choose;
refused, every field stays as typed and the refusal is said above the buttons. Driven through the page's own hooks, the
dialog built and never shown, with the real bridge's answers made in a home of its own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_editor.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402

WORDS = "Carry on with the release notes, then check every link once more."


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def opened(cls, bridge, extra_steps, script_more=None):
        shot = snapshot()
        script = cls.opening(bridge, "en")
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        script.update(script_more or {})
        steps = [{"do": "snapshot", "reply": shot}, {"do": "show"}, {"do": "choose", "id": "prompt_queue"},
                 {"do": "look"}] + extra_steps
        words = script["advanced-words"][0]["result"]["words"]
        return "en", {"script": script, "steps": steps}, {"words": words, "thread": shot["pending"][0]["thread_id"]}

    @classmethod
    def on(cls, bridge):
        """prompt_queue on through the real bridge, once for a home."""
        if bridge("advanced-list", {})["result"]["capabilities"] and not any(
                item["id"] == "prompt_queue" and item["state"] == "armed"
                for item in bridge("advanced-list", {})["result"]["capabilities"]):
            cls.watched(bridge, "prompt_queue", state="armed")

    @staticmethod
    def thread(bridge):
        return snapshot()["pending"][0]["thread_id"]

    @classmethod
    def add(cls, bridge, **argument):
        cls.on(bridge)
        argument.setdefault("thread_id", cls.thread(bridge))
        argument.setdefault("words", "the words as written")
        argument.setdefault("trigger", "at_time")
        argument.setdefault("at", ac.NOW + 7200)
        argument["generation"] = bridge("advanced-list", {})["result"]["generation"]
        return bridge("advanced-prompt-add", argument)

    @classmethod
    def scenario_new(cls, bridge):
        made = cls.add(bridge, while_running="wait")        # the bridge's own answer, which the page is handed
        return cls.opened(bridge, [{"do": "editor", "thread": cls.thread(bridge), "words": WORDS, "when": "at_time",
                                    "hour": "14", "press": "save"}],
                          {"advanced-prompt-add": [made]})

    @classmethod
    def scenario_refused(cls, bridge):
        cls.on(bridge)
        refused = {"ok": True, "result": {"done": False, "refusal": "queue_full"}}
        return cls.opened(bridge, [{"do": "editor", "thread": cls.thread(bridge), "words": WORDS, "when": "day",
                                    "hour": "9", "times": "3", "mode": "queue", "press": "save"}],
                          {"advanced-prompt-add": [refused]})

    @classmethod
    def scenario_after_turn(cls, bridge):
        made = cls.add(bridge, trigger="after_turn", at=None)
        return cls.opened(bridge, [{"do": "editor", "thread": cls.thread(bridge), "words": WORDS, "when": "after_turn",
                                    "press": "save"}],
                          {"advanced-prompt-add": [made]})

    @classmethod
    def scenario_edit(cls, bridge):
        made = cls.add(bridge, words="the words as written", while_running="queue")["result"]["prompt"]
        listed = bridge("advanced-prompts", {})             # what the page read, before the edit
        edited = bridge("advanced-prompt-edit", {"prompt": made, "words": WORDS, "trigger": "at_time",
                                                  "at": ac.NOW + 3600, "while_running": "queue",
                                                  "generation": bridge("advanced-list", {})["result"]["generation"]})
        name, scenario, expected = cls.opened(bridge, [{"do": "editor", "prompt": made, "words": WORDS,
                                                        "press": "save"}],
                                               {"advanced-prompt-edit": [edited], "advanced-prompts": [listed]})
        expected["prompt"] = made
        return name, scenario, expected

    @classmethod
    def scenario_cancel(cls, bridge):
        cls.on(bridge)
        return cls.opened(bridge, [{"do": "editor", "thread": cls.thread(bridge), "words": WORDS, "press": "cancel"}])

    # ---------------------------------------------------------------- tests
    def test_saved_it_closes_and_the_saved_row_is_the_one_to_choose(self):
        result, expected = self.of("scenario_new")
        (editor,) = result["dialogs"]
        self.assertTrue(editor["taken"], editor)
        self.assertGreater(editor["saved"], 0)
        (request,) = sent(result, "advanced-prompt-add")
        self.assertEqual((request["thread_id"], request["words"], request["trigger"], request["while_running"]),
                         (expected["thread"], WORDS, "at_time", "wait"), "the recommended mode, preselected")

    def test_the_dialog_reads_as_the_issue_asks(self):
        """Words at the reading size (never under 12 pt at 100%), the recommended mode marked and chosen, Save and return
        the accent button. Fails with the editor reverted: there is no dialog to open."""
        result, expected = self.of("scenario_new")
        (editor,) = result["dialogs"]
        words = expected["words"]
        self.assertGreaterEqual(editor["reading_points"], editor["window_points"] + 3 - 0.01)
        self.assertEqual(editor["mode"], "wait")
        self.assertEqual(editor["modes"], [words["page.editor.mode.wait"], words["page.editor.mode.queue"]])
        self.assertIn("(recommended)", editor["modes"][0])
        self.assertEqual(editor["buttons"], [words["page.editor.save"], "Cancel"])
        self.assertTrue(editor["accept"], "Enter presses Save and return")
        self.assertTrue(editor["mode_shown"])
        self.assertTrue(editor["conversation_enabled"])

    def test_refused_every_field_stays_as_typed_and_the_refusal_is_said(self):
        result, expected = self.of("scenario_refused")
        (editor,) = result["dialogs"]
        self.assertFalse(editor["taken"])
        self.assertEqual(editor["words_after"], WORDS)
        self.assertEqual(editor["said"], expected["words"]["page.refused.queue_full"])
        (request,) = sent(result, "advanced-prompt-add")
        self.assertEqual((request["trigger"], request["every"], request["occurrences"], request["while_running"]),
                         ("recurring", "day", 3, "queue"))

    def test_after_this_turn_says_what_it_does_instead_of_offering_the_choice(self):
        result, expected = self.of("scenario_after_turn")
        (editor,) = result["dialogs"]
        self.assertFalse(editor["mode_shown"])
        self.assertTrue(editor["after_turn_shown"])
        (request,) = sent(result, "advanced-prompt-add")
        self.assertEqual((request["trigger"], request["while_running"]), ("after_turn", "queue"))

    def test_the_dialog_is_as_tall_as_what_it_shows(self):
        """No empty band above the buttons: up to v0.6.19-beta.3 the dialog stood as tall as the send mode's choices, the
        line on after this turn and the longest refusal all at once (the owner, 2026-10-25). A refusal said is wholly in
        view. Fails with the dialog sized for all of them."""
        for name in ("scenario_after_turn", "scenario_new", "scenario_refused"):
            (editor,) = self.of(name)[0]["dialogs"]
            self.assertLessEqual(editor["blank"], 2, "%s: %r px empty above the buttons" % (name, editor["blank"]))
            if not editor["taken"]:
                self.assertLessEqual(editor["blank_after"], 2, "%s, refused: %r px" % (name, editor["blank_after"]))
                self.assertTrue(editor["said_fits"], "%s: the refusal is cut off" % name)
        refused = self.of("scenario_refused")[0]["dialogs"][0]
        self.assertTrue(refused["said"], "the refused scenario said its refusal")

    def test_edit_opens_filled_for_that_message_and_saves_it(self):
        result, expected = self.of("scenario_edit")
        (editor,) = result["dialogs"]
        self.assertEqual(editor["words"], "the words as written")
        self.assertFalse(editor["conversation_enabled"], "an edit keeps its conversation")
        self.assertEqual(editor["mode"], "queue", "as it was written")
        self.assertEqual(editor["title"], expected["words"]["page.editor.title_edit"])
        (request,) = sent(result, "advanced-prompt-edit")
        self.assertEqual((request["prompt"], request["words"]), (expected["prompt"], WORDS))
        self.assertNotIn("thread_id", request)
        self.assertTrue(editor["taken"])
        self.assertEqual(editor["saved"], expected["prompt"])

    def test_cancel_sends_nothing(self):
        result, _expected = self.of("scenario_cancel")
        (editor,) = result["dialogs"]
        self.assertFalse(editor["taken"])
        self.assertEqual(sent(result, "advanced-prompt-add"), [])


if __name__ == "__main__":
    unittest.main()
