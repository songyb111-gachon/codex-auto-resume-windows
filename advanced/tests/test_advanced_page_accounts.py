"""The saved-accounts card of the automatic account switch (v0.6.22, advanced/gui/AdvancedAccounts.cs), read as source.

The card is the Settings page's own pieces - a group, help lines, flat check rows and card buttons - so it takes both
themes, both designs and the Arabic and Hebrew mirror from the page; it draws no colour, icon or tile of its own. Every
word it says is in statement.PAGE_KEYS and every catalog, and every bridge command it sends is one control/autoswitch.py
answers, with only the arguments the bridge takes. The capability waited hidden in registry.WAITING until MPROFILE and
MSWAP passed (2026-11-06) and is offered now; the page audit is handed its fullest data (pagecase.audit_data).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand  # noqa: E402

CARD = ac.ROOT / "advanced" / "gui" / "AdvancedAccounts.cs"
PAGE = ac.ROOT / "advanced" / "gui" / "AdvancedPage.cs"


def source(path=CARD) -> str:
    return path.read_text(encoding="utf-8")


class CardSourceTests(unittest.TestCase):
    def test_it_is_compiled_into_the_advanced_window(self):
        listed = [line.split("#", 1)[0].strip() for line in
                  (ac.ROOT / "advanced" / "gui" / "window.sources").read_text(encoding="utf-8").splitlines()]
        self.assertIn("advanced/gui/AdvancedAccounts.cs", listed)

    def test_the_page_reads_builds_forgets_and_enables_it(self):
        """Fails with any of the page's five hooks taken out: the card would never be read, drawn or enabled."""
        page = source(PAGE)
        for call in ("ReadAccounts(after)", "BuildAccounts(item)", "ForgetAccountsCard()", "UpdateAccountsButtons(idle)",
                     "AccountsShown(item)"):
            with self.subTest(call):
                self.assertIn(call, page)

    def test_it_draws_only_the_page_s_own_pieces(self):
        """Flat check rows, help lines, card buttons in a group - no tile, panel, picture, icon or colour of its own."""
        card = source()
        for piece in ("NewGroup(", "NewCheck(", "HelpText(", "CardButton("):
            self.assertIn(piece, card)
        for foreign in ("new Panel", "PictureBox", "Icon", "BackColor", "Color.", "new Button", "new Label", "Tile"):
            with self.subTest(foreign):
                self.assertNotIn(foreign, card)

    def test_every_word_is_a_page_key_in_every_catalog(self):
        card = source()
        used = set(re.findall(r'Word\("(page\.[a-z_.]+)"', card))
        self.assertTrue({"page.accounts.title", "page.accounts.not_file", "page.accounts.add", "page.accounts.save",
                         "page.accounts.delete", "page.accounts.delete_all"} <= used)
        for key in sorted(used):
            with self.subTest(key):
                self.assertIn(key, statement.PAGE_KEYS)
                for locale_file in sorted((ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales")
                                          .glob("*.json")):
                    words = json.loads(locale_file.read_text(encoding="utf-8"))
                    self.assertTrue(words.get(key, "").strip(), locale_file.name)

    def test_every_command_it_sends_is_answered_with_the_arguments_the_bridge_takes(self):
        card = source()
        sent = re.findall(r'AdvancedCall\("([a-z-]+)", "(.*?)"', card)
        self.assertEqual(sorted({command for command, _argument in sent}),
                         ["advanced-accounts", "advanced-accounts-add", "advanced-accounts-delete",
                          "advanced-accounts-save"])
        for command, argument in sent:
            with self.subTest(command):
                names = set(re.findall(r'\\"([a-z_]+)\\"', argument))
                self.assertLessEqual(names, set(surfaces.ARGUMENTS[BridgeCommand(command)]))
        self.assertIn('"{\\"id\\":" + Json.Escape(', card, "an id goes escaped")

    def test_it_says_each_state_the_bridge_answers(self):
        from codex_auto_resume_advanced import profiles
        card = source()
        for state in profiles.STATES:
            with self.subTest(state):
                self.assertIn('state == "%s"' % state if state != profiles.DAMAGED else "page.accounts.state.damaged",
                              card)


if __name__ == "__main__":
    unittest.main()
