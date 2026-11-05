"""account_auto_switch's saved accounts through the bridge (v0.6.22, control/autoswitch.py), and its place beside the
capabilities it composes with once it is offered.

Every home is a temporary folder and every sign-in file a fixture of no one's; Codex's sign-in is a stand-in.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_autoswitch_profiles import opened, sealed  # noqa: E402
from codex_auto_resume_advanced import profiles, registry, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.control import autoswitch as accounts  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_AUTO_SWITCH, ACCOUNT_SWITCH, Registry, offered  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, Measurement, Refusal, Verdict  # noqa: E402

ONE = json.dumps({"fixture": "one"}).encode("utf-8")
TWO = json.dumps({"fixture": "two"}).encode("utf-8")
PASSED = {Measurement.MPROFILE: (Verdict.PASS, "x"), Measurement.MSWAP: (Verdict.PASS, "x")}


class OfferedOrderTests(unittest.TestCase):
    def test_once_offered_it_answers_after_the_reset_actions_and_needs_account_switch(self):
        """reset_credit and early_reset answer P7 first: a credit or an early reset goes before a switch."""
        made = Registry(registry.DEFINITIONS + offered(PASSED))
        ids = made.ids
        self.assertGreater(ids.index("account_auto_switch"), ids.index("reset_credit"))
        self.assertGreater(ids.index("account_auto_switch"), ids.index("early_reset"))
        self.assertEqual(made.requires("account_auto_switch"), ("account_switch",))
        self.assertIn("account_auto_switch", made.required_by("account_switch"))


class ControlCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="usage_probe")
        self.rt = self.runtime(ACCOUNT_SWITCH, ACCOUNT_AUTO_SWITCH)
        self.rt.arming.catalogs = statement.CATALOGS
        self.dir = Path(tempfile.mkdtemp(prefix="car-autoswitch-control-"))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.codex = self.dir / "codex"
        self.codex.mkdir()
        (self.codex / "auth.json").write_bytes(ONE)
        self.store = profiles.Profiles(self.dir / "home", seal=sealed, open_=opened)

    def on(self):
        for capability in ("account_switch", "account_auto_switch"):
            definition = self.rt.registry.get(capability)
            result = self.rt.arming.arm(capability, state="armed", revision=definition.revision,
                                        generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                        warnings=[str(w) for w in self.rt.arming.warnings(definition)],
                                        actor=Actor.DASHBOARD)
            self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)


class ControlTests(ControlCase):
    def test_off_nothing_is_kept_and_what_is_kept_can_go(self):
        """Fails if Add or Save answered while the capability is off (or hidden, when no runtime has it) - or if the
        card or Delete did not (the security review's finding 3: a saved sign-in is deletable in every state)."""
        self.assertEqual(accounts.save(self.rt, store=self.store, codex_home=self.codex)["refusal"], Refusal.NOT_ON)
        self.assertEqual(accounts.add(self.rt, start=lambda job: job(), run=lambda p, s: "x")["refusal"], Refusal.NOT_ON)
        self.assertEqual(self.store.ids(), [])
        self.assertIsNone(accounts.view(self.rt, store=self.store, codex_home=self.codex)["refusal"])
        self.assertTrue(surfaces.bridge(self.rt, "advanced-accounts-delete", {"all": True})["done"])

    def test_save_view_and_delete_show_only_a_masked_address(self):
        self.on()
        reader = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com", "kind": "chatgpt"}  # noqa: E731
        self.assertTrue(accounts.save(self.rt, store=self.store, codex_home=self.codex, read_real=reader)["saved"])
        shown = accounts.view(self.rt, store=self.store, codex_home=self.codex)
        self.assertEqual((shown["store"], len(shown["profiles"])), ("usable", 1))
        self.assertNotIn("one@example.com", json.dumps(shown))
        profile_id = shown["profiles"][0]["id"]
        self.assertEqual(accounts.delete(self.rt, {"id": "f" * 16}, store=self.store)["refusal"], Refusal.OPTION_INVALID)
        self.assertEqual(accounts.delete(self.rt, {"id": profile_id}, store=self.store)["deleted"], 1)
        self.assertEqual(self.store.ids(), [])

    def test_add_runs_once_at_a_time_and_says_how_it_ended(self):
        self.on()
        jobs = []
        first = accounts.add(self.rt, start=jobs.append, run=lambda paths, store: "a" * 16)
        self.assertEqual(first["add_state"], accounts.WAITING)
        self.assertEqual(accounts.add(self.rt, start=jobs.append, run=lambda p, s: None)["refusal"],
                         Refusal.SWITCH_RUNNING)
        jobs[0]()
        self.assertEqual(accounts.view(self.rt, store=self.store, codex_home=self.codex)["add_state"], accounts.ADDED)

    def test_the_bridge_takes_only_its_arguments(self):
        self.on()
        self.assertEqual(surfaces.bridge(self.rt, "advanced-accounts-delete", {"path": "x"})["refusal"],
                         Refusal.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
