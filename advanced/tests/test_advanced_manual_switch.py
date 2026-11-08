"""Switch to this account (v0.6.22 final, the owner's 2026-11-08): a person's own switch to one saved account, from the
saved accounts under either account capability's card (control/autoswitch.switch) - the automatic switch's own switch
(engine/autoswitch.AutoSwitch.put_in) given the account the person picked - and the one store both cards share.

Every home is a temporary folder, every sign-in file a fixture of no one's, and Codex, its app, the restart and the clock
are fakes: nothing real is read, closed, started or switched.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch import EngineCase, View, waiting  # noqa: E402
from test_advanced_autoswitch_control import ControlCase  # noqa: E402
from test_advanced_autoswitch_swap import NOW, ONE, TWO, THREE, Fake, usage  # noqa: E402
from codex_auto_resume_advanced import profiles, registry, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import swap  # noqa: E402
from codex_auto_resume_advanced.control import autoswitch as accounts  # noqa: E402
from codex_auto_resume_advanced.engine import autoswitch  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand, OptionKey, Refusal  # noqa: E402


class SharedPathTests(EngineCase):
    """The engine's side: one switch, given the account the look chose or the one a person picked."""

    def test_the_look_switches_through_put_in(self):
        """Fails if the look switched by a path of its own: the manual switch would then not be the same switch."""
        calls = []
        real = autoswitch.AutoSwitch.put_in

        def recorded(code, target, now, *, manual=False):
            calls.append((target, manual))
            return real(code, target, now, manual=manual)
        with patch.object(autoswitch.AutoSwitch, "put_in", recorded):
            self.look()
        self.assertEqual(calls, [(self.two, False)])
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)

    def test_a_person_s_switch_needs_nobody_away_but_still_waits_for_a_busy_codex(self):
        """Fails if a manual switch asked the PC to be idle (the person who clicked is at it) - or if it went on while a
        turn runs, something is queued or a recovery is being sent (codex/restart.busy)."""
        self.idle = 0
        self.busy = ("turn_running",)
        self.assertEqual(self.code.put_in(self.three, NOW, manual=True)[0], swap.HELD)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE, "nothing changed while busy")
        self.busy = ()
        self.assertEqual(self.code.put_in(self.three, NOW, manual=True)[0], swap.SWITCHED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), THREE)
        self.assertEqual(self.code.put_in(self.two, NOW)[0], swap.HELD, "the look's own switch still waits for idle")

    def test_a_person_s_switch_is_not_counted_toward_the_ceiling(self):
        """Fails if the manual switch counted toward PER_DAY, or were refused by it."""
        self.code._keep([NOW] * autoswitch.PER_DAY)
        self.assertEqual(self.code.put_in(self.three, NOW, manual=True)[0], swap.SWITCHED)
        self.assertEqual(self.store.attempts(), [NOW] * autoswitch.PER_DAY)
        self.assertEqual(self.scoped.counted, [])

    def test_a_switch_that_did_not_finish_is_undone(self):
        """The target not signed in after the restart: the previous file goes back, as the look's switch does."""
        self.code._read_real = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com"}
        self.assertEqual(self.code.put_in(self.three, NOW, manual=True)[0], swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertIsNone(self.store.intent())

    def test_a_person_s_switch_releases_the_waiting_recoveries_early(self):
        """The stamp a manual switch leaves (where the automatic switch is on) is read by its P7 answer."""
        self.scoped.stamps[str(OptionKey.AUTO_SWITCHED_AT)] = NOW
        record = dict(waiting(), state="waiting_reset")
        from codex_auto_resume.domain.plug import Alternative
        self.assertEqual(self.code.schedule(record, NOW + 600), Alternative.EARLY)


class Stand:
    """The automatic switch's code as the bridge's switch sees it: whether Codex is busy, and the switch itself."""

    def __init__(self, outcome=swap.SWITCHED, busy=()):
        self.outcome, self._busy, self.calls = outcome, busy, []

    def busy(self):
        return self._busy

    def put_in(self, target, now, *, manual=False):
        self.calls.append((target, manual))
        return self.outcome, []


class ManualCase(ControlCase):
    def setUp(self):
        super().setUp()
        (self.codex / "auth.json").write_bytes(ONE)          # the swap tests' fixture: their Codex stand-in reads it
        self.two = self.store.save(TWO, "two@example.com", "plus")
        self.one = self.store.save(ONE, "one@example.com", "plus")
        self.store.update(self.one, seen_at=NOW)            # the card's "in use"

    def ask(self, profile_id, code=None, engines=lambda: False, jobs=None):
        return accounts.switch(self.rt, {"id": profile_id}, store=self.store, codex_home=self.codex,
                               start=(jobs.append if jobs is not None else lambda job: job()), code=code,
                               engines=engines, now=NOW)

    def journalled(self):
        return [line["code"] for line in self.rt.state.journal(capability="account_auto_switch")
                if line["code"].startswith("autoswch.manual")]


class ManualSwitchTests(ManualCase):
    def test_it_calls_the_shared_switch_with_the_account_picked(self):
        """Fails if the bridge switched by a path of its own, or to another account than the row asked for."""
        self.on()
        code, jobs = Stand(), []
        answer = self.ask(self.two, code, jobs=jobs)
        self.assertEqual((answer["done"], answer["switch_state"]), (True, accounts.SWITCHING))
        self.assertEqual(self.ask(self.two, Stand())["refusal"], Refusal.ACCOUNTS_HELD, "one at a time")
        jobs[0]()
        self.assertEqual(code.calls, [(self.two, True)])
        shown = accounts.view(self.rt, store=self.store, codex_home=self.codex)
        self.assertEqual(shown["switch_state"], swap.SWITCHED)
        self.assertTrue(shown["switch_mask"])
        self.assertIsNone(accounts.view(self.rt, store=self.store, codex_home=self.codex)["switch_state"], "said once")
        self.assertIn("autoswch.manual_switched", self.journalled())

    def test_its_journal_words(self):
        self.on()
        for outcome, word in ((swap.NOT_SIGNED_IN, "manual_not_finished"), (swap.NOT_PUT_BACK, "manual_not_finished"),
                              (swap.NOT_CLOSED, "manual_not_done"), (swap.HELD, "manual_not_done")):
            with self.subTest(outcome):
                self.ask(self.two, Stand(outcome))
                self.assertEqual(self.journalled()[-1], "autoswch." + word)

    def test_it_needs_neither_capability_on(self):
        """The click and the window's question are the consent: it answers wherever the card shows the accounts."""
        code = Stand()
        self.assertTrue(self.ask(self.two, code)["done"])
        self.assertEqual(code.calls, [(self.two, True)])

    def test_refused_with_nothing_changed(self):
        """Fails with any one refusal taken out: the switch would close Codex where its own safety rules say no."""
        self.on()
        damaged = self.store.save(THREE, "three@example.com", "plus")
        self.store.update(damaged, failed_at=NOW)
        cases = [("not a row", dict(profile_id="f" * 16), Refusal.OPTION_INVALID),
                 ("in use", dict(profile_id=self.one), Refusal.ACCOUNT_IN_USE),
                 ("needs a sign-in", dict(profile_id=damaged), Refusal.ACCOUNT_NOT_READY),
                 ("busy", dict(code=Stand(busy=("turn_running",))), Refusal.RESTART_BUSY),
                 ("another engine", dict(engines=lambda: True), Refusal.OTHER_ENGINE)]
        for name, kwargs, refusal in cases:
            with self.subTest(name):
                code = kwargs.pop("code", Stand())
                profile_id = kwargs.pop("profile_id", self.two)
                self.assertEqual(self.ask(profile_id, code, **kwargs)["refusal"], refusal)
                self.assertEqual(code.calls, [])
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(self.journalled(), [])

    def test_refused_while_the_saved_accounts_are_held(self):
        self.on()
        code = Stand()
        taken, done = threading.Event(), threading.Event()

        def holder():
            # Another process's switch, read or save: the lock held on a thread of its own (it is reentrant on one).
            with self.store.locked(0):
                taken.set()
                done.wait(10)
        other = threading.Thread(target=holder)
        other.start()
        try:
            taken.wait(10)
            self.assertEqual(self.ask(self.two, code)["refusal"], Refusal.ACCOUNTS_HELD)
        finally:
            done.set()
            other.join(10)
        self.store.begin(self.one, self.two)
        self.assertEqual(self.ask(self.two, code)["refusal"], Refusal.ACCOUNTS_HELD, "a put-back still waits")
        self.store.end()
        with patch.dict(accounts._READING, {Path(self.rt.paths.home): {"state": accounts.READING}}):
            self.assertEqual(self.ask(self.two, code)["refusal"], Refusal.ACCOUNTS_HELD, "Read usage reads")
        self.assertEqual(code.calls, [])

    def test_refused_for_a_sign_in_kept_outside_a_file(self):
        self.on()
        code = Stand()
        (self.codex / "config.toml").write_text('cli_auth_credentials_store = "keyring"\n', encoding="utf-8")
        self.assertEqual(self.ask(self.two, code)["refusal"], Refusal.SIGN_IN_NOT_FILE)
        self.assertEqual(code.calls, [])

    def test_the_bridge_command(self):
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_ACCOUNTS_SWITCH], frozenset({"id"}))
        self.assertNotIn(BridgeCommand.ADVANCED_ACCOUNTS_SWITCH, surfaces.UNANSWERED)
        self.assertEqual(surfaces.bridge(self.rt, "advanced-accounts-switch", {"id": "x", "all": True})["refusal"],
                         Refusal.INVALID_REQUEST)
        self.assertEqual(surfaces.bridge(self.rt, "advanced-accounts-switch", {})["refusal"], Refusal.OPTION_INVALID)
        with patch.object(accounts, "_saved", lambda runtime: self.store):
            self.assertEqual(surfaces.bridge(self.rt, "advanced-accounts-switch", {"id": self.one})["refusal"],
                             Refusal.ACCOUNT_IN_USE)
        self.assertEqual(BridgeCommand.ADVANCED_ACCOUNTS_SWITCH.value, "advanced-accounts-switch")


