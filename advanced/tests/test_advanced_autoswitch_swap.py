"""account_auto_switch reads a saved account on a scratch home and switches the Codex app to it (v0.6.22, codex/swap.py).

The Codex app, its restart and every session are fakes; every home is a temporary folder and every sign-in file a
fixture of no one's. Who is signed in is decided by which fixture is in the folder's auth.json, as Codex would read it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch_profiles import Temp, opened, sealed  # noqa: E402
from codex_auto_resume_advanced import profiles  # noqa: E402
from codex_auto_resume_advanced.codex import authfile, restart as restarts, swap  # noqa: E402

NOW = 1_800_000_000


def fixture(name, n=1):
    return json.dumps({"fixture": name, "n": n}).encode("utf-8")


ONE, TWO, THREE = fixture("one"), fixture("two"), fixture("three")
WHO = {b"one": "one@example.com", b"two": "two@example.com", b"three": "three@example.com"}


def who(data):
    if data is None:
        return None
    name = json.loads(data.decode("utf-8"))["fixture"].encode("ascii")
    return WHO.get(name)


def usage(used=10.0, reached=False):
    bucket = {"primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": NOW + 3600},
              "secondary": {"usedPercent": min(used, 50.0), "windowDurationMins": 10080, "resetsAt": NOW + 86400}}
    if reached:
        bucket["rateLimitReachedType"] = "rate_limit_reached"
    return {"rateLimitsByLimitId": {"codex": bucket}}


class Fake:
    """Codex as these tests see it: an account/read that answers whoever's fixture is in the home, a usage read from
    `usages` by address, and the app - running or not - whose restart calls `between`."""

    def __init__(self, test, *, running=True, usages=None, signs_in=True, refresh=None):
        self.test, self.running, self.usages, self.signs_in, self.refresh = test, running, usages or {}, signs_in, refresh
        self.restarts = 0
        self.homes = []

    def session_for(self, home):
        @contextmanager
        def opened_session():
            self.homes.append(Path(home))

            class Session:
                def call(inner, method, params):
                    data = (Path(home) / "auth.json").read_bytes()
                    email = who(data)
                    if method == swap.ACCOUNT_READ:
                        return {"account": {"type": "chatgpt", "email": email, "planType": "plus"} if email else None}
                    if method == swap.USAGE_READ:
                        if self.refresh is not None:
                            (Path(home) / "auth.json").write_bytes(self.refresh)
                        return self.usages.get(email, usage())
                    raise AssertionError(method)
            yield Session()
        return opened_session()

    def restart(self, between):
        self.restarts += 1
        if not self.running:
            return restarts.NOT_RUNNING, None
        between()
        return restarts.RESTARTED, restarts.CLOSED

    def read_real(self):
        if not self.signs_in:
            return {"present": False, "plan_word": None, "email": None, "kind": None}
        email = who((self.test.codex / "auth.json").read_bytes())
        return {"present": True, "plan_word": "plus", "email": email, "kind": "chatgpt"}


class SwapCase(Temp):
    def setUp(self):
        super().setUp()
        # No real process is read: no other Codex engine runs here (the security review's finding 10 has its own tests).
        from unittest.mock import patch
        patcher = patch.object(swap, "_inventory", lambda: [])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = profiles.Profiles(self.home, seal=sealed, open_=opened, clock=lambda: NOW)
        (self.codex / "auth.json").write_bytes(ONE)

    def switch(self, fake, target):
        return swap.switch(None, self.store, self.codex, target, restart=fake.restart, read_real=fake.read_real, now=NOW)


class ReadProfileTests(SwapCase):
    def test_a_read_is_made_on_a_scratch_home_never_the_real_one(self):
        """Fails if the read used the real Codex home: MPROFILE's question is that nothing real changes."""
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self, usages={"two@example.com": usage(40.0)})
        found = swap.read_profile(None, self.store, two, session_for=fake.session_for, now=NOW)
        self.assertEqual((found["present"], found["own"], found["available"], found["most_used"]), (True, True, True, 40.0))
        self.assertTrue(swap.has_room(found))
        self.assertNotEqual(fake.homes[0].resolve(), self.codex.resolve())
        self.assertFalse(fake.homes[0].exists(), "the scratch home is removed")
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_a_copy_codex_refreshed_there_is_kept(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        refreshed = fixture("two", n=2)
        swap.read_profile(None, self.store, two, session_for=Fake(self, refresh=refreshed).session_for, now=NOW)
        self.assertEqual(self.store.get(two)["auth"], refreshed)

    def test_an_exhausted_account_has_no_room_and_is_marked_until_its_reset(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self, usages={"two@example.com": usage(100.0, reached=True)})
        found = swap.read_profile(None, self.store, two, session_for=fake.session_for, now=NOW)
        self.assertFalse(swap.has_room(found))
        self.assertEqual(self.store.get(two)["exhausted_until"], NOW + 3600)

    def test_a_copy_of_another_account_is_marked_and_never_used(self):
        two = self.store.save(THREE, "two@example.com", "plus")     # a copy that signs in as someone else
        found = swap.read_profile(None, self.store, two, session_for=Fake(self).session_for, now=NOW)
        self.assertIs(found["own"], False)
        self.assertFalse(swap.has_room(found))
        self.assertEqual(self.store.view()[0]["state"], profiles.NEEDS_SIGN_IN)

    def test_ninety_five_percent_is_not_room(self):
        self.assertFalse(swap.has_room({"present": True, "own": True, "available": True, "most_used": 95.0}))
        self.assertTrue(swap.has_room({"present": True, "own": True, "available": True, "most_used": 94.9}))


class SwitchTests(SwapCase):
    def test_a_switch_saves_the_account_in_use_back_and_puts_the_target_in(self):
        """Fails if the file in use were not saved back first: its rotated tokens would be lost."""
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self)
        self.assertEqual(self.switch(fake, two), swap.SWITCHED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)
        one = self.store.find("one@example.com")
        self.assertIsNotNone(one, "the account in use was saved before it was swapped out")
        self.assertEqual(self.store.get(one)["auth"], ONE)
        self.assertTrue(self.store.switched_to("two@example.com", after=NOW))
        self.assertIsNone(self.store.intent())

    def test_tokens_the_app_rotated_before_it_closed_are_the_ones_saved_back(self):
        """Fails with the save-back removed: the profile would keep the copy from before the app refreshed it."""
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(ONE, "one@example.com", "plus")
        rotated = fixture("one", n=7)
        fake = Fake(self)
        plain = fake.restart

        def restart(between):
            (self.codex / "auth.json").write_bytes(rotated)      # the app refreshed its tokens while it ran
            return plain(between)
        fake.restart = restart
        self.assertEqual(self.switch(fake, two), swap.SWITCHED)
        self.assertEqual(self.store.get(one)["auth"], rotated)

    def test_codex_closed_is_swapped_with_no_restart(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self, running=False)
        self.assertEqual(self.switch(fake, two), swap.SWITCHED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)

    def test_not_the_target_after_the_restart_puts_the_previous_file_back_once(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self)
        fake.read_real = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com", "kind": "chatgpt"}
        self.assertEqual(self.switch(fake, two), swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(fake.restarts, 2, "one switch and one put-back, never a loop")
        self.assertEqual(self.store.get(two)["failed_at"], NOW)

    def test_a_keyring_store_is_never_switched(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        (self.codex / "config.toml").write_text('cli_auth_credentials_store = "keyring"\n', encoding="utf-8")
        fake = Fake(self)
        self.assertEqual(self.switch(fake, two), swap.NOT_USABLE)
        self.assertEqual(fake.restarts, 0)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_an_app_that_would_not_close_keeps_its_file(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self)
        fake.restart = lambda between: (restarts.NOT_ENDED, None)
        self.assertEqual(self.switch(fake, two), swap.NOT_CLOSED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_a_crash_left_intent_is_settled_once(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(ONE, "one@example.com", "plus")
        self.store.begin(one, two)
        authfile.replace(self.codex, TWO)
        fake = Fake(self)
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=fake.read_real), swap.SWITCHED)
        self.assertIsNone(self.store.intent())
        self.assertIsNone(swap.recover(None, self.store, self.codex, read_real=fake.read_real))


if __name__ == "__main__":
    unittest.main()
