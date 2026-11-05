"""account_auto_switch after its security review (v0.6.22, plans/v0622-autoswitch-security-review.md): each finding's
reproduction, as a test that fails with its fix taken away.

The rule behind most of them: nothing writes Codex's sign-in file unless it knows what is there now; where it does not
know, it leaves the file, keeps what it can and says so once; a person's own sign-in is never overwritten. The Codex app,
its restart and every session are fakes; every home is a temporary folder and every sign-in file a fixture of no one's.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch_swap import NOW, ONE, THREE, TWO, Fake, SwapCase, fixture  # noqa: E402
from codex_auto_resume_advanced.codex import authfile, swap  # noqa: E402


class RecoverKnowsWhatIsThere(SwapCase):
    """Finding 1 (R6): recover wrote the from-copy over auth.json without looking at what was there."""

    def setUp(self):
        super().setUp()
        self.two = self.store.save(TWO, "two@example.com", "plus")
        self.one = self.store.save(ONE, "one@example.com", "plus")
        patcher = patch.object(swap, "_app_running", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def recover(self, fake):
        return swap.recover(None, self.store, self.codex, read_real=fake.read_real)

    def test_a_crash_before_the_swap_leaves_the_newest_tokens_in_place(self):
        """Fails with the check removed: the profile's older copy went over the tokens Codex refreshed since."""
        newest = fixture("one", n=9)
        (self.codex / "auth.json").write_bytes(newest)
        self.store.begin(self.one, self.two)                    # killed while the app was closing
        self.assertEqual(self.recover(Fake(self)), swap.LEFT)
        self.assertEqual((self.codex / "auth.json").read_bytes(), newest)
        self.assertIsNone(self.store.intent())

    def test_a_person_signed_in_since_is_never_overwritten(self):
        """Fails with the check removed: a third account a person signed in to went, unsaved, under the from-copy."""
        self.store.begin(self.one, self.two)
        (self.codex / "auth.json").write_bytes(THREE)            # the capability off meanwhile; a person signed in
        self.assertEqual(self.recover(Fake(self)), swap.LEFT)
        self.assertEqual((self.codex / "auth.json").read_bytes(), THREE)

    def test_the_target_put_in_and_not_signed_in_is_put_back(self):
        self.store.begin(self.one, self.two)
        authfile.replace(self.codex, TWO)
        self.assertEqual(self.recover(Fake(self, signs_in=False)), swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_nothing_is_written_under_a_running_app(self):
        self.store.begin(self.one, self.two)
        authfile.replace(self.codex, TWO)
        with patch.object(swap, "_app_running", lambda: True):
            self.assertEqual(self.recover(Fake(self, signs_in=False)), swap.LEFT)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)


if __name__ == "__main__":
    unittest.main()
