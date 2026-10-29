# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Steer the running turn in the window itself (v0.6.20, issue #50 item 2 - steer_send): the prompt queue's editor offers
"Now, into the turn that is running (steer)" as When only while steer_send stands on and only for a new message; chosen,
the time fields are not asked, the while-running cards give way to the warning that the Codex app does not show the
steered line, in the danger colour, and the accent button reads Steer now and sends advanced-steer - the conversation,
the words and the generation, nothing else. History lists each steer as its own row - its conversation, accepted, may
have been delivered or refused, Steer - and, chosen, says the words that were sent and what the outcome means. Driven
through the page's own hooks, the dialog built and never shown, with the real bridge's answers made in a home of its own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_steer.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402
from codex_auto_resume_advanced.control import steer as steer_control  # noqa: E402
from codex_auto_resume_advanced.vocabulary import SteerReason, SteerState  # noqa: E402

WORDS = "Stop rewriting the tests; fix the parser instead."


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def armed(cls, bridge, steer=True):
        cls.watched(bridge, "prompt_queue", state="armed")
        if steer:
            cls.watched(bridge, "steer_send", state="armed")
        return snapshot(on=2 if steer else 1)

    @classmethod
    def opened(cls, bridge, shot, extra_steps, script_more=None):
        script = cls.opening(bridge, "en")
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        script.update(script_more or {})
        steps = [{"do": "snapshot", "reply": shot}, {"do": "show"}, {"do": "choose", "id": "prompt_queue"},
                 {"do": "look"}] + extra_steps
        words = script["advanced-words"][0]["result"]["words"]
        return "en", {"script": script, "steps": steps}, {"words": words, "thread": shot["pending"][0]["thread_id"]}

    @classmethod
    def scenario_steer(cls, bridge):
        shot = cls.armed(bridge)
        thread = shot["pending"][0]["thread_id"]
        with mock.patch.object(steer_control, "latest_status", lambda home, thread_id: "inProgress"):
            made = bridge("advanced-steer", {"thread_id": thread, "words": WORDS,
                                             "generation": bridge("advanced-list", {})["result"]["generation"]})
        assert made["result"]["done"], made
        return cls.opened(bridge, shot, [{"do": "editor", "thread": thread, "words": WORDS, "when": "steer",
                                          "press": "save"}], {"advanced-steer": [made]})

    @classmethod
    def scenario_steer_refused(cls, bridge):
        shot = cls.armed(bridge)
        thread = shot["pending"][0]["thread_id"]
        with mock.patch.object(steer_control, "latest_status", lambda home, thread_id: "completed"):
            refused = bridge("advanced-steer", {"thread_id": thread, "words": WORDS,
                                                "generation": bridge("advanced-list", {})["result"]["generation"]})
        return cls.opened(bridge, shot, [{"do": "editor", "thread": thread, "words": WORDS, "when": "steer",
                                          "press": "save"}], {"advanced-steer": [refused]})

    @classmethod
    def scenario_steer_off(cls, bridge):
        shot = cls.armed(bridge, steer=False)
        return cls.opened(bridge, shot, [{"do": "editor", "thread": shot["pending"][0]["thread_id"], "words": WORDS,
                                          "press": "cancel"}])

    @classmethod
    def scenario_history(cls, bridge):
        shot = cls.armed(bridge)
        thread = shot["pending"][0]["thread_id"]
        state = bridge.plug.runtime.state
        for index, (outcome, reason) in enumerate(((SteerState.ACCEPTED, None), (SteerState.UNCONFIRMED, None),
                                                   (SteerState.REFUSED, SteerReason.NOT_HELD))):
            made = state.add_steer(thread, "%s %d" % (WORDS, index), "00000000-0000-7000-8000-00000000000%d" % index,
                                   at=ac.NOW - 600 + index)
            if outcome != SteerState.REFUSED:
                state.claim_steer(made)
            state.settle_steer(made, outcome, reason, at=ac.NOW - 500 + index)
        counted = copy.deepcopy(shot)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        script["advanced-prompts"] = [bridge("advanced-prompts", {})]
        recoveries = len(counted["history"])
        steps = [{"do": "snapshot", "reply": counted}, {"do": "page", "name": "history"}, {"do": "look"}]
        steps += [step for index in range(3) for step in ({"do": "history_select", "index": recoveries + index},
                                                          {"do": "look"})]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "recoveries": recoveries}

    # ---------------------------------------------------------------- tests
    def test_steer_is_a_when_of_its_own_with_the_warning_and_steer_now(self):
        result, expected = self.of("scenario_steer")
        words = expected["words"]
        (editor,) = result["dialogs"]
        self.assertEqual(editor["whens"][-1], words["page.editor.when.steer"])
        self.assertTrue(editor["steer_shown"])
        self.assertTrue(editor["steer_colour"], "the warning in the danger colour")
        self.assertEqual(editor["steer_warning"], words["page.editor.steer.warning"])
        self.assertIn("does not show the steered line", editor["steer_warning"])
        self.assertFalse(editor["mode_shown"])
        self.assertFalse(editor["after_turn_shown"])
        self.assertFalse(editor["hour_enabled"])
        self.assertFalse(editor["depends_enabled"])
        self.assertEqual(editor["buttons_after"], [words["page.editor.steer.send"], "Cancel"])
        self.assertTrue(editor["taken"])
        self.assertEqual(editor["saved"], -1, "no prompt is saved: nothing is chosen on Pending")

    def test_steer_now_sends_the_conversation_the_words_and_the_generation_alone(self):
        result, expected = self.of("scenario_steer")
        (request,) = sent(result, "advanced-steer")
        self.assertEqual(set(request), {"thread_id", "words", "generation"})
        self.assertEqual((request["thread_id"], request["words"]), (expected["thread"], WORDS))
        self.assertEqual(sent(result, "advanced-prompt-add"), [], "a steer is not a scheduled message")

    def test_refused_the_words_stay_and_the_reason_is_said(self):
        result, expected = self.of("scenario_steer_refused")
        (editor,) = result["dialogs"]
        self.assertFalse(editor["taken"])
        self.assertEqual(editor["words_after"], WORDS)
        self.assertEqual(editor["said"], expected["words"]["page.refused.no_turn_running"])

    def test_steer_is_offered_only_while_it_stands_on(self):
        result, expected = self.of("scenario_steer_off")
        (editor,) = result["dialogs"]
        self.assertNotIn(expected["words"]["page.editor.when.steer"], editor["whens"])
        self.assertEqual(len(editor["whens"]), 4)
        self.assertFalse(editor["steer_shown"])

    def test_history_lists_each_steer_and_says_its_words_and_outcome(self):
        result, expected = self.of("scenario_history")
        words, recoveries = expected["words"], expected["recoveries"]
        looks = result["looks"]
        opened = looks[0]["scheduled"]
        kinds = opened["history_kinds"][recoveries:]
        self.assertEqual(kinds, ["steer", "steer", "steer"])
        rows = opened["history"][recoveries:]
        self.assertEqual([row[1] for row in rows], [words["page.steer.state.refused"],
                                                    words["page.steer.state.unconfirmed"],
                                                    words["page.steer.state.accepted"]], "newest first, three outcomes")
        self.assertEqual({row[2] for row in rows}, {words["page.pending.kind.steer"]})
        notes = [look["scheduled"]["history_note"] for look in looks[1:]]
        self.assertTrue(notes[0].startswith(words["page.steer.sent"].replace("{words}", WORDS + " 2")))
        self.assertIn(words["page.steer.reason.not_held"], notes[0])
        self.assertIn(words["page.steer.note.unconfirmed"], notes[1])
        self.assertIn(words["page.steer.note.accepted"], notes[2])
        self.assertIn(WORDS + " 0", notes[2])


if __name__ == "__main__":
    unittest.main()
