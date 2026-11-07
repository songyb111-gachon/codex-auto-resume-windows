# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The Advanced features page says how a capability stands on this Codex: measured by a person, or checked automatically.

The card's head and the question before Turn on both carry the line, in words a person can tell apart, in the language the
page is in; a grade with no line of its own adds none. Every reply is the real bridge's, over a record written the way the
watcher writes it; nothing reads Codex and nothing starts one.

GUI test module: compiles real executables, so it runs on its own.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_page_auto_check.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, snapshot  # noqa: E402

CAPABILITY = "model_fallback"
EARLIER = "codex-cli 0.163.0-alpha.10.2"


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def graded(cls, bridge, locale, grade, version=None):
        script = cls.opening(bridge, locale)
        script["advanced-statement " + CAPABILITY][0]["result"]["check"] = {"grade": grade, "version": version}
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": CAPABILITY},
                 {"do": "look"}, {"do": "press", "button": "on"}]
        return locale, {"answers": [False], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_checked(cls, bridge):
        return cls.graded(bridge, "en", "auto_checked", EARLIER)

    @classmethod
    def scenario_checked_korean(cls, bridge):
        return cls.graded(bridge, "ko", "auto_checked", EARLIER)

    @classmethod
    def scenario_whole(cls, bridge):
        return cls.graded(bridge, "en", "auto_checked")

    @classmethod
    def scenario_measured(cls, bridge):
        return cls.graded(bridge, "en", "measured")

    @classmethod
    def scenario_offered(cls, bridge):
        return cls.graded(bridge, "en", "offered_only")

    @classmethod
    def scenario_failed(cls, bridge):
        return cls.graded(bridge, "en", "failed_still_offered")

    @classmethod
    def scenario_unmeasured(cls, bridge):
        return cls.graded(bridge, "en", "unmeasured")

    def shown(self, name, key, **fields):
        result, expected = self.of(name)
        line = expected["words"][key]
        for token, value in fields.items():
            line = line.replace("{%s}" % token, value)
        head = result["looks"][0]["cards"][0]
        return result, line, head

    def test_checked_automatically_says_so_on_the_card_and_in_the_question(self):
        result, line, head = self.shown("scenario_checked", "page.check.auto_checked", version=EARLIER)
        self.assertIn(line, head)
        self.assertIn("checked automatically", line)
        self.assertIn(EARLIER, line)
        self.assertIn(line, result["asked"][0])

    def test_it_is_said_in_the_person_s_language(self):
        _result, line, head = self.shown("scenario_checked_korean", "page.check.auto_checked", version=EARLIER)
        self.assertIn(line, head)
        self.assertIn("자동", line)

    def test_a_person_can_tell_the_two_grades_apart(self):
        _result, measured, head = self.shown("scenario_measured", "page.check.measured")
        self.assertIn(measured, head)
        self.assertIn("by a person", measured)
        self.assertNotIn("automatically", measured)
        _result, whole, head = self.shown("scenario_whole", "page.check.auto_checked_whole")
        self.assertIn(whole, head)
        self.assertIn("automatically", whole)

    def test_the_lesser_grades_say_what_they_cannot_show(self):
        _result, offered, head = self.shown("scenario_offered", "page.check.offered_only")
        self.assertIn(offered, head)
        self.assertIn("still needs measuring", offered)
        _result, failed, head = self.shown("scenario_failed", "page.check.failed_still_offered")
        self.assertIn(failed, head)
        self.assertIn("does not undo", failed)

    def test_a_grade_with_no_line_adds_none(self):
        result, expected = self.of("scenario_unmeasured")
        head = " ".join(result["looks"][0]["cards"][0])
        for key, words in expected["words"].items():
            if key.startswith("page.check."):
                self.assertNotIn(words.split("{")[0], head, key)


if __name__ == "__main__":
    unittest.main()
