"""v0.6.23 second round R1: an account read that gives no answer right after the swap is not "the target is not signed in".

codex/account.read never raises: a read that broke - a timeout while the Codex app starts, a codex.exe that cannot be
spawned, a broken session - answers {present: None}. The switch took that as "not the target": it set a good saved
account aside (needs a new sign-in) and undid the switch with a second restart; a crash-left switch was undone the same
way. Now only a definite answer - signed out, or another account - sets the account aside and undoes the switch; no
answer is read again, and still unknown it is UNVERIFIED, the intent kept for the next look.

Every home is a temporary folder and every sign-in file a fixture of no one's; the app, its restart and every read are
fakes (test_advanced_autoswitch_swap.SwapCase).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch_swap import NOW, ONE, TWO, Fake, SwapCase  # noqa: E402
from codex_auto_resume_advanced import profiles  # noqa: E402
from codex_auto_resume_advanced.codex import swap  # noqa: E402
from codex_auto_resume_advanced.codex.account import parse  # noqa: E402

UNKNOWN = parse(None)
SIGNED_OUT = {"present": False, "plan_word": None, "email": None, "kind": None}


class Reads:
    """account/read on the real home: the first read (before the swap) as Codex answers, the later ones from `after` -
    UNKNOWN, SIGNED_OUT or None for Codex's own answer - in turn, the last one repeated."""

    def __init__(self, fake, *after):
        self.fake, self.after, self.count = fake, list(after), 0

    def __call__(self):
        self.count += 1
        if self.count == 1 or not self.after:
            return self.fake.read_real()
        found = self.after[min(self.count - 2, len(self.after) - 1)]
        return self.fake.read_real() if found is None else found


class AReadThatAnswersNothing(SwapCase):
    def setUp(self):
        super().setUp()
        self.two = self.store.save(TWO, "two@example.com", "plus")
        self.fake = Fake(self)

    def switch_with(self, reads):
        return swap.switch(None, self.store, self.codex, self.two, restart=self.fake.restart, read_real=reads, now=NOW)

    def test_it_sets_no_account_aside_and_undoes_nothing(self):
        """Fails with the old rule: not_signed_in | needs_sign_in | restarts 2 | ONE in place (the report's repro)."""
        reads = Reads(self.fake, UNKNOWN)
        self.assertEqual(self.switch_with(reads), swap.UNVERIFIED)
        self.assertEqual(self.store.state(self.store.get(self.two), NOW), profiles.READY)
        self.assertEqual(self.fake.restarts, 1, "no second restart")
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO, "the target's copy stays in")
        self.assertEqual(reads.count, 1 + swap.AFTER_TRIES, "read again before it counts as unknown")
        intent = self.store.intent()
        self.assertEqual(intent["step"], swap.VERIFY)
        self.assertEqual((intent["to"], intent["to_email"]), (self.two, "two@example.com"))
        self.assertEqual(swap._previous(self.store, intent), ONE, "the previous sign-in is kept with the intent")

    def test_a_read_again_that_answers_finishes_the_switch(self):
        reads = Reads(self.fake, UNKNOWN, None)
        self.assertEqual(self.switch_with(reads), swap.SWITCHED)
        self.assertIsNone(self.store.intent())
        self.assertIsNotNone(self.store.last_switch_at())

    def test_a_definite_signed_out_still_undoes_the_switch(self):
        """A guard, not a proof: it passes with the fix reverted."""
        self.assertEqual(self.switch_with(Reads(self.fake, SIGNED_OUT)), swap.NOT_SIGNED_IN)
        self.assertEqual(self.store.state(self.store.get(self.two), NOW), profiles.NEEDS_SIGN_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_the_next_look_settles_it_on_a_definite_answer(self):
        self.switch_with(Reads(self.fake, UNKNOWN))
        unknown = lambda: UNKNOWN  # noqa: E731
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=unknown, restart=self.fake.restart),
                         swap.UNVERIFIED)
        self.assertEqual(self.store.intent()["step"], swap.VERIFY, "kept for the look after")
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=self.fake.read_real,
                                      restart=self.fake.restart), swap.SWITCHED)
        self.assertIsNone(self.store.intent())
        self.assertEqual(self.store.state(self.store.get(self.two), NOW), profiles.READY)

    def test_a_later_definite_no_sets_it_aside_and_puts_the_previous_back(self):
        self.switch_with(Reads(self.fake, UNKNOWN))
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=lambda: SIGNED_OUT,
                                      restart=self.fake.restart), swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(self.store.state(self.store.get(self.two), NOW), profiles.NEEDS_SIGN_IN)
        self.assertIsNone(self.store.intent())


class ASwitchACrashLeft(SwapCase):
    """_recover had the same rule: an unknown read undid a switch a crash left, even one that had succeeded."""

    def test_an_unknown_read_leaves_it_for_the_next_look(self):
        """Fails with the old rule: the previous copy went back over a switch that may have worked."""
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(ONE, "one@example.com", "plus")
        self.store.begin(one, two)                          # the crash came after the swap, before the read
        (self.codex / "auth.json").write_bytes(TWO)
        found = swap.recover(None, self.store, self.codex, read_real=lambda: UNKNOWN, restart=Fake(self).restart)
        self.assertEqual(found, swap.UNVERIFIED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)
        self.assertIsNotNone(self.store.intent())
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=Fake(self).read_real,
                                      restart=Fake(self).restart), swap.SWITCHED)

    def test_a_damaged_intent_is_still_cleared(self):
        """A guard: an intent that cannot be read is no switch to wait on."""
        self.store.begin("a" * 16, "b" * 16)
        (self.store.directory / profiles.INTENT).write_bytes(b"not sealed")
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=lambda: UNKNOWN), swap.LEFT)
        self.assertIsNone(self.store.intent())


class TheJournalKnowsTheWord(unittest.TestCase):
    def test_unverified_is_one_of_the_capabilitys_codes(self):
        from codex_auto_resume_advanced.registry import ACCOUNT_AUTO_SWITCH
        self.assertIn(swap.UNVERIFIED, ACCOUNT_AUTO_SWITCH.codes)
        self.assertIn(swap.UNVERIFIED, swap.OUTCOMES)


if __name__ == "__main__":
    unittest.main()
