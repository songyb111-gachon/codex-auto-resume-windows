# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Find a conversation in the window itself (v0.6.20, issue #50): beside the scheduled-message editor's picker and the
reset-message form's, a button opens a small dialog with a search box and a list of the person's own conversations
(the bridge's advanced-conversations), typing keeps the ones whose name holds it, and the one chosen is put into the
picker - the message saved names it, though neither Pending nor History lists it. Driven through the page's own hooks,
the dialog built and never shown, with the real bridge's answers made in a home of its own (the list of conversations a
script hands it, in the shape control/conversations.py answers).

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_find.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, ok, sent, snapshot  # noqa: E402

WORDS = "Carry on with the release notes, then check every link once more."
FOUND = "0a1b2c3d-00f0-7000-8000-0000000000f0"
NAME = "Release notes plan"
OTHERS = [("0a1b2c3d-00f1-7000-8000-0000000000f1", "Fix the tray icon"),
          ("0a1b2c3d-00f2-7000-8000-0000000000f2", "Korean wording")]
CONVERSATIONS = [{"thread_id": FOUND, "name": NAME}] + [{"thread_id": thread, "name": name} for thread, name in OTHERS]
ANSWER = ok({"done": True, "refusal": None, "limit": 200, "conversations": CONVERSATIONS})


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def counted(cls, bridge, capability):
        """`capability` on through the real bridge, and the dashboard reply with the status's counts as the watcher
        would write them."""
        cls.watched(bridge, capability, state="armed")
        reply = snapshot(on=1)
        reply["status"]["advanced"].update(surfaces.status(bridge.plug.runtime))
        return reply

    @classmethod
    def scenario_editor(cls, bridge):
        """Schedule... on Pending: the editor's Find a conversation... opens, `release` is typed, the conversation neither
        Pending nor History lists is chosen, the words are written and the message saved; Pending then names it."""
        reply = cls.counted(bridge, "prompt_queue")
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        before = bridge("advanced-prompts", {})
        script["advanced-conversations"] = [ANSWER]
        generation = script["advanced-list"][0]["result"]["generation"]
        made = bridge("advanced-prompt-add", {"thread_id": FOUND, "words": WORDS, "trigger": "at_time",
                                              "at": ac.NOW + 7200, "while_running": "wait", "generation": generation})
        script["advanced-prompts"] = [before, bridge("advanced-prompts", {})]
        script["advanced-prompt-add"] = [made]
        steps = [{"do": "snapshot", "reply": reply}, {"do": "page", "name": "pending"}, {"do": "look"},
                 {"do": "scheduled_press", "button": "add",
                  "editor": {"find": {"search": "release", "thread": FOUND}, "words": WORDS, "when": "at_time",
                             "hour": "14", "press": "save"}},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "pending": reply["pending"]}

    @classmethod
    def scenario_reset(cls, bridge):
        """A message at a reset: the form's Find a conversation... chooses the same conversation, and the rule added names
        it."""
        cls.watched(bridge, "reset_message", state="armed")
        reply = snapshot()
        script = cls.opening(bridge, "en")
        generation = script["advanced-list"][0]["result"]["generation"]
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-conversations"] = [ANSWER]
        added = bridge("advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 3,
                                              "thread_id": FOUND, "words": WORDS, "generation": generation})
        after, listed = bridge("advanced-resets", {}), bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": "reset_message"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-reset-add", "with": [added]},
                 {"do": "reply", "key": "advanced-resets", "with": [after]},
                 {"do": "reply", "key": "advanced-list", "with": [listed]},
                 {"do": "reset_add", "family": "codex 300", "ordinal": "3", "words": WORDS,
                  "find": {"search": "RELEASE", "thread": FOUND}},
                 {"do": "look"}]
        return "en", {"answers": [True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def editor_only(cls, bridge, answer, find):
        reply = cls.counted(bridge, "prompt_queue")
        script = cls.opening(bridge, "en")
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        script["advanced-conversations"] = [answer]
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": "prompt_queue"},
                 {"do": "look"}, {"do": "editor", "find": find, "words": WORDS, "press": "cancel"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_none(cls, bridge):
        return cls.editor_only(bridge, ANSWER, {"search": "zzz", "press": "cancel"})

    @classmethod
    def scenario_failed(cls, bridge):
        return cls.editor_only(bridge, ok({"done": False, "refusal": "state_unavailable"}), {"press": "cancel"})

    # ---------------------------------------------------------------- tests
    def test_the_editor_finds_a_conversation_by_its_name_and_the_saved_message_names_it(self):
        """Fails with Find a conversation reverted: the editor offers only what Pending and History list, so the
        conversation cannot be chosen and the message is never saved to it."""
        result, expected = self.of("scenario_editor")
        words = expected["words"]
        (editor,) = result["dialogs"]
        found = editor["find"]
        self.assertEqual(editor["find_button"], words["page.find.button"])
        self.assertEqual(found["rows"], [NAME] + [name for _, name in OTHERS], "the bridge's order, newest first")
        self.assertEqual(found["rows_after"], [NAME], "typing keeps the conversations whose name holds it, in any case")
        self.assertEqual(found["picked"], FOUND)
        self.assertNotIn(FOUND, [each["thread_id"] for each in expected["pending"]], "neither list had it")
        self.assertIn(NAME, found["offered"])
        self.assertTrue(found["taken"])
        self.assertEqual(sent(result, "advanced-conversations"), [{}], "asked once, with no argument")
        (request,) = sent(result, "advanced-prompt-add")
        self.assertEqual((request["thread_id"], request["words"]), (FOUND, WORDS))
        self.assertTrue(editor["taken"])
        saved = result["looks"][-1]["pending_rows"]
        self.assertTrue(any(NAME in row[0] for row in saved), "Pending names the conversation: %r" % (saved,))

    def test_the_pickers_own_conversations_come_first_and_the_dialog_reads_as_the_window_does(self):
        result, expected = self.of("scenario_editor")
        words = expected["words"]
        (editor,) = result["dialogs"]
        found = editor["find"]
        offered = found["offered"]
        self.assertEqual(offered.index(NAME), len(offered) - 1, "the found one after Pending's and History's")
        self.assertEqual(found["title"], words["page.find.title"])
        self.assertEqual(found["search_name"], words["page.find.search"])
        self.assertEqual(found["buttons"], [words["page.find.use"], "Cancel"])
        self.assertTrue(found["accept"], "Enter presses Use this conversation")
        self.assertFalse(found["use_before"], "nothing chosen yet")
        self.assertEqual(found["column"], words["page.resets.field.conversation"])

    def test_a_reset_message_finds_one_too_and_the_rule_names_it(self):
        result, expected = self.of("scenario_reset")
        (found,) = result["dialogs"]
        self.assertEqual(found["rows_after"], [NAME], "RELEASE finds Release notes plan")
        self.assertEqual(found["picked"], FOUND)
        self.assertTrue(found["taken"])
        (request,) = sent(result, "advanced-reset-add")
        self.assertEqual((request["thread_id"], request["words"]), (FOUND, WORDS))
        self.assertIn(NAME, str(result["looks"][-1]), "the rule's line names the conversation")

    def test_no_match_and_an_unreadable_list_are_said_and_nothing_can_be_used(self):
        for name, key in (("scenario_none", "page.find.none"), ("scenario_failed", "page.find.failed")):
            result, expected = self.of(name)
            (editor,) = result["dialogs"]
            found = editor["find"]
            self.assertEqual(found["said"], expected["words"][key], name)
            self.assertEqual(found["rows_after"], [], name)
            self.assertFalse(found["use_enabled"], name)
            self.assertFalse(found["taken"], name)
        none = self.of("scenario_none")[0]["dialogs"][0]["find"]
        self.assertEqual(none["rows_after"], [])
        self.assertEqual(sent(self.of("scenario_none")[0], "advanced-prompt-add"), [], "cancelled: nothing is sent")

    def test_cancel_chooses_nothing(self):
        found = self.of("scenario_none")[0]["dialogs"][0]["find"]
        self.assertNotIn(FOUND, found["offered"])


if __name__ == "__main__":
    unittest.main()
