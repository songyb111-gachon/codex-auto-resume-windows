"""A measurement only a part rests on narrows that part and never turns the capability off (v0.6.20).

MK (keep_going: three continuations until it passes), MQ (parallel_dispatch: two workers), MS (subagent_parent: 5a
alone, 5b waits) and MTOK (usage_analytics: the lifetime totals alone where it failed) each decide one part of their
capability, as MAL decides account_switch's button (commit ec3ce825d). Listed among `measurements`, a fail of one was
a MEASUREMENT_FAILED warning nobody confirmed - a tripwire (arming.standing) - and would have turned the capability
off, as MAL's did to the owner's watched account_switch at the v0.6.20 update. Each now stands in `narrowed_by`: its
statement still warns of it (MEASUREMENT_FAILED, UNMEASURED), its code still reads it where the part is decided, and
its fail never trips.

Every read is a fake and every home a temporary folder: no Codex runs.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced import arming, registry, statement  # noqa: E402
from codex_auto_resume_advanced.engine import keepgoing, parallel, subagent  # noqa: E402
from codex_auto_resume_advanced.engine.analytics import UsageAnalytics  # noqa: E402
from codex_auto_resume_advanced.registry import (ACCOUNT_SWITCH, KEEP_GOING, PARALLEL_DISPATCH, SUBAGENT_PARENT,  # noqa: E402
                                                 USAGE_ANALYTICS, USAGE_METER)
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, Measurement,  # noqa: E402
                                                   OffReason, OptionKey, Verdict)

NARROWED = ((KEEP_GOING, Measurement.MK), (PARALLEL_DISPATCH, Measurement.MQ), (SUBAGENT_PARENT, Measurement.MS),
            (USAGE_ANALYTICS, Measurement.MTOK),
            # v0.6.20 final: the button rests on MALR, the sign-in then the restart, in place of MAL.
            (ACCOUNT_SWITCH, Measurement.MALR))


class DefinitionTests(unittest.TestCase):
    def test_each_part_measurement_is_narrowing_and_never_its_route(self):
        """Fails with the four restored to `measurements`."""
        for definition, measurement in NARROWED:
            with self.subTest(definition.id):
                self.assertEqual(definition.narrowed_by, (measurement,))
                self.assertNotIn(measurement, definition.measurements)
                self.assertEqual(registry.problems(definition), [])
        self.assertEqual(USAGE_ANALYTICS.measurements, (Measurement.MU,), "MU, the meter's reads, stays its route")

    def test_a_measurement_both_route_and_part_or_on_an_action_is_a_problem(self):
        both = ac.definition(measurements=(Measurement.MK,), narrowed_by=(Measurement.MK,))
        self.assertIn("narrowed_by", registry.problems(both))
        self.assertIn("narrowed_by", registry.problems(ac.definition(narrowed_by=("mk",))))

    def test_only_route_measurements_feed_the_tripwire(self):
        view = ac.view(capability=KEEP_GOING.compat)
        failed = {Measurement.MK: (Verdict.FAIL, ac.ENGINE)}
        self.assertIn(ArmingWarning.MEASUREMENT_FAILED, arming.warnings_for(KEEP_GOING, view, failed))
        self.assertNotIn(ArmingWarning.MEASUREMENT_FAILED, arming.warnings_for(KEEP_GOING, view, failed, parts=False))
        self.assertIn(ArmingWarning.UNMEASURED, arming.warnings_for(KEEP_GOING, view, {}), "unmeasured still shown")


class FailTests(ac.AdvancedCase):
    """An installation with one of them on, or watched, while its part measurement was unmeasured meets its fail."""

    def runtime_for(self, definition):
        # A home of its own for each, so one capability's arming never meets another's.
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name) / "home"
        self.paths = config.Paths(self.home)
        self.compat = ac.view(capability=definition.compat)
        self.measured = {Measurement.MU: (Verdict.PASS, ac.ENGINE)}
        definitions = (USAGE_METER, definition) if definition.requires else (definition,)
        rt = self.runtime(*definitions)
        rt.arming.catalogs = statement.CATALOGS
        return rt, definitions

    def on(self, rt, definition, state):
        result = rt.arming.arm(definition.id, state=state, revision=definition.revision,
                               generation=rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                               warnings=[str(w) for w in rt.arming.warnings(definition)], actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def turned_on(self, definition, state):
        rt, definitions = self.runtime_for(definition)
        for each in definitions:
            self.on(rt, each, state if each is definition else ArmingState.ARMED)
        return rt

    def test_on_or_watched_each_stays_where_it_stood_and_still_warns(self):
        """Fails with the four restored to `measurements`: the tripwire turns each off (measurement_failed)."""
        for definition, measurement in NARROWED:
            for state in (ArmingState.ARMED, ArmingState.SHADOW):
                with self.subTest(definition.id, state=state):
                    rt = self.turned_on(definition, state)
                    self.measured = dict(self.measured, **{measurement: (Verdict.FAIL, ac.ENGINE)})
                    self.assertEqual(rt.states(fresh=True).get(definition.id), state, "its part's fail turned it off")
                    row = rt.state.arming()[definition.id]
                    self.assertEqual((row["state"], row["reason"]), (state, None))
                    self.assertIn(ArmingWarning.MEASUREMENT_FAILED, rt.arming.warnings(definition),
                                  "the statement still warns of the part's fail")
                    listed = next(item for item in rt.arming.listing()["capabilities"] if item["id"] == definition.id)
                    self.assertEqual((listed["state"], listed["reason"], listed["notice"]), (state, None, None))
                    self.assertIn(str(measurement), listed["measurements"])
                    self.assertEqual(rt.arming.verdict(measurement), "fail", "its code still reads the fail")

    def test_a_route_measurement_still_trips(self):
        """The tripwire itself is unchanged: MU, usage_analytics' route, failing turns it off."""
        rt = self.turned_on(USAGE_ANALYTICS, ArmingState.ARMED)
        self.measured = {Measurement.MU: (Verdict.FAIL, ac.ENGINE)}
        self.assertEqual(rt.states(fresh=True).get(USAGE_ANALYTICS.id), ArmingState.OFF)
        self.assertEqual(rt.state.arming()[USAGE_ANALYTICS.id]["reason"], OffReason.MEASUREMENT_FAILED)


