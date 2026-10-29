"""Keep on is offered for every capability (the owner's word of 2026-10-24, v0.6.19-beta.3: "every capability may be
kept on if the person wants"), and none is kept on unless the person chose it on that capability's card.

Before, two capabilities (other_sessions, silent_continuation) carried `keepable=False` and Keep on was refused for them.
These tests fail if any capability - shipped now, or waiting on its measurement - is refused Keep on again, or if
anything but a person's choice keeps one on: a fresh state, and a state an earlier version wrote, read back unchanged.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.registry import CapabilityDef, Registry  # noqa: E402
from codex_auto_resume_advanced.runtime import Runtime  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, KeepOn, Refusal  # noqa: E402

CONFIRMED = [str(KeepOn.KEEP_ON)]
EVERY = registry.DEFINITIONS + tuple(definition for definition, _measurement in registry.WAITING)


class EveryCase(ac.AdvancedCase):
    def runtime(self, *definitions):
        made = Runtime(self.paths, registry=Registry(definitions or EVERY), clock=lambda: self.now,
                       policy=lambda: self.policy, view=lambda: self.compat, measured=lambda: self.measured,
                       catalogs=statement.CATALOGS)
        self.addCleanup(made.state.close)
        return made


class OfferedTests(EveryCase):
    def test_no_capability_carries_a_way_to_refuse_keep_on(self):
        """The field that refused it is gone: adding it back, for any capability, fails here first."""
        self.assertNotIn("keepable", {field.name for field in dataclasses.fields(CapabilityDef)})
        self.assertEqual(len({definition.id for definition in EVERY}), len(EVERY))

    def test_keep_on_is_never_an_invalid_request_for_any_capability(self):
        """Every capability, shipped or waiting: Keep on of one not on is refused only because it is not on (NOT_ON),
        and the arm's own Keep it on only for the confirmation it carries here - never as a request that may not be
        made (INVALID_REQUEST), which is how Keep on was refused for the two that could not be kept on."""
        runtime = self.runtime()
        for definition in EVERY:
            with self.subTest(capability=definition.id):
                kept = runtime.arming.set_keep_on(definition.id, True, generation=runtime.state.meta()["generation"],
                                                  confirmed=CONFIRMED, actor=Actor.DASHBOARD)
                self.assertEqual((kept["done"], kept["refusal"]), (False, Refusal.NOT_ON))
                armed = runtime.arming.arm(definition.id, state="armed", revision=definition.revision + 1000,
                                           generation=runtime.state.meta()["generation"],
                                           acknowledged_version=ac.ENGINE, keep_on=True, actor=Actor.DASHBOARD)
                self.assertFalse(armed["done"])
                self.assertNotEqual(armed["refusal"], Refusal.INVALID_REQUEST, armed)


class ChosenOnlyTests(EveryCase):
    def kept(self, runtime):
        return sorted(item["id"] for item in runtime.arming.listing()["capabilities"] if item["keep_on"])

    def test_a_fresh_state_keeps_nothing_on(self):
        runtime = self.runtime()
        listed = runtime.arming.listing()["capabilities"]
        self.assertTrue(listed)
        self.assertEqual(self.kept(runtime), [])
        self.assertEqual([item["id"] for item in listed if item["send_again"]], [])

    def test_a_state_written_before_keeps_on_exactly_what_the_person_chose(self):
        """A state an earlier version wrote - one capability on and kept on by the person, another on and not kept on
        - read by this version's registry, where every capability may be kept on: only the chosen one is kept on."""
        before = ac.definition()                      # the earlier version's: one test capability, keepable as ever
        other = ac.definition(id="test_other", journal_prefix="other")
        self.catalogs = ac.catalogs(self.home.parent / "both", before, other)
        earlier = Runtime(self.paths, **self.options(before, other))
        for capability in (before.id, other.id):
            self.assertTrue(self.arm(earlier, capability)["done"])
        earlier.states(fresh=True)
        kept = earlier.arming.set_keep_on(before.id, True, generation=earlier.state.meta()["generation"],
                                          confirmed=CONFIRMED, actor=Actor.DASHBOARD)
        self.assertTrue(kept["done"], kept)
        earlier.state.close()
        now = Runtime(self.paths, registry=Registry(EVERY + (before, other)), clock=lambda: self.now,
                      policy=lambda: self.policy, view=lambda: self.compat, measured=lambda: self.measured,
                      catalogs=self.catalogs)
        self.addCleanup(now.state.close)
        rows = now.state.arming()
        self.assertTrue(rows[before.id]["keep_on"])
        self.assertFalse(rows[other.id]["keep_on"])
        self.assertEqual(sorted(capability for capability, row in rows.items() if row.get("keep_on")), [before.id])


if __name__ == "__main__":
    unittest.main()
