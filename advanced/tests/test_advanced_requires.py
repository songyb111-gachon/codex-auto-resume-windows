"""A capability that needs another (v0.6.16-beta.3, registry.CapabilityDef.requires, the owner's rule):
turning one on turns on what it requires in the same confirmation; turning a required one off turns off
what requires it, named first; a required one an administrator forbids, or whose compatibility failed
here, keeps the dependent off, with the reason.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import policy, registry  # noqa: E402
from codex_auto_resume_advanced.registry import CapabilityDef, Ceilings, Registry, RegistryError  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, OffReason, Refusal  # noqa: E402

ENGINE = ac.ENGINE


# The requirement stands on a compatibility capability of its own, so a FAILED_HERE on it never also
# trips the dependent for the dependent's own compat.
REQ_COMPAT = "req_compat"


def _dep():
    return ac.definition(id="test_dep", journal_prefix="tdep", requires=("test_req",))


def _req(**changes):
    return ac.definition(id="test_req", journal_prefix="treq", compat=REQ_COMPAT, **changes)


def _view_both(req_state="COMPATIBLE", dep_state="COMPATIBLE"):
    """A Compatibility Registry view with the requirement's and the dependent's own capabilities."""
    return {"status": "ok", "engine": {"found": True, "version": ENGINE},
            "capabilities": {REQ_COMPAT: {"state": req_state, "reason": "local_checks_passed"},
                             ac.COMPAT: {"state": dep_state, "reason": "local_checks_passed"}}}


class RegistryShapeTests(unittest.TestCase):
    def test_a_require_of_an_unknown_capability_is_refused(self):
        with self.assertRaises(RegistryError):
            Registry((ac.definition(requires=("not_there",)),))

    def test_a_capability_may_not_require_itself(self):
        with self.assertRaises(RegistryError):
            Registry((ac.definition(requires=("test_wake",)),))

    def test_a_cycle_is_refused(self):
        a = ac.definition(id="a_one", journal_prefix="aone", requires=("a_two",))
        b = ac.definition(id="a_two", journal_prefix="atwo", requires=("a_one",))
        with self.assertRaises(RegistryError):
            Registry((a, b))

    def test_requires_is_transitive_and_requirements_come_first(self):
        a = ac.definition(id="a_one", journal_prefix="aone")
        b = ac.definition(id="a_two", journal_prefix="atwo", requires=("a_one",))
        c = ac.definition(id="a_thr", journal_prefix="athr", requires=("a_two",))
        made = Registry((a, b, c))
        self.assertEqual(made.requires("a_thr"), ("a_one", "a_two"))
        self.assertEqual(made.required_by("a_one"), ("a_two", "a_thr"))

    def test_the_shipped_pairs_are_the_meters_and_longer_messages_requires_nothing(self):
        """The audit (v0.6.16-beta.3): no capability before it needs another. Longer messages lengthens what the
        message at a reset and the prompt queue send - either one - so it requires neither."""
        shipped = {d.id: d.requires for d in registry.DEFINITIONS if d.requires}
        # v0.6.20: the usage and token analytics read the meter's readings for their pace, so they need it too; and the
        # steer (#50), written in the prompt queue's editor.
        self.assertEqual(shipped, {"usage_wrap_up": ("usage_meter",), "usage_pause": ("usage_meter",),
                                   "usage_analytics": ("usage_meter",), "steer_send": ("prompt_queue",)})
        self.assertEqual(registry.REGISTRY.get("long_reset_message").requires, ())


class RequireCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.defs = (_req(), _dep())
        self.compat = _view_both()
        self.rt = self.runtime(*self.defs)
        self.catalogs = ac.catalogs(self.home.parent / "two", *self.defs)
        self.rt.arming.catalogs = self.catalogs

    def _arm(self, capability, state="armed", also=None, generation=None):
        request = dict(state=state, revision=1,
                       generation=self.rt.state.meta()["generation"] if generation is None else generation,
                       acknowledged_version=ENGINE, actor=Actor.DASHBOARD)
        if also is not None:
            request["also"] = also
        return self.rt.arming.arm(capability, **request)

    def _also_entry(self, capability="test_req"):
        return {"capability": capability, "revision": 1, "warnings": [], "engine_version": ENGINE}

    def _states(self):
        return self.rt.arming.current()


class OneConfirmationTests(RequireCase):
    def test_turning_the_dependent_on_turns_the_requirement_on_too(self):
        """One yes (the `also` the Dashboard gathered) turns on the dependent and its requirement, in one
        confirmation, moving the generation once."""
        before = self.rt.state.meta()["generation"]
        result = self._arm("test_dep", also=[self._also_entry()])
        self.assertTrue(result["done"], result)
        self.assertEqual(self._states(), {"test_req": ArmingState.ARMED, "test_dep": ArmingState.ARMED})
        self.assertEqual(result["generation"], before + 1)

    def test_the_dependent_alone_needs_its_requirement_in_also(self):
        """Without the requirement's confirmation, turning the dependent on is refused: it would be on
        with its requirement off."""
        self.assertEqual(self._arm("test_dep")["refusal"], Refusal.REQUIREMENT_REFUSED)
        self.assertEqual(self._states()["test_dep"], ArmingState.OFF)

    def test_also_may_not_carry_more_than_the_requirements_that_are_off(self):
        self.assertTrue(self._arm("test_req")["done"])
        # test_req is on now, so turning test_dep on needs no `also` at all.
        self.assertEqual(self._arm("test_dep", also=[self._also_entry()])["refusal"], Refusal.REQUIREMENT_REFUSED)
        self.assertTrue(self._arm("test_dep")["done"])
        self.assertEqual(self._states()["test_dep"], ArmingState.ARMED)

    def test_a_requirement_failed_here_refuses_the_whole_arm_whatever_is_confirmed(self):
        """The owner's rule: an administrator's policy or a Failed-here grade on the required one keeps the dependent
        off, with the reason - a Failed-here warning confirmed in `also` turns neither on."""
        self.compat = _view_both(req_state="FAILED_HERE")
        shown = [str(word) for word in self.rt.arming.warnings(self.rt.registry.get("test_req"))]
        self.assertIn("failed_here", shown)
        result = self._arm("test_dep", also=[dict(self._also_entry(), warnings=shown)])
        self.assertEqual((result["done"], result["refusal"]), (False, Refusal.REQUIREMENT_FAILED_HERE))
        self.assertEqual(self._states(), {"test_req": ArmingState.OFF, "test_dep": ArmingState.OFF})

    def test_watching_the_dependent_needs_no_requirement(self):
        result = self._arm("test_dep", state="shadow")
        self.assertTrue(result["done"], result)
        self.assertEqual(self._states(), {"test_req": ArmingState.OFF, "test_dep": ArmingState.SHADOW})
        self.assertEqual(self._arm("test_dep", state="shadow", also=[self._also_entry()])["refusal"],
                         Refusal.INVALID_REQUEST)


class RequirementPolicyTests(RequireCase):
    def test_a_policy_forbidding_the_requirement_keeps_the_dependent_off(self):
        """An administrator's AllowedCapabilities that leaves the requirement out refuses the whole arm,
        with the requirement's policy refusal: the dependent cannot be on without it."""
        self.policy = policy.Policy(allowed=frozenset({"test_dep"}))
        self.assertEqual(self._arm("test_dep", also=[self._also_entry()])["refusal"],
                         Refusal.NOT_ALLOWED_BY_POLICY)
        self.assertEqual(self._states()["test_dep"], ArmingState.OFF)


