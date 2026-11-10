"""The saved-accounts card's usage meters (account_auto_switch, v0.6.22 final): each saved account's last usage reading,
kept from the switch's own look and from Read usage; Read usage itself (one account at a time, in the background, at
most once every ten minutes, never a switch, never a send, a broken read keeping the last reading); the next candidate
as the switch's own rule picks it; the profile file an earlier build still reads; and the bridge's command and fields.

Every home is a temporary folder, every sign-in file a fixture of no one's, and Codex, its app and the clock are fakes:
nothing real is read, closed, started or switched.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch import EngineCase  # noqa: E402
from test_advanced_autoswitch_control import ControlCase  # noqa: E402
from test_advanced_autoswitch_profiles import Temp, opened, sealed  # noqa: E402
from test_advanced_autoswitch_swap import NOW, ONE, THREE, TWO, Fake, SwapCase, usage  # noqa: E402
from codex_auto_resume_advanced import profiles, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import account, swap  # noqa: E402
from codex_auto_resume_advanced.control import autoswitch as accounts  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand, Refusal  # noqa: E402

BETA2 = Path(__file__).resolve().parent / "data" / "profiles_v0622_beta2.py.txt"


def rows(store):
    return {row["id"]: row for row in store.view()}


class KeptFromTheLookTests(EngineCase):
    def test_the_switch_s_own_look_keeps_each_reading(self):
        """Fails with _note_read's `usage` taken out: the meters would show only what Read usage read."""
        self.assertEqual(self.code.choose(self.store, NOW), self.two)
        shown = rows(self.store)
        self.assertEqual(shown[self.two]["usage"]["five_hour"], {"used": 30.0, "resets_at": NOW + 3600})
        self.assertEqual(shown[self.two]["usage"]["weekly"], {"used": 30.0, "resets_at": NOW + 86400})
        self.assertEqual(shown[self.three]["usage"]["five_hour"]["used"], 60.0)
        self.assertEqual(shown[self.three]["usage"]["weekly"]["used"], 50.0)
        self.assertEqual(shown[self.three]["usage"]["read_at"], NOW)
        self.assertFalse(shown[self.three]["unread"])

    def test_the_account_signed_in_is_marked_in_use_and_never_read_on_a_scratch_home(self):
        """Fails with choose's `seen` taken out: the card could not tell which saved account is in use."""
        one = self.store.save(ONE, "one@example.com", "plus")
        self.code.choose(self.store, NOW)
        self.assertEqual(rows(self.store)[one]["seen_at"], NOW)
        self.assertIsNone(rows(self.store)[one]["usage"], "the account in use is never read on a scratch home")

    def test_the_switch_s_own_reads_hold_the_saved_accounts(self):
        """Fails with read_profile's lock taken out: the watcher's look could read an account Read usage reads."""
        held = []
        inner = self.fake.session_for

        def session_for(home):
            probe = threading.Thread(target=lambda: held.append(ReadNowCase.try_lock(self.store)))
            probe.start()
            probe.join()
            return inner(home)
        self.code._session_for = session_for
        self.code.choose(self.store, NOW)
        self.assertEqual(held, [True, True])

    def test_a_read_that_broke_keeps_the_last_reading_and_says_so(self):
        """Fails with the broken read's `unread_at` taken out: the card would show an old reading as if it were fresh."""
        self.code.choose(self.store, NOW)

        def broken(home):
            raise OSError("Codex did not answer")
        swap.read_profile(None, self.store, self.three, session_for=broken, now=NOW + 60)
        shown = rows(self.store)[self.three]
        self.assertTrue(shown["unread"])
        self.assertEqual((shown["usage"]["read_at"], shown["usage"]["five_hour"]["used"]), (NOW, 60.0))
        swap.read_profile(None, self.store, self.three, session_for=self.fake.session_for, now=NOW + 120)
        self.assertFalse(rows(self.store)[self.three]["unread"], "a good read clears it")


