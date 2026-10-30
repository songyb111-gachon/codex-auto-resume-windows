# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Start the 5-hour window early: its card says it starts nothing while it has no occasion (v0.6.20-beta.4).

On, with none of its three times of day picked and Start right after a reset off, the watcher has nothing to start at:
the head card says so in the accent, under where it stands. It is not there with a time picked, with Start right after
a reset on, or with the capability off. Each state is the real bridge's list with the options set as that state has
them; nothing here reads the real installation or a real Codex, and the window is never shown.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_anchor_hint.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, snapshot  # noqa: E402

CAP = "window_anchor"
KEY = "page.anchor.needs_occasion"
TIME_OFF, SWITCH_ON, SWITCH_OFF = 1, 1, 2  # a time off is 1; a switch is on at 1 and off at 2
LOCALES = ("ar", "de", "en", "es", "fr", "he", "id", "it", "ja", "ko", "pl", "pt-BR", "ru", "tr", "uk", "vi", "zh-CN",
           "zh-TW")


def scenario(bridge, state, times=(), after=None):
    """The capability in `state`, its times of day `times` (minutes of the day, three at most) and Start right after a
    reset `after` (1 on, 2 off, None: the list carries no value for it); its card read once."""
    if state == "armed":
        PageCase.watched(bridge, CAP, state="armed")
    script = PageCase.opening(bridge, "en")
    (item,) = [each for each in script["advanced-list"][0]["result"]["capabilities"] if each["id"] == CAP]
    held = {"anchor_at_1": TIME_OFF, "anchor_at_2": TIME_OFF, "anchor_at_3": TIME_OFF}
    for index, minute in enumerate(times):
        held["anchor_at_%d" % (index + 1)] = anchor.encode_time(minute // 60, minute % 60)
    if after is not None:
        held["anchor_after_reset"] = after
    kept = []
    for option in item["options"]:
        if option["key"] == "anchor_after_reset" and after is None:
            option = {key: value for key, value in option.items() if key != "value"}
        elif option["key"] in held:
            option = dict(option, value=held[option["key"]])
        kept.append(option)
    item["options"] = kept
    steps = [{"do": "snapshot", "reply": snapshot(on=1 if state == "armed" else 0)}, {"do": "show"},
             {"do": "choose", "id": CAP}, {"do": "look"}]
    return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def scenario_no_occasion(cls, bridge):
        return scenario(bridge, "armed", after=SWITCH_OFF)

    @classmethod
    def scenario_a_time(cls, bridge):
        return scenario(bridge, "armed", times=(7 * 60,), after=SWITCH_OFF)

    @classmethod
    def scenario_after_a_reset(cls, bridge):
        return scenario(bridge, "armed", after=SWITCH_ON)

    @classmethod
    def scenario_off(cls, bridge):
        return scenario(bridge, "off", after=SWITCH_OFF)

    @classmethod
    def scenario_unstored(cls, bridge):
        return scenario(bridge, "armed")

    def head(self, name):
        result, expected = self.of(name)
        return result["looks"][0]["cards"][0], expected["words"][KEY]

    def test_it_says_it_starts_nothing_when_on_with_no_time_and_no_reset_to_start_after(self):
        """Fails with BuildAnchorLine's second line removed: the card says nothing of it."""
        head, line = self.head("scenario_no_occasion")
        self.assertIn(line, head)
        self.assertEqual(line, "It starts nothing until you pick a start time or turn on Start right after a reset.")

    def test_it_is_not_there_with_a_time_picked(self):
        """Fails with AnchorNeedsOccasion's time check removed."""
        head, line = self.head("scenario_a_time")
        self.assertNotIn(line, head)

    def test_it_is_not_there_with_start_right_after_a_reset_on(self):
        """Fails with AnchorNeedsOccasion's switch check removed."""
        head, line = self.head("scenario_after_a_reset")
        self.assertNotIn(line, head)

    def test_it_is_not_there_while_the_capability_is_off(self):
        """Fails with AnchorNeedsOccasion's state check removed."""
        head, line = self.head("scenario_off")
        self.assertNotIn(line, head)

    def test_it_is_not_there_where_the_list_carries_no_value_for_the_switch(self):
        """A choice the list does not carry is not guessed at as off."""
        head, line = self.head("scenario_unstored")
        self.assertNotIn(line, head)


class WordsTests(unittest.TestCase):
    def test_the_line_is_in_all_eighteen_catalogs_and_names_the_options_by_their_own_words(self):
        from codex_auto_resume_advanced import statement
        catalogs = Path(statement.__file__).parent / "locales"
        self.assertEqual(sorted(path.stem for path in catalogs.glob("*.json")), sorted(LOCALES))
        for locale in LOCALES:
            with self.subTest(locale):
                words = json.loads((catalogs / (locale + ".json")).read_text(encoding="utf-8"))
                line = words[KEY]
                self.assertTrue(line.strip())
                if locale != "en":
                    self.assertNotEqual(line, json.loads((catalogs / "en.json").read_text(encoding="utf-8"))[KEY])
                label = words["page.option.anchor_after_reset"]
                self.assertIn(label, line, "names Start right after a reset as the catalog does")
        self.assertIn(statement.PAGE_PREFIX + "anchor.needs_occasion", statement.PAGE_KEYS)


if __name__ == "__main__":
    unittest.main()
