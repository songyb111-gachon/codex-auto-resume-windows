# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""early_reset's line on Pending in the window itself (v0.6.19, issue #50): shown only while the status carries it (the
capability on), saying when it last read usage early, what it read and whether anything went on; Check now sends
advanced-early-check, naming no row, and says what came of it until a new reading says it; and the line's other button
opens the capability's own card on the Advanced features page, where its on/off is. Driven through the page's own
hooks with the real bridge's answers, made in a home of its own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_early.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, ok, sent, snapshot  # noqa: E402

CAP = "early_reset"


def with_line(reply, **line):
    shown = copy.deepcopy(reply)
    shown["status"]["advanced"]["early_check"] = dict(
        {"checked_at": None, "read": None, "available_at": None, "confirm_at": None, "lifted_at": None,
         "lifted": False, "waiting": 1, "asked": False}, **line)
    return shown


def parts(text):
    """A catalog sentence's words around its {time}: what a line made from it starts and ends with."""
    head, _, tail = text.partition("{time}")
    return head, tail


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def scenario_line(cls, bridge):
        cls.watched(bridge, CAP, state="armed")
        script = cls.opening(bridge, "en")
        reply = snapshot(on=1)
        limited = with_line(reply, checked_at=ac.NOW - 60, read="still_limited")
        lifted = with_line(reply, checked_at=ac.NOW - 5, read="available", available_at=ac.NOW - 305,
                           confirm_at=ac.NOW - 5, lifted_at=ac.NOW - 5, lifted=True)
        steps = [{"do": "snapshot", "reply": limited}, {"do": "page", "name": "pending"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-early-check",
                  "with": [ok({"done": True, "refusal": None, "check": "asked"})]},
                 {"do": "early_press", "button": "check"}, {"do": "look"},
                 {"do": "snapshot", "reply": limited}, {"do": "look"},
                 {"do": "snapshot", "reply": lifted}, {"do": "look"},
                 {"do": "reply", "key": "advanced-early-check",
                  "with": [ok({"done": True, "refusal": None, "check": "not_running"})]},
                 {"do": "early_press", "button": "check"}, {"do": "look"},
                 {"do": "early_press", "button": "settings"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_off(cls, bridge):
        """early_reset off: the status carries no line, and Pending has none."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot(on=0)}, {"do": "page", "name": "pending"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    # ---------------------------------------------------------------- tests
    def test_the_line_says_when_it_read_what_it_read_and_whether_anything_went_on(self):
        """Fails with the line reverted: Pending shows nothing of early_reset."""
        result, expected = self.of("scenario_line")
        words = expected["words"]
        first, _asked, _same, lifted, _stopped, _card = result["looks"]
        self.assertTrue(first["early"]["shown"])
        self.assertEqual((first["early"]["check"], first["early"]["settings"]),
                         (words["page.early.check_now"], words["page.early.settings"]))
        head, tail = parts(words["page.early.limited"])
        self.assertTrue(first["early"]["note"].startswith(head) and first["early"]["note"].endswith(tail),
                        first["early"]["note"])
        head, tail = parts(words["page.early.lifted"])
        self.assertTrue(lifted["early"]["note"].startswith(head) and lifted["early"]["note"].endswith(tail),
                        lifted["early"]["note"])

    def test_check_now_names_no_row_and_says_what_came_of_it_until_a_new_reading(self):
        result, expected = self.of("scenario_line")
        words = expected["words"]
        _first, asked, same, lifted, stopped, _card = result["looks"]
        self.assertEqual(sent(result, "advanced-early-check"), [{}, {}], "no row, no argument")
        self.assertEqual(asked["early"]["note"], words["page.early.asked"])
        self.assertEqual(same["early"]["note"], words["page.early.asked"], "the same reading: the answer stays")
        self.assertNotEqual(lifted["early"]["note"], words["page.early.asked"], "a new reading says it now")
        self.assertEqual(stopped["early"]["note"], words["page.early.not_running"])

    def test_its_settings_are_on_the_advanced_page_only(self):
        result, _expected = self.of("scenario_line")
        card = result["looks"][-1]
        self.assertEqual((card["page"], card["open"]), ("advanced", CAP))

    def test_off_there_is_no_line(self):
        result, _expected = self.of("scenario_off")
        (look,) = result["looks"]
        self.assertFalse(look["early"]["shown"])


if __name__ == "__main__":
    unittest.main()
