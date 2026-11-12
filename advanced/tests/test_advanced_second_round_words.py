"""v0.6.23 second round R3 and R1's card word.

R3: usage_pause's card showed "Sends a day, all conversations together 1" and "in any one conversation 1": limits that
never bind it - its stops and continuations are IPC writes, not the ledger's sends. Its listing now says it sends
nothing the ceilings count (`sends` False), and its card says what does bound it in place of the day's numbers.

R1: a switch whose account could not be read after the swap ends UNVERIFIED (codex/swap.py); its card says so in its own
words, not "did not finish and was undone", which is what it is not.

Read as source (guiscan); the words in every catalog.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import guiscan  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.codex import swap  # noqa: E402
from codex_auto_resume_advanced.registry import USAGE_PAUSE  # noqa: E402

LOCALES = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales"
GUI = ac.ROOT / "advanced" / "gui"
PAUSE_WORDS, UNVERIFIED_WORDS = "page.pause_limits", "page.accounts.switch_unverified"


def member(source, name) -> str:
    """One method of the advanced window's SettingsForm part in `source`, by its braces (guiscan's own block)."""
    body = guiscan.type_body("SettingsForm", (GUI / source).read_text(encoding="utf-8"))
    found = re.search(r"(?m)^[ \t]*private[ \t]+[\w<>,\[\]]+[ \t]+%s\(" % re.escape(name), body)
    if found is None:
        raise AssertionError(name)
    return guiscan._block(body, found.start())


def catalogs():
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(LOCALES.glob("*.json"))}


class StopNearALimitSaysItsOwnBound(unittest.TestCase):
    def test_its_listing_says_no_ceiling_counts_its_sends(self):
        """Fails with `sends` left to its points: GATES made it True, and the page showed 1 and 1 as limits."""
        self.assertIs(USAGE_PAUSE.sends, False)

    def test_its_card_says_its_bound_in_place_of_the_days_numbers(self):
        cards = member("AdvancedPage.cs", "BuildAdvancedCards")
        mine = cards.index('Str(item, "id") == "usage_pause"')
        self.assertLess(mine, cards.index('Fact(numbers, Word("page.per_day"'), "before the day's numbers, not beside")
        self.assertIn('Word("%s"' % PAUSE_WORDS, cards[mine:cards.index('Fact(numbers, Word("page.per_day"')])

    def test_the_bound_is_said_in_every_language(self):
        found = catalogs()
        self.assertEqual(len(found), 22)
        english = found["en"][PAUSE_WORDS]
        self.assertIn(english, member("AdvancedPage.cs", "BuildAdvancedCards"), "the window's own fallback")
        for locale, words in found.items():
            with self.subTest(locale=locale):
                self.assertTrue(words.get(PAUSE_WORDS))
                if locale != "en":
                    self.assertNotEqual(words[PAUSE_WORDS], english)
        self.assertIn(PAUSE_WORDS, statement.PAGE_KEYS)


class AnUnverifiedSwitchSaysSo(unittest.TestCase):
    def test_the_card_has_its_own_words_for_it(self):
        """Fails without its branch: an unverified switch fell to "did not finish and was undone"."""
        said = member("AdvancedAccounts.cs", "AccountsSwitchState")
        branch = said.index('state == "%s"' % swap.UNVERIFIED)
        self.assertIn('Word("%s"' % UNVERIFIED_WORDS, said[branch:said.index("page.accounts.switch_undone")])

    def test_the_words_name_the_account_in_every_language(self):
        found = catalogs()
        self.assertIn(found["en"][UNVERIFIED_WORDS], member("AdvancedAccounts.cs", "AccountsSwitchState"))
        for locale, words in found.items():
            with self.subTest(locale=locale):
                self.assertIn("{account}", words[UNVERIFIED_WORDS])
        self.assertIn(UNVERIFIED_WORDS, statement.PAGE_KEYS)


if __name__ == "__main__":
    unittest.main()