class Scoped:
    """What a capability's code is bound to, as far as the narrowed parts read it: a verdict per measurement."""

    def __init__(self, verdicts, **more):
        self.verdicts = verdicts
        self.stamped = []
        for name, value in more.items():
            setattr(self, name, value)

    def passed(self, measurement):
        return self.verdicts.get(measurement) == "pass"

    def failed(self, measurement):
        return self.verdicts.get(measurement) == "fail"

    def options(self):
        return {OptionKey.WORKERS: 4}

    def now(self):
        return ac.NOW

    def stamp(self, key, value):
        self.stamped.append(key)


class NarrowedRouteOnFailTests(unittest.TestCase):
    """On a fail each part takes its narrower route, as it does unmeasured."""

    def test_parallel_dispatch_holds_two_workers(self):
        code = parallel.ParallelDispatch(None)
        code.bind(Scoped({Measurement.MQ: "fail"}))
        self.assertEqual(code.partition([{}, {}]), parallel.UNMEASURED_WORKERS)
        code.bind(Scoped({Measurement.MQ: "pass"}))
        self.assertEqual(code.partition([{}, {}]), 4)

    def test_keep_going_sends_three_at_most(self):
        self.assertEqual(keepgoing.allowed(10, Scoped({Measurement.MK: "fail"}).passed(Measurement.MK)),
                         keepgoing.UNMEASURED_COUNT)

    def test_subagent_parent_runs_5a_alone(self):
        code = subagent.SubagentParent(None)
        code.bind(Scoped({Measurement.MS: "fail"}))
        self.assertIs(code.tick(ac.view()), DEFER)

    def test_usage_analytics_reads_no_rollout(self):
        class Handle:
            def on(self):
                return True

            def files(self):
                raise AssertionError("no rollout is read where MTOK failed")
        scoped = Scoped({Measurement.MTOK: "fail"}, analytics=Handle())
        code = UsageAnalytics(None, homes=lambda: (), clock=lambda: 0.0)
        code.bind(scoped)
        self.assertIsNone(code.ingest())
        self.assertEqual(scoped.stamped, [OptionKey.LAST_INGEST])


if __name__ == "__main__":
    unittest.main()
