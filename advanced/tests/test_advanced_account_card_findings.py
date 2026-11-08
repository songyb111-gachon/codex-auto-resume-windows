"""The v0.6.22 reachability audit's findings on the saved-accounts card (outputs/plans/v0622-reachability-audit.md):
R4 - Add an account... works while Codex is signed out here, and the line under the heading says what is really the
case; M8 - no "every saved account is at its limit" with no other account saved; M9 - "The account was saved." is said
once; M10 - a Delete held by a switch or a read says so; M11 - Save the account in use asks first.

Every home is a temporary folder, every sign-in file a fixture of no one's; nothing real is read, closed or switched.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_autoswitch import EngineCase  # noqa: E402
from test_advanced_autoswitch_control import TWO, ControlCase  # noqa: E402
from test_advanced_autoswitch_swap import ONE  # noqa: E402
from codex_auto_resume_advanced.control import autoswitch as accounts  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Refusal  # noqa: E402

CARD = ac.ROOT / "advanced" / "gui" / "AdvancedAccounts.cs"


def card() -> str:
    return re.sub(r"//[^\n]*", "", CARD.read_text(encoding="utf-8"))


def method(name) -> str:
    text = card()
    start = text.index("private void %s(" % name) if "private void %s(" % name in text else text.index(
        "private string %s(" % name)
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError(name)


class AddWhileSignedOutTests(ControlCase):
    """R4."""

    def test_the_bridge_adds_while_codex_is_signed_out_here(self):
        """Adding signs in on a scratch home: no sign-in file in Codex's own home stops nothing."""
        self.on()
        (self.codex / "auth.json").unlink()
        self.assertEqual(accounts.view(self.rt, store=self.store, codex_home=self.codex, usage={})["store"], "no_file")
        started = []
        answer = accounts.add(self.rt, start=started.append, run=lambda paths, store: "0123456789abcdef")
        self.assertEqual((answer["done"], answer["add_state"]), (True, accounts.WAITING))
        started.pop()()
        self.assertEqual(accounts.view(self.rt, store=self.store, codex_home=self.codex, usage={})["add_state"],
                         accounts.ADDED)

    def test_the_card_offers_add_while_signed_out_and_says_why_save_cannot(self):
        """Fails with Add enabled on "usable" alone, or the line saying "outside a file" for a signed-out Codex."""
        buttons = method("UpdateAccountsButtons")
        self.assertIn('bool addable = usable || (listed && Str(advancedAccounts, "store") == "no_file");', buttons)
        self.assertIn('accountsAdd.Enabled = addable &&', buttons)
        self.assertIn("accountsSave.Enabled = usable;", buttons)
        line = method("AccountsStoreLine")
        self.assertRegex(line, r'if \(store == "no_file"\)\s*return Word\("page\.accounts\.no_file"')
        self.assertRegex(line, r'if \(store == "unreadable"\)\s*return Word\("page\.accounts\.unreadable"')
        self.assertIn('if (store == "usable") return null;', line)


class NothingSavedTests(EngineCase):
    """M8."""

    def test_with_nothing_saved_nothing_is_said(self):
        """Fails with the `_others` check taken out: an empty card would say every saved account is at its limit."""
        for profile_id in self.store.ids():
            self.store.delete(profile_id)
        self.look()
        self.assertIsNone(self.code.notice())
        self.assertEqual(self.scoped.counted, [])

    def test_with_only_the_account_in_use_saved_nothing_is_said(self):
        for profile_id in self.store.ids():
            self.store.delete(profile_id)
        self.store.save(ONE, "one@example.com", "plus")
        self.look()
        self.assertIsNone(self.code.notice())

    def test_with_others_saved_at_their_limit_it_still_says_so(self):
        from test_advanced_autoswitch_swap import usage
        self.fake.usages.update({"two@example.com": usage(99.0), "three@example.com": usage(99.0)})
        self.look()
        self.assertEqual(self.scoped.counted, ["all_exhausted"])
        self.assertIsNotNone(self.code.notice())


class SaidOnceTests(ControlCase):
    """M9."""

    def test_the_account_was_saved_is_said_once(self):
        """Fails with view's forgetting taken out: the line stayed until the bridge restarted."""
        self.on()
        started = []
        accounts.add(self.rt, start=started.append, run=lambda paths, store: "0123456789abcdef")
        started.pop()()
        view = lambda: accounts.view(self.rt, store=self.store, codex_home=self.codex, usage={})["add_state"]  # noqa: E731
        self.assertEqual(view(), accounts.ADDED)
        self.assertIsNone(view())
        accounts.add(self.rt, start=started.append, run=lambda paths, store: None)
        self.assertEqual(view(), accounts.WAITING, "a sign-in still waiting is said every time")
        started.pop()()
        self.assertEqual(view(), accounts.NOT_ADDED)
        self.assertIsNone(view())


class HeldDeleteTests(ControlCase):
    """M10."""

    def test_a_delete_held_by_a_switch_says_so(self):
        """Fails with the old word: a held Delete said a sign-in was waiting in the browser."""
        profile_id = self.store.save(TWO, "two@example.com", "plus")
        holding, release = threading.Event(), threading.Event()

        def hold():
            with self.store.locked():
                holding.set()
                release.wait(30)
        holder = threading.Thread(target=hold)
        holder.start()
        try:
            holding.wait(10)
            answer = accounts.delete(self.rt, {"id": profile_id}, store=self.store, codex_home=self.codex)
        finally:
            release.set()
            holder.join()
        self.assertEqual(answer["refusal"], Refusal.ACCOUNTS_HELD)
        self.assertIn(profile_id, self.store.ids())
        refusal = method("AccountsRefusal")
        self.assertRegex(refusal, r'if \(refusal == "accounts_held"\)\s*return Word\("page\.refused\.accounts_held"')


class SaveAsksFirstTests(unittest.TestCase):
    """M11."""

    def test_save_asks_once_before_it_saves(self):
        """Fails with the question taken out: Save kept a copy of the sign-in without a word."""
        save = method("SaveAccount")
        self.assertIn('if (!AskAdvanced(Word("page.confirm.accounts_save"', save)
        self.assertLess(save.index("AskAdvanced("), save.index('AdvancedCall("advanced-accounts-save"'))


if __name__ == "__main__":
    unittest.main()