class CandidateTests(EngineCase):
    def meters(self, usage_reading=None):
        return accounts.meters(None, self.store, {}, NOW, usage=usage_reading or {})

    def test_the_next_candidate_is_the_one_choose_picks(self):
        """Fails if the card ranked by anything but engine/autoswitch.best: ties go to the least recently used."""
        self.fake.usages["three@example.com"] = usage(30.0)
        self.store.update(self.two, used_at=NOW - 10)
        self.store.update(self.three, used_at=NOW - 100)
        picked = self.code.choose(self.store, NOW)
        self.assertEqual(picked, self.three)
        shown = self.meters()
        self.assertEqual((shown["candidate_id"], shown["candidate"], shown["candidate_state"]),
                         (self.three, account.mask("three@example.com"), "found"))
        self.store.update(self.three, used_at=NOW)
        self.assertEqual(self.code.choose(self.store, NOW), self.two)
        self.assertEqual(self.meters()["candidate_id"], self.two)

    def test_none_has_room(self):
        self.fake.usages.update({"two@example.com": usage(96.0), "three@example.com": usage(99.0)})
        self.assertIsNone(self.code.choose(self.store, NOW))
        shown = self.meters()
        self.assertEqual((shown["candidate"], shown["candidate_state"]), (None, "none_has_room"))

    def test_no_reading_no_candidate_line(self):
        shown = self.meters()
        self.assertEqual((shown["candidate"], shown["candidate_state"], shown["read_at"]), (None, None, None))
        for row in shown["profiles"]:
            self.assertEqual((row["five_hour"], row["weekly"], row["read_at"]), (None, None, None))

    def test_the_account_in_use_takes_the_watcher_s_own_reading(self):
        """Fails if the row in use showed a read of its own, or none: its meters are the watcher's last reading."""
        one = self.store.save(ONE, "one@example.com", "plus")
        self.code.choose(self.store, NOW)
        watcher = {"read_at": NOW - 30, "windows": [
            {"bucket": "codex", "window": "primary", "used_percent": 92.0, "window_minutes": 300, "reset_at": NOW + 4200},
            {"bucket": "codex", "window": "secondary", "used_percent": 48.0, "window_minutes": 10080,
             "reset_at": NOW + 3 * 86400}]}
        shown = {row["id"]: row for row in self.meters(watcher)["profiles"]}
        self.assertTrue(shown[one]["in_use"])
        self.assertEqual(shown[one]["five_hour"], {"used": 92.0, "resets_at": NOW + 4200})
        self.assertEqual(shown[one]["weekly"], {"used": 48.0, "resets_at": NOW + 3 * 86400})
        self.assertEqual(shown[one]["read_at"], NOW - 30)
        self.assertEqual([row["id"] for row in shown.values() if row["in_use"]], [one])
        self.assertEqual(self.meters(watcher)["read_at"], NOW, "the line's time is the saved accounts' reading")


class ReadNowCase(SwapCase):
    def setUp(self):
        super().setUp()
        self.one = self.store.save(ONE, "one@example.com", "plus")
        self.two = self.store.save(TWO, "two@example.com", "plus")
        self.three = self.store.save(THREE, "three@example.com", "plus")
        self.fake = Fake(self, usages={"two@example.com": usage(30.0), "three@example.com": usage(60.0)})
        self.read, self.methods, self.broken = [], [], set()
        self.home_key = self.home
        accounts._READING[self.home_key] = {"state": accounts.READING, "done": 0, "of": None, "failed": []}
        self.addCleanup(accounts._READING.pop, self.home_key, None)

    def run_one(self, paths, store, profile_id, now=None):
        """swap.read_profile with the fake session - recording each read, and whether the saved accounts were held."""
        held = []
        probe = threading.Thread(target=lambda: held.append(self.try_lock(store)))
        probe.start()
        probe.join()
        self.read.append((profile_id, held[0]))
        if profile_id in self.broken:
            def broken(home):
                raise OSError("Codex did not answer")
            return swap.read_profile(paths, store, profile_id, session_for=broken, now=now)

        def recorded(home):
            session = self.fake.session_for(home)

            class Recorder:
                def __enter__(inner):
                    real = session.__enter__()

                    class Call:
                        def call(_self, method, params):
                            self.methods.append(method)
                            return real.call(method, params)
                    return Call()

                def __exit__(inner, *exc):
                    return session.__exit__(*exc)
            return Recorder()
        return swap.read_profile(paths, store, profile_id, session_for=recorded, now=now)

    @staticmethod
    def try_lock(store):
        try:
            with store.locked(0):
                return False
        except profiles.Locked:
            return True

    def read_all(self, **kwargs):
        kwargs.setdefault("read_real", self.fake.read_real)
        return accounts.read_all(None, self.store, self.home_key, run=self.run_one, clock=lambda: NOW, **kwargs)


