"""account_auto_switch (v0.6.22): hidden until MPROFILE and MSWAP pass; when it acts at a usage limit; its P7 release;
its probes' verdicts; and account_switch's hold, which a switch of its own does not trigger and a person's still does.

Every home is a temporary folder, every sign-in file a fixture of no one's, and Codex, its app and the clock are fakes:
nothing real is read, closed, started or switched.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_account import OTHER, AccountCase  # noqa: E402
from test_advanced_autoswitch_swap import NOW, ONE, TWO, THREE, Fake, SwapCase, usage  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative  # noqa: E402
from codex_auto_resume_advanced import measure, profiles, registry  # noqa: E402
from codex_auto_resume_advanced.engine import autoswitch  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_AUTO_SWITCH, offered  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, OptionKey, Verdict  # noqa: E402

ENGINE = "codex-cli 0.166.0-alpha.5.1"


class HiddenTests(unittest.TestCase):
    def test_hidden_until_both_measurements_pass_on_the_codex_in_force(self):
        """Fails with the WAITING row taken out: a switch no Codex was measured to take would be offered."""
        self.assertIsNone(registry.REGISTRY.get("account_auto_switch"))
        self.assertNotIn(ACCOUNT_AUTO_SWITCH, registry.DEFINITIONS)
        passed, failed = (Verdict.PASS, ENGINE), (Verdict.FAIL, ENGINE)
        self.assertNotIn(ACCOUNT_AUTO_SWITCH, offered({}))
        self.assertNotIn(ACCOUNT_AUTO_SWITCH, offered({Measurement.MPROFILE: passed}))
        self.assertNotIn(ACCOUNT_AUTO_SWITCH, offered({Measurement.MPROFILE: passed, Measurement.MSWAP: failed}))
        self.assertIn(ACCOUNT_AUTO_SWITCH, offered({Measurement.MPROFILE: passed, Measurement.MSWAP: passed}))

    def test_its_definition(self):
        self.assertEqual(registry.problems(ACCOUNT_AUTO_SWITCH), [])
        self.assertEqual(ACCOUNT_AUTO_SWITCH.requires, ("account_switch",))
        self.assertIn("B11", ACCOUNT_AUTO_SWITCH.departs_from)
        self.assertEqual(registry.SHOWN_ORDER.index("account_auto_switch"), registry.SHOWN_ORDER.index("early_reset") + 1)


class Scoped:
    def __init__(self, now=NOW):
        self.clock, self.stamps, self.counted = now, {}, []

    def now(self):
        return self.clock

    def stamped(self, key):
        return self.stamps.get(str(key))

    def stamp(self, key, value):
        self.stamps[str(key)] = value
        return True

    def count(self, code):
        self.counted.append(code)


class View:
    def __init__(self, rows, settings=None):
        self.rows = rows
        self._settings = settings if settings is not None else {"enabled": True, "observe_only": False}

    def settings(self):
        return self._settings

    def records_in(self, states):
        return [row for row in self.rows if row["state"] in states]


def waiting(key="a", detected=NOW - autoswitch.SETTLE, category="usage_limit"):
    return {"interruption_id": key * 64, "state": "waiting_reset", "category": category, "detected_at": detected,
            "hold": None, "cancel_requested": 0}


class EngineCase(SwapCase):
    def setUp(self):
        super().setUp()
        self.fake = Fake(self, usages={"two@example.com": usage(30.0), "three@example.com": usage(60.0)})
        self.idle, self.busy = autoswitch.IDLE, ()
        self.code = autoswitch.AutoSwitch(None, store=self.store, session_for=self.fake.session_for,
                                          restart=self.fake.restart, read_real=self.fake.read_real,
                                          idle=lambda: self.idle, busy=lambda: self.busy, home=self.codex)
        self.scoped = Scoped()
        self.code.bind(self.scoped)
        self.two = self.store.save(TWO, "two@example.com", "plus")
        self.three = self.store.save(THREE, "three@example.com", "plus")

    def look(self, rows=None, settings=None):
        self.code.look(View([waiting()] if rows is None else rows, settings), self.scoped.clock)


class WhenTests(EngineCase):
    def test_at_a_usage_limit_with_nothing_running_it_switches_to_the_most_room(self):
        self.look()
        self.assertEqual(self.scoped.counted, ["switched"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO, "30 % used beats 60 %")
        self.assertEqual(self.scoped.stamps[str(OptionKey.AUTO_SWITCHED_AT)], NOW)

    def test_it_waits_while_anything_holds_it(self):
        """Fails if any one of the conditions were dropped: each would switch under it."""
        cases = {"paused": dict(settings={"enabled": False}), "observed": dict(settings={"enabled": True,
                                                                                          "observe_only": True}),
                 "too soon": dict(rows=[waiting(detected=NOW - autoswitch.SETTLE + 1)]),
                 "not a usage limit": dict(rows=[waiting(category="network_transient")]), "nothing": dict(rows=[])}
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.look(**kwargs)
        self.busy = ("turn_running",)
        self.look()
        self.busy, self.idle = (), autoswitch.IDLE - 1
        self.look()
        self.assertEqual(self.scoped.counted, [])
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_one_attempt_for_each_set_of_waiting_records(self):
        self.code._read_real = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com"}
        self.look()                                       # the app came back as the old account: put back
        self.look()
        self.assertEqual(self.scoped.counted, ["not_signed_in"])
        self.assertEqual(self.store.view()[[v["id"] for v in self.store.view()].index(self.two)]["state"],
                         profiles.NEEDS_SIGN_IN)

    def test_at_most_ten_a_day(self):
        """The owner, 2026-11-05: ten switches in 24 hours."""
        self.assertEqual(autoswitch.PER_DAY, 10)
        self.scoped.stamps.update({str(OptionKey.AUTO_SWITCH_DAY): int(NOW // autoswitch.DAY) + 1,
                                   str(OptionKey.AUTO_SWITCH_COUNT): autoswitch.PER_DAY})
        self.look()
        self.assertEqual(self.scoped.counted, ["ceiling"])
        self.scoped.clock += autoswitch.DAY
        self.look([waiting("b", detected=self.scoped.clock - autoswitch.SETTLE)])
        self.assertEqual(self.scoped.counted, ["ceiling", "switched"])
        self.assertEqual(self.scoped.stamps[str(OptionKey.AUTO_SWITCH_COUNT)], 1)

    def test_all_exhausted_waits_and_says_so_once(self):
        """Fails without the notice: the person would learn of it only from the journal."""
        self.assertIsNone(self.code.notice())
        self.fake.usages = {"two@example.com": usage(100.0, reached=True), "three@example.com": usage(97.0)}
        self.look()
        notice = self.code.notice()
        self.look()
        self.assertEqual(self.scoped.counted, ["all_exhausted"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(notice, {"key": "autoswitch:%d" % (NOW - autoswitch.SETTLE)}, "one key for the set")
        self.assertEqual(self.code.notice(), notice, "the same set asks for no second notice")

    def test_the_notice_is_core_s_kind_with_its_words(self):
        from codex_auto_resume import notifier
        from codex_auto_resume_advanced import plug
        self.assertIn(("accounts_exhausted", ("accounts_exhausted",), "msg.toast_accounts_exhausted"), plug.NOTICE_KINDS)
        self.assertEqual(notifier.STATUS["accounts_exhausted"], "paused")
        made = notifier.build("accounts_exhausted", {})
        self.assertIsNotNone(made, "core builds the notice the plug asks for")

    def test_never_back_to_an_account_exhausted_until_a_reset_ahead(self):
        """No ping-pong: an account found full is not read again before its reset."""
        self.fake.usages = {"two@example.com": usage(100.0, reached=True), "three@example.com": usage(100.0, reached=True)}
        self.look()
        homes = len(self.fake.homes)
        self.look([waiting("b")])
        self.assertEqual(len(self.fake.homes), homes, "neither was read again")

    def test_the_account_in_use_is_never_read_on_a_scratch_home(self):
        """Its refresh token would rotate under the running app."""
        self.store.save(ONE, "one@example.com", "plus")
        self.look()
        read = [path.name for path in self.fake.homes]
        self.assertEqual(len(read), 2, "two and three, never one")

    def test_a_keyring_store_is_never_switched(self):
        (self.codex / "config.toml").write_text('cli_auth_credentials_store = "auto"\n', encoding="utf-8")
        self.look()
        self.assertEqual((self.scoped.counted, self.fake.homes), ([], []))


class ScheduleTests(EngineCase):
    def test_after_its_own_switch_waiting_usage_limits_are_looked_at_early_for_a_while(self):
        record = dict(waiting(), state="waiting_reset")
        self.assertIs(self.code.schedule(record, NOW + 3600), DEFER, "no switch yet")
        self.look()
        self.assertIs(self.code.schedule(record, NOW + 3600), Alternative.EARLY)
        self.assertIs(self.code.schedule(dict(record, category="network_transient"), NOW + 3600), DEFER)
        self.assertIs(self.code.schedule(record, NOW - 1), DEFER, "already due")
        self.scoped.clock += autoswitch.EARLY_FOR
        self.assertIs(self.code.schedule(record, self.scoped.clock + 3600), DEFER)


class HoldTests(AccountCase):
    def test_its_own_switch_holds_no_recovery_and_a_persons_change_still_does(self):
        """Fails with the switched_to check removed from engine/account.py: the recoveries it switched for would be held."""
        self.on()
        self.look()
        self.code._ours = lambda paths, text, after: True
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [])
        self.assertIsNotNone(self.rt.state.stamped("account_switch", OptionKey.ACCOUNT_CHANGED_AT),
                             "window_anchor still follows the change of account")
        self.code._ours = lambda paths, text, after: False
        from test_advanced_account import ONE as FIRST
        self.answer = FIRST
        self.look()
        self.assertEqual(self.holds, [["a" * 64]])


class ProbeTests(unittest.TestCase):
    def run_probe(self, probe, answered):
        ctx = measure.Context(Measurement.MPROFILE, hands={"profile_read": lambda home: answered,
                                                           "account_swap": lambda home: answered})
        return probe(ctx)

    def test_mprofile(self):
        good = {"store_word": "usable", "profile_given": True, "account_read": True, "own_account": True,
                "usage_read": True, "real_file_unchanged": True, "app_unchanged": True, "real_still_signed_in": True,
                "email": "someone@example.com"}
        verdict, observed, _ = self.run_probe(measure._mprofile, good)
        self.assertEqual(verdict, Verdict.PASS)
        self.assertNotIn("email", observed, "only the closed fields reach the record")
        self.assertEqual(self.run_probe(measure._mprofile, dict(good, real_file_unchanged=False))[0], Verdict.FAIL)
        self.assertEqual(self.run_probe(measure._mprofile, dict(good, own_account=False))[0], Verdict.FAIL)
        self.assertEqual(self.run_probe(measure._mprofile, dict(good, profile_given=False))[0], Verdict.BLOCKED)
        self.assertEqual(self.run_probe(measure._mprofile, {"store_word": "not_file"})[0], Verdict.BLOCKED)
        self.assertEqual(self.run_probe(measure._mprofile, None)[0], Verdict.BLOCKED)

    def test_mswap(self):
        good = {"store_word": "usable", "profiles_given": True, "swapped": True, "signed_in_as_target": True,
                "swapped_back": True, "signed_in_as_first": True, "first_usage_read": True, "target_usage_read": True}
        self.assertEqual(self.run_probe(measure._mswap, good)[0], Verdict.BLOCKED, "the person confirms what the app showed")
        self.assertEqual(self.run_probe(measure._mswap, dict(good, signed_in_as_target=False))[0], Verdict.FAIL)
        self.assertEqual(self.run_probe(measure._mswap, dict(good, signed_in_as_first=False))[0], Verdict.FAIL)
        self.assertEqual(self.run_probe(measure._mswap, dict(good, first_usage_read=False))[0], Verdict.FAIL)
        self.assertEqual(self.run_probe(measure._mswap, dict(good, swapped=False))[0], Verdict.BLOCKED)


if __name__ == "__main__":
    unittest.main()
