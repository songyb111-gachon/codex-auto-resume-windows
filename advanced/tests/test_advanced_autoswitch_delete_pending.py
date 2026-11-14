"""v0.6.23 second round R2: Delete all while a put-back waits never deletes the only copy of the previous sign-in.

Since A-R5 the previous sign-in a failed switch is to put back lives in the switch's intent itself. Delete all removed the
intent, and with it that copy: Codex stayed on the copy that did not sign in, and the stop statement's "a switch that
did not finish is still undone" no longer held. Now Delete all first finishes the put-back where Codex does not run, and
where it runs it deletes nothing and is refused as a switch holding the saved accounts is (ACCOUNTS_HELD).

Every home is a temporary folder and every sign-in file a fixture of no one's; the app, its restart and every read are
fakes (test_advanced_autoswitch_swap.SwapCase).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch_swap import NOW, ONE, THREE, TWO, Fake, SwapCase  # noqa: E402
from codex_auto_resume_advanced import profiles  # noqa: E402
from codex_auto_resume_advanced.codex import authfile, restart as restarts, swap  # noqa: E402
from codex_auto_resume_advanced.control import autoswitch as card  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, Refusal  # noqa: E402

SIGNED_OUT = {"present": False, "plan_word": None, "email": None, "kind": None}


class APutBackWaits(SwapCase):
    """The report's repro: the target not signed in, the put-back's restart held because someone was at the PC."""

    def setUp(self):
        super().setUp()
        self.two = self.store.save(TWO, "two@example.com", "plus")
        fake, made = Fake(self), {"restart": 0, "read": 0}

        def restart(between):
            made["restart"] += 1
            if made["restart"] == 1:
                between()
                return restarts.RESTARTED, restarts.CLOSED
            return None                                     # the put-back's restart: someone uses the PC now

        def read_real():
            made["read"] += 1
            return fake.read_real() if made["read"] == 1 else SIGNED_OUT
        self.assertEqual(swap.switch(None, self.store, self.codex, self.two, restart=restart, read_real=read_real,
                                     now=NOW), swap.NOT_PUT_BACK)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO, "the copy that did not sign in is in place")
        self.running = True
        patcher = patch.object(swap, "_app_running", lambda: self.running)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(authfile, "_PRIVATE", lambda directory: True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = SimpleNamespace(paths=SimpleNamespace(home=self.home),
                                       states=lambda fresh=False: {card.CAPABILITY: ArmingState.ARMED},
                                       registry={card.CAPABILITY: object()},
                                       state=SimpleNamespace(stamped=lambda *_a: None))

    def delete_all(self):
        return card.delete(self.runtime, {"all": True}, store=self.store, codex_home=self.codex)

    def test_with_codex_running_nothing_is_deleted_and_it_is_refused(self):
        """Fails with the old Delete all: removed 2, intent None, and recover then left TWO in place for good."""
        self.assertEqual(self.delete_all()["refusal"], Refusal.ACCOUNTS_HELD)
        self.assertEqual(len(self.store.ids()), 2, "nothing deleted")
        self.assertEqual(swap._previous(self.store, self.store.intent()), ONE, "the previous sign-in is still kept")
        # The watcher's next look, Codex closed by then, puts it back as promised.
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=lambda: SIGNED_OUT,
                                      restart=lambda between: (restarts.NOT_RUNNING, None)), swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_with_codex_closed_the_put_back_is_finished_first(self):
        """Fails with the old Delete all: the accounts went and TWO, which did not sign in, stayed in Codex's place."""
        self.running = False
        found = self.delete_all()
        self.assertEqual((found["done"], found["deleted"]), (True, 2))
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE, "the account signed in before is back")
        self.assertIsNone(self.store.intent())
        self.assertEqual(self.store.ids(), [])

    def test_the_store_itself_refuses_so_no_other_caller_can_miss_it(self):
        with self.assertRaises(profiles.Locked):
            self.store.delete_all(self.codex)
        self.assertEqual(len(self.store.ids()), 2)

    def test_a_file_no_longer_the_switchs_copy_stops_nothing(self):
        """A guard: a person signed in to another account since - nothing of the switch is left in place to undo."""
        (self.codex / "auth.json").write_bytes(THREE)
        self.assertEqual(self.delete_all()["deleted"], 2)
        self.assertEqual((self.codex / "auth.json").read_bytes(), THREE)


class NoPutBackWaits(SwapCase):
    def test_delete_all_is_as_before(self):
        """A guard, not a proof: it passes with the fix reverted."""
        self.store.save(TWO, "two@example.com", "plus")
        self.assertEqual(self.store.delete_all(self.codex), 1)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)


if __name__ == "__main__":
    unittest.main()