class ReadNowTests(ReadNowCase):
    def test_one_account_at_a_time_never_the_one_in_use(self):
        """Fails if a read ran outside the saved accounts' lock (beside the watcher's own look) or read the account in
        use on a scratch home."""
        self.assertEqual(self.read_all(), accounts.READ)
        self.assertEqual(sorted(profile_id for profile_id, _held in self.read), sorted([self.two, self.three]))
        self.assertTrue(all(held for _id, held in self.read), "each read holds the saved accounts")
        self.assertEqual((accounts._READING[self.home_key]["done"], accounts._READING[self.home_key]["of"]), (2, 2))
        self.assertEqual(rows(self.store)[self.one]["seen_at"], NOW)

    def test_it_never_switches_and_never_sends(self):
        """Fails if Read usage asked Codex anything but who is signed in and the usage, or touched the sign-in in use."""
        self.read_all()
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertIsNone(self.store.intent())
        self.assertIsNone(self.store.last_switch_at())
        self.assertEqual(self.fake.restarts, 0)
        self.assertEqual(set(self.methods), {swap.ACCOUNT_READ, swap.USAGE_READ})
        self.assertNotIn(self.codex.resolve(), [home.resolve() for home in self.fake.homes])

    def test_a_read_that_broke_keeps_the_last_reading(self):
        self.read_all()
        first = rows(self.store)[self.three]["usage"]
        self.broken = {self.three}
        accounts._READING[self.home_key] = {"state": accounts.READING, "done": 0, "of": None, "failed": []}
        self.assertEqual(self.read_all(), accounts.READ)
        self.assertEqual(accounts._READING[self.home_key]["failed"], [self.three])
        shown = accounts.meters(None, self.store, accounts._READING[self.home_key], NOW, usage={})
        three = [row for row in shown["profiles"] if row["id"] == self.three][0]
        self.assertTrue(three["unread"])
        self.assertEqual((three["five_hour"], three["read_at"]), (first["five_hour"], first["read_at"]))

    def test_a_switch_that_began_stops_it(self):
        """Fails without the check under the lock: a switch between two reads could make a later one the account in
        use, and a scratch read of it would rotate the running app's tokens."""
        def run(paths, store, profile_id, now=None):
            self.read.append(profile_id)
            store.mark_switched("two@example.com")
            return {"present": True}
        self.assertEqual(accounts.read_all(None, self.store, self.home_key, run=run, read_real=self.fake.read_real,
                                           clock=lambda: NOW + 1), accounts.HELD)
        self.assertEqual(len(self.read), 1)

    def test_who_is_signed_in_unknown_reads_nothing(self):
        self.fake.signs_in = False
        self.assertEqual(self.read_all(), accounts.UNKNOWN)
        self.assertEqual(self.read, [])