class EndToEndTests(ManualCase):
    """Through the bridge's switch with the automatic switch's real code over Codex's stand-in."""

    def setUp(self):
        super().setUp()
        for name, value in (("_inventory", lambda: []), ("_clock", lambda: 0.0), ("_sleep", lambda seconds: None)):
            patcher = patch.object(swap, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fake = Fake(self, usages={"two@example.com": usage(30.0)})

    def code(self):
        return autoswitch.AutoSwitch(None, store=self.store, restart=self.fake.restart, read_real=self.fake.read_real,
                                     idle=lambda: 0, busy=lambda: (), home=self.codex)

    def test_the_account_picked_is_put_in_and_the_one_in_use_saved_back(self):
        self.on()
        self.assertTrue(self.ask(self.two, self.code())["done"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)
        self.assertEqual(self.fake.restarts, 1)
        self.assertIsNone(self.store.attempts(), "not counted toward the automatic switch's ten a day")
        self.assertEqual(self.journalled(), ["autoswch.manual_switched"])
        self.assertEqual(self.rt.state.stamped("account_auto_switch", OptionKey.AUTO_SWITCHED_AT), NOW)

    def test_one_that_did_not_finish_is_undone_and_said(self):
        self.on()
        self.fake.read_real = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com"}
        self.ask(self.two, self.code())
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(accounts.view(self.rt, store=self.store, codex_home=self.codex)["switch_state"],
                         swap.NOT_SIGNED_IN)
        self.assertEqual(self.journalled(), ["autoswch.manual_not_finished"])


class OneStoreTests(ControlCase):
    """The saved accounts under account_switch's card too: one store, kept while either capability stands."""

    def arm_one(self, capability):
        from test_advanced_autoswitch_control import ac
        from codex_auto_resume_advanced.vocabulary import Actor
        definition = self.rt.registry.get(capability)
        result = self.rt.arming.arm(capability, state="armed", revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)], actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def test_account_switch_alone_adds_saves_and_reads_the_same_store(self):
        """Fails if the card under account_switch could not keep accounts while the automatic switch is off."""
        self.arm_one("account_switch")
        reader = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com", "kind": "chatgpt"}  # noqa: E731
        self.assertTrue(accounts.save(self.rt, store=self.store, codex_home=self.codex, read_real=reader)["saved"])
        self.assertEqual(accounts.add(self.rt, start=lambda job: None, run=lambda p, s: None)["add_state"],
                         accounts.WAITING)
        accounts._ADDING.pop(Path(self.rt.paths.home), None)
        shown = accounts.view(self.rt, store=self.store, codex_home=self.codex)
        self.assertEqual((shown["standing"], shown["store"], len(shown["profiles"])), (True, "usable", 1))

    def test_account_switch_raised_its_revision_and_says_what_it_keeps(self):
        self.assertEqual(registry.ACCOUNT_SWITCH.revision, 3)
        self.assertEqual(registry.ACCOUNT_AUTO_SWITCH.revision, 2)
        for code in ("B2", "B3", "B11", "D2"):
            self.assertIn(code, registry.ACCOUNT_SWITCH.departs_from)
        from codex_auto_resume_advanced import statement
        import json
        words = json.loads((Path(statement.__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))
        does = words["statement.account_switch.does"]
        for said in ("encrypted for your Windows user", "Delete all", "Switch to this account"):
            self.assertIn(said, does)
        self.assertIn("Switch to this account", words["statement.account_auto_switch.does"])
        self.assertNotIn("never reads Codex's sign-in file", words["statement.account_switch.risks"])

    def test_off_both_nothing_is_kept(self):
        self.assertEqual(accounts.save(self.rt, store=self.store, codex_home=self.codex)["refusal"], Refusal.NOT_ON)
        self.assertEqual(accounts.read(self.rt, store=self.store)["refusal"], Refusal.NOT_ON)
        self.assertEqual(profiles.Profiles(self.dir / "home").ids(), [])


if __name__ == "__main__":
    unittest.main()
