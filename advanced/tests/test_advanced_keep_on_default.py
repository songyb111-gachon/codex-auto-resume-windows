"""Keep it on by default (v0.6.22, the owner's 2026-11-08): the Dashboard's Turn on asks for Keep it on unless the person
turns it off in the same dialog (the page's own tests: test_advanced_page_arming), and the arm takes it for what it turns
on with the capability as well - each requirement turned on in the same confirmation is kept on too, one already on is
left as it is, and without keep_on neither is kept. Kept on by default for a new turn-on, never by migration: a capability
on but not kept stays exactly so when the edition's state is opened again, as an update's restart opens it, and can still
be kept on later. Only the Dashboard arms.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced.courier import api, telegram  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, Refusal  # noqa: E402
from test_advanced_requires import RequireCase  # noqa: E402


class RequirementsFollowTests(RequireCase):
    def kept(self):
        rows = self.rt.state.arming()
        return {capability: (rows[capability]["state"], rows[capability]["keep_on"]) for capability in rows}

    def test_what_it_needs_is_kept_on_with_it(self):
        """Fails with the arm keeping only the capability itself (keep=(capability,)): the requirement is on, not kept."""
        found = self.rt.arming.arm("test_dep", state=ArmingState.ARMED, revision=1,
                                   generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                   also=[self._also_entry()], keep_on=True, actor=Actor.DASHBOARD)
        self.assertTrue(found["done"], found)
        self.assertEqual(self.kept(), {"test_dep": (ArmingState.ARMED, True), "test_req": (ArmingState.ARMED, True)})

    def test_without_keep_on_neither_is_kept(self):
        self.assertTrue(self._arm("test_dep", also=[self._also_entry()])["done"])
        self.assertEqual(self.kept(), {"test_dep": (ArmingState.ARMED, False), "test_req": (ArmingState.ARMED, False)})

    def test_a_requirement_already_on_is_left_as_it_is(self):
        """One on already is not in the confirmation, so a kept-on dependent does not change it."""
        self.assertTrue(self._arm("test_req")["done"])
        found = self.rt.arming.arm("test_dep", state=ArmingState.ARMED, revision=1,
                                   generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                   keep_on=True, actor=Actor.DASHBOARD)
        self.assertTrue(found["done"], found)
        self.assertEqual(self.kept(), {"test_dep": (ArmingState.ARMED, True), "test_req": (ArmingState.ARMED, False)})


class NeverByMigrationTests(ac.AdvancedCase):
    def test_on_but_not_kept_stays_so_when_opened_again_and_can_be_kept_on_later(self):
        """No migration: the row - state, keep_on, since, who - read before and after the state is opened again by a new
        runtime, as the watcher opens it after an update. Then the card's Keep it on... (an arm with keep_on) keeps it."""
        first = self.runtime()
        self.assertTrue(self.arm(first)["done"])
        before = dict(first.state.arming()["test_wake"])
        listed_before = first.arming.listing()["capabilities"][0]["keep_on"]
        first.state.close()
        self.now += 3600
        again = self.runtime()
        after = dict(again.state.arming()["test_wake"])
        self.assertEqual(after, before)
        self.assertEqual((after["state"], after["keep_on"], listed_before), (ArmingState.ARMED, False, False))
        self.assertIs(again.arming.listing()["capabilities"][0]["keep_on"], False)
        self.assertTrue(self.arm(again, keep_on=True)["done"])
        self.assertEqual((again.state.arming()["test_wake"]["state"], again.state.arming()["test_wake"]["keep_on"]),
                         (ArmingState.ARMED, True))


class OnlyTheDashboardTests(ac.AdvancedCase):
    def test_no_other_surface_turns_one_on_kept_or_not(self):
        rt = self.runtime()
        for actor in Actor:
            if actor == Actor.DASHBOARD:
                continue
            for keep_on in (True, False):
                with self.subTest(actor=actor, keep_on=keep_on):
                    self.assertEqual(self.arm(rt, actor=actor, keep_on=keep_on)["refusal"], Refusal.NOT_THE_DASHBOARD)
        self.assertIsNone(rt.state.arming().get("test_wake"))
        # The loopback API's routes and Telegram's commands: none arms.
        self.assertFalse([route for route in api.ROUTES if "arm" in route or "keep" in route])
        self.assertFalse([command for command in telegram.COMMANDS if "arm" in command or "keep" in command])


if __name__ == "__main__":
    unittest.main()