class ReadNowBridgeTests(ControlCase):
    def setUp(self):
        super().setUp()
        self.started = []
        self.addCleanup(accounts._READING.pop, Path(self.rt.paths.home), None)

    def read(self, now):
        return accounts.read(self.rt, store=self.store, start=self.started.append, now=now)

    def finish(self):
        job = self.started.pop()
        from unittest.mock import patch
        with patch.object(accounts, "read_all", lambda *args, **kwargs: accounts.READ):
            job()

    def test_off_it_is_refused(self):
        self.assertEqual(self.read(NOW)["refusal"], Refusal.NOT_ON)
        self.assertEqual(surfaces.bridge(self.rt, "advanced-accounts-read", {})["refusal"], Refusal.NOT_ON)

    def test_at_most_once_every_ten_minutes_and_in_the_background(self):
        """Fails with READ_EVERY's check taken out: every click would read every saved account again."""
        self.on()
        answer = self.read(NOW)
        self.assertEqual((answer["started"], answer["read_state"], answer["read_next_at"]),
                         (True, accounts.READING, NOW + accounts.READ_EVERY))
        self.assertEqual(len(self.started), 1, "the reads run on a thread of their own, not in the request")
        self.assertEqual(self.read(NOW + 1)["started"], False, "one at a time: a second waits for the first")
        self.finish()
        early = self.read(NOW + accounts.READ_EVERY - 1)
        self.assertEqual((early["started"], early["read_next_at"]), (False, NOW + accounts.READ_EVERY))
        self.assertEqual(self.started, [])
        self.assertEqual(accounts.view(self.rt, store=self.store, codex_home=self.codex, usage={},
                                       now=NOW + 60)["read_next_at"], NOW + accounts.READ_EVERY)
        self.assertTrue(self.read(NOW + accounts.READ_EVERY)["started"])

    def test_the_bridge_answers_it_with_no_arguments(self):
        self.assertIn(BridgeCommand.ADVANCED_ACCOUNTS_READ, surfaces.ARGUMENTS)
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_ACCOUNTS_READ], frozenset())
        self.assertNotIn(BridgeCommand.ADVANCED_ACCOUNTS_READ, surfaces.UNANSWERED)
        self.assertEqual(surfaces.bridge(self.rt, "advanced-accounts-read", {"all": True})["refusal"],
                         Refusal.INVALID_REQUEST)
        self.on()
        from unittest.mock import patch
        with patch.object(accounts, "read_all", lambda *args, **kwargs: accounts.READ):
            answer = surfaces.bridge(self.rt, "advanced-accounts-read", {})
            self.assertTrue(answer["done"], answer)
            deadline = time.monotonic() + 10
            while accounts._READING[Path(self.rt.paths.home)]["state"] == accounts.READING:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)

    def test_the_card_s_answer_carries_the_meters(self):
        """The fields the window reads (advanced/gui/AdvancedAccounts.cs), and never an address."""
        self.on()
        self.store.save(TWO, "two@example.com", "plus")
        shown = accounts.view(self.rt, store=self.store, codex_home=self.codex, usage={}, now=NOW)
        for key in ("candidate", "candidate_id", "candidate_state", "read_at", "read_state", "read_done", "read_of", "read_next_at"):
            self.assertIn(key, shown)
        self.assertEqual(set(shown["profiles"][0]), {"id", "mask", "plan", "state", "in_use", "five_hour", "weekly",
                                                     "read_at", "unread"})
        self.assertNotIn("two@example.com", repr(shown))


class StoreTests(Temp):
    def store(self, module=profiles):
        return module.Profiles(self.home, seal=sealed, open_=opened, clock=lambda: NOW)

    def test_a_reading_is_numbers_only_and_anything_else_is_none(self):
        good = {"read_at": NOW, "available": True, "most_used": 40.0, "five_hour": {"used": 40.0, "resets_at": NOW},
                "weekly": {"used": 10, "resets_at": None}}
        self.assertEqual(profiles.reading(good), good)
        self.assertIsNone(profiles.reading({"read_at": "yesterday"}))
        self.assertIsNone(profiles.reading(None))
        odd = profiles.reading(dict(good, five_hour={"used": "full"}, weekly={"used": -1}, email="x@example.com"))
        self.assertEqual((odd["five_hour"], odd["weekly"]), (None, None))
        self.assertNotIn("email", odd)

    def test_a_file_an_earlier_build_wrote_reads_as_no_reading(self):
        beta2 = self.load_beta2()
        profile_id = self.store(beta2).save(TWO, "two@example.com", "plus")
        shown = rows(self.store())[profile_id]
        self.assertEqual((shown["usage"], shown["unread"], shown["seen_at"], shown["state"]),
                         (None, False, None, profiles.READY))

    def test_an_earlier_build_reads_the_file_and_keeps_the_reading_through_its_updates(self):
        """Fails if the reading moved into a field the beta.2 build refuses, or out of the profile's own file."""
        store = self.store()
        profile_id = store.save(TWO, "two@example.com", "plus")
        store.update(profile_id, usage={"read_at": NOW, "available": True, "most_used": 40.0,
                                        "five_hour": {"used": 40.0, "resets_at": NOW + 60}, "weekly": None},
                     seen_at=NOW)
        store.note_read_now(NOW)
        old = self.store(self.load_beta2())
        self.assertEqual(old.ids(), [profile_id], "usage.read is not a profile to it")
        self.assertEqual(old.view(), [{"id": profile_id, "mask": account.mask("two@example.com"), "plan": "plus",
                                       "state": profiles.READY}])
        self.assertEqual(old.get(profile_id)["auth"], TWO)
        old.update(profile_id, used_at=NOW + 5)
        shown = rows(store)[profile_id]
        self.assertEqual((shown["usage"]["five_hour"]["used"], shown["seen_at"], shown["used_at"]), (40.0, NOW, NOW + 5))
        self.assertEqual(store.read_now_at(), NOW)

    def load_beta2(self):
        name = "codex_auto_resume_advanced._profiles_beta2"
        loader = importlib.machinery.SourceFileLoader(name, str(BETA2))
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
