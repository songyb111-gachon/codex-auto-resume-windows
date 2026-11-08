"""Switch to this account on the saved-accounts card (v0.6.22 final, the owner's 2026-11-08; advanced/gui/AdvancedAccounts.cs
and AdvancedMeter.cs), read as source: the button on each saved row but the one in use and only where the row's state can
be switched to; one question first, Cancel the default; the card under both account capabilities' columns, one
implementation; and every switch state and refusal the bridge answers said in the catalog's words.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import guiscan  # noqa: E402
from codex_auto_resume_advanced.codex import swap  # noqa: E402
from codex_auto_resume_advanced.engine import autoswitch as engine  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Refusal  # noqa: E402

CARD = ac.ROOT / "advanced" / "gui" / "AdvancedAccounts.cs"
METER = ac.ROOT / "advanced" / "gui" / "AdvancedMeter.cs"
DIALOG = ac.ROOT / "gui" / "DashboardActions.cs"
PAGE = ac.ROOT / "advanced" / "gui" / "AdvancedPage.cs"


def code(path) -> str:
    """The source without its // comments, so a word in a comment never passes for code."""
    return re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))


def member(name, path=CARD) -> str:
    """One method of the file, by its braces (guiscan's block), found by its declaration - never a call."""
    text = code(path)
    found = re.search(r"(?m)^[ \t]*(?:(?:private|internal|static)[ \t]+)*[\w<>,\[\]]+[ \t]+%s[ \t]*\(" % re.escape(name),
                      text)
    if found is None:
        raise AssertionError("%s has no method %s" % (path.name, name))
    return guiscan._block(text, found.start())


class ButtonTests(unittest.TestCase):
    def test_it_is_offered_only_on_other_rows_that_can_be_switched_to(self):
        """Fails if the account in use, a row needing a new sign-in or one that cannot be opened got the button."""
        switchable = member("AccountsSwitchable")
        self.assertIn('if (Equals(Get(row, "in_use"), true) || !Equals(Get(advancedAccounts, "offered"), true)) return false;',
                      switchable)
        self.assertIn('return state == "ready" || state == "exhausted";', switchable)
        build = member("BuildAccounts")
        self.assertRegex(build, r"if \(AccountsSwitchable\(row\)\)\s*\{[^}]*MakeButton\(Word\(\"page\.accounts\.switch\"")
        self.assertIn('AccountsRow(check, Equals(Get(row, "in_use"), true))', build)

    def test_it_stands_on_a_line_of_its_own_under_the_meters(self):
        """Fails with the button put back beside the row: it took the account's line's room, and the layout audit found
        that line cut off in de, it, ru, uk and vi (2026-11-08)."""
        build = member("BuildAccounts")
        meters = build.index("card.Controls.Add(AccountsMeters(row));")
        line = build.index("if (switchTo != null) card.Controls.Add(AccountsSwitchLine(switchTo));")
        self.assertLess(meters, line, "the button comes after the meters")
        self.assertNotIn("switchTo", member("AccountsRow", METER), "the row itself keeps only \"in use\"")
        self.assertIn("switchTo.Anchor = AnchorStyles.Left;", member("AccountsSwitchLine", METER))

    def test_it_is_enabled_only_where_codex_keeps_its_sign_in_in_a_file_and_no_switch_runs(self):
        update = member("UpdateAccountsButtons")
        self.assertIn("foreach (Button switchTo in accountsSwitches) switchTo.Enabled = usable && !switching;", update)
        self.assertIn('accountsSwitches.Clear();', member("ForgetAccountsCard"))


class QuestionTests(unittest.TestCase):
    def test_it_asks_once_before_it_switches(self):
        """Fails with the question taken out, or asked after the request: Codex would close without a word."""
        switch = member("SwitchAccount")
        self.assertIn('if (!AskAdvanced(Word("page.confirm.accounts_switch"', switch)
        self.assertLess(switch.index("AskAdvanced("), switch.index('AdvancedCall("advanced-accounts-switch"'))
        self.assertIn('"{\\"id\\":" + Json.Escape(id) + "}"', switch, "the row's id goes escaped")

    def test_cancel_is_the_default(self):
        """AskAdvanced's question is the window's Dialog with Cancel as its `away` - what Enter presses."""
        self.assertIn('return Dialog(question, affirm, S("action.cancel", "Cancel"), choice);', code(PAGE))
        dialog = DIALOG.read_text(encoding="utf-8")
        self.assertIn("wears the accent and is what Enter presses", dialog)

    def test_it_says_what_closes_what_may_be_lost_what_is_saved_and_as_whom_codex_starts(self):
        import json
        words = json.loads((ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales" / "en.json")
                           .read_text(encoding="utf-8"))["page.confirm.accounts_switch"]
        for said in ("The Codex app closes", "anything not yet sent in its window may be lost",
                     "The account in use is saved back", "Codex starts again as {account}"):
            self.assertIn(said, words)


class BothCardsTests(unittest.TestCase):
    def test_one_card_under_both_account_capabilities(self):
        """Fails if the card showed under account_switch only while the automatic switch is hidden (before 2026-11-08)."""
        here = member("AccountsHere")
        self.assertIn("return (id == AccountsId || id == AccountId) && (Standing(item) || AccountsKept());", here)
        self.assertIn("bool standing = Standing(item);", member("BuildAccounts"))
        self.assertIn("(advancedOpen != AccountsId && advancedOpen != AccountId)", member("PollAccounts"))


class SaidTests(unittest.TestCase):
    def test_each_ending_the_bridge_answers_is_said(self):
        said = member("AccountsSwitchState")
        for state in ("switching", swap.SWITCHED, swap.NOT_STARTED, swap.NOT_PUT_BACK) + engine.MANUAL_NOTHING:
            with self.subTest(state):
                self.assertIn('state == "%s"' % state, said)
        self.assertIn('Word("page.accounts.switch_undone"', said, "every other ending: not finished and undone")
        self.assertIn('"switching"', member("AccountsWaiting"), "the card is read again while it runs")

    def test_each_refusal_is_said(self):
        refusal = member("AccountsRefusal")
        for word in (Refusal.ACCOUNT_IN_USE, Refusal.ACCOUNT_NOT_READY, Refusal.SIGN_IN_NOT_FILE, Refusal.RESTART_BUSY,
                     Refusal.OTHER_ENGINE, Refusal.ACCOUNTS_HELD):
            with self.subTest(word):
                self.assertIn('refusal == "%s"' % word.value, refusal)


if __name__ == "__main__":
    unittest.main()