class CascadeTests(RequireCase):
    def _turn_both_on(self):
        self.assertTrue(self._arm("test_dep", also=[self._also_entry()])["done"])

    def test_turning_the_requirement_off_turns_the_dependent_off_first(self):
        self._turn_both_on()
        result = self.rt.arming.disarm("test_req", actor=Actor.DASHBOARD)
        self.assertTrue(result["done"])
        self.assertEqual(result["also_off"], ["test_dep"])
        self.assertEqual(self._states(), {"test_req": ArmingState.OFF, "test_dep": ArmingState.OFF})

    def test_standing_reads_a_dependent_down_when_its_requirement_is_not_on(self):
        """However its requirement left - watched elsewhere, say - an armed dependent is read down to off,
        with REQUIREMENT_OFF, at the next read."""
        self._turn_both_on()
        self.rt.state.move("test_req", ArmingState.SHADOW, actor=Actor.MCP)
        self.assertEqual(self._states()["test_dep"], ArmingState.OFF)
        row = self.rt.state.arming()["test_dep"]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.OFF, OffReason.REQUIREMENT_OFF))

    def test_a_failed_here_requirement_keeps_the_dependent_off(self):
        """The requirement's compatibility failing here trips the requirement; the dependent, whose own
        compatibility is fine, is read down for its requirement being off (REQUIREMENT_OFF)."""
        self._turn_both_on()
        self.compat = _view_both(req_state="FAILED_HERE")
        self.assertEqual(self._states(), {"test_req": ArmingState.OFF, "test_dep": ArmingState.OFF})
        self.assertEqual(self.rt.state.arming()["test_dep"]["reason"], OffReason.REQUIREMENT_OFF)


class KeptOnTests(RequireCase):
    def test_a_kept_on_dependent_notes_the_requirement_off_and_stays(self):
        """Keep on (K8): a kept-on dependent whose requirement goes off notes REQUIREMENT_OFF and stays
        where it stands, rather than turning itself off."""
        self.assertTrue(self._arm("test_dep", also=[self._also_entry()])["done"])
        self.assertEqual(self.rt.arming.set_keep_on("test_dep", True, generation=self.rt.state.meta()["generation"],
                                                    confirmed=["keep_on"], actor=Actor.DASHBOARD)["refusal"], None)
        self.rt.state.move("test_req", ArmingState.OFF, actor=Actor.MCP)
        self.assertEqual(self._states()["test_dep"], ArmingState.ARMED)
        self.assertEqual(self.rt.state.arming()["test_dep"]["reason"], OffReason.REQUIREMENT_OFF)


if __name__ == "__main__":
    unittest.main()
