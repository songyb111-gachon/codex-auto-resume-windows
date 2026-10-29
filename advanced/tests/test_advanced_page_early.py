# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""early_reset on Pending in the window itself (v0.6.19, issue #50; the owner's decision of 2026-10-24).

It has no line, no Check now and no settings button on Pending any more - nothing on Pending grows. While the status
carries it (the capability on), Why it is waiting says, for a recovery that waits for a usage limit and under the usage
readings core says there, when early reset last read usage, what it read and whether anything went on. A person's Retry
now or Rescan asks the watcher for one usage reading; while early_reset stands on, the window also asks for its probe
(advanced-early-check, naming no row), so that reading is one of its two. With it off, nothing of it is said or asked.
Driven through the page's own hooks with the real bridge's answers, made in a home of its own.

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
USAGE_ROW = 0          # the fullest snapshot's first Pending row waits for a usage reset an hour ahead
OTHER_ROW = 1          # and its second for a network failure's retry


def with_line(reply, **line):
    shown = copy.deepcopy(reply)
    shown["status"]["advanced"]["early_check"] = dict(
        {"checked_at": None, "read": None, "available_at": None, "confirm_at": None, "lifted_at": None,
         "lifted": False, "waiting": 1, "asked": False}, **line)
    return shown


def parts(text):
    """A catalog sentence's words around its {time}: what a sentence made from it starts and ends with."""
    head, _, tail = text.partition("{time}")
    return head, tail


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def scenario_on(cls, bridge):
        cls.watched(bridge, CAP, state="armed")
        script = cls.opening(bridge, "en")
        reply = snapshot(on=1)
        limited = with_line(reply, checked_at=ac.NOW - 60, read="still_limited")
        lifted = with_line(reply, checked_at=ac.NOW - 5, read="available", available_at=ac.NOW - 305,
                           confirm_at=ac.NOW - 5, lifted_at=ac.NOW - 5, lifted=True)
        steps = [{"do": "snapshot", "reply": limited}, {"do": "page", "name": "pending"},
                 {"do": "pending_select", "index": USAGE_ROW}, {"do": "look"},
                 {"do": "snapshot", "reply": lifted}, {"do": "pending_select", "index": USAGE_ROW}, {"do": "look"},
                 {"do": "pending_select", "index": OTHER_ROW}, {"do": "look"},
                 {"do": "reply", "key": "advanced-early-check",
                  "with": [ok({"done": True, "refusal": None, "check": "asked"})]},
                 {"do": "usage_asked"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_off(cls, bridge):
        """early_reset off: the status carries none of it; Why it is waiting says nothing of it and nothing is asked."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot(on=0)}, {"do": "page", "name": "pending"},
                 {"do": "pending_select", "index": USAGE_ROW}, {"do": "usage_asked"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- tests
    def test_why_it_is_waiting_says_what_early_reset_last_read(self):
        """Fails with UsageNoted reverted: Pending says nothing of early_reset."""
        result, expected = self.of("scenario_on")
        words = expected["words"]
        limited, lifted, _other, _asked = result["looks"]
        for look, key in ((limited, "page.early.limited"), (lifted, "page.early.lifted")):
            with self.subTest(key):
                head, tail = parts(words[key])
                said = [line for line in (look["explain_note"] or "").split("\n") if line.startswith(head)]
                self.assertEqual(len(said), 1, look["explain_note"])
                self.assertTrue(said[0].endswith(tail), said[0])
                self.assertEqual(said[0], look["early"]["text"])

    def test_it_is_said_only_for_a_recovery_that_waits_for_a_usage_limit(self):
        result, expected = self.of("scenario_on")
        head, _tail = parts(expected["words"]["page.early.lifted"])
        other = result["looks"][2]
        self.assertNotIn(head, other["explain_note"] or "")

    def test_pending_has_no_line_and_no_button_of_its_own(self):
        """Fails with the line back: Check now and Early reset settings stand above Pending's list."""
        result, _expected = self.of("scenario_on")
        for look in result["looks"]:
            self.assertNotIn("Check now", look["pending_buttons"])
            self.assertNotIn("Early reset settings", look["pending_buttons"])
        self.assertTrue(result["looks"][0]["retry_enabled"], "Retry now is the click that reads usage for this row")

    def test_a_clicks_reading_asks_for_early_resets_probe_naming_no_row(self):
        """Fails with UsageAsked reverted: the click's reading is not one of early reset's two."""
        result, _expected = self.of("scenario_on")
        self.assertEqual(sent(result, "advanced-early-check"), [{}])

    def test_off_nothing_is_said_or_asked(self):
        result, expected = self.of("scenario_off")
        (look,) = result["looks"]
        self.assertIsNone(look["early"]["text"])
        head, _tail = parts(expected["words"]["page.early.limited"])
        self.assertNotIn(head, look["explain_note"] or "")
        self.assertEqual(sent(result, "advanced-early-check"), [])


if __name__ == "__main__":
    unittest.main()
