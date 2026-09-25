"""NeutralPlug: an advanced installation with nothing turned on is the standard edition.

Every codexsim scenario is run twice, as it is written: once with NULL, the standard edition's
plug, and once with a plug that is asked at every point and defers at every one of them
(tests/neutral.py). The two runs have to leave the same rows in every store the scenario opened
and make the same calls of Codex, in the same order, and the scenario has to pass both times.
And the scenarios between them have to reach every point the engine asks, or a point nothing
reaches would pass for a neutral one.

Then the comparison is shown to be able to fail: a plug that holds every gate does change what
a scenario leaves behind, and the harness says so.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # the harness and codexsim live next to this file

import neutral  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, Point  # noqa: E402

HERE = Path(_HERE)
# A scenario that registers an interruption, sends its continuation and follows the turn.
SENDS = "test_engine.EngineScenarioTests.test_08_after_reset_and_loaded_resumes_exact_thread"


class ScenarioListTests(unittest.TestCase):
    def test_the_scenarios_are_every_module_that_drives_the_engine_against_codexsim(self):
        importers = {path.stem for path in HERE.glob("test_*.py")
                     if "codexsim" in path.read_text(encoding="utf-8") and path.stem != Path(__file__).stem}
        self.assertEqual(importers, set(neutral.MODULES) | set(neutral.NOT_SCENARIOS))
        self.assertEqual(set(neutral.MODULES) & set(neutral.NOT_SCENARIOS), set())
        for name, reason in neutral.NOT_SCENARIOS.items():
            self.assertTrue(reason.strip(), name)

    def test_the_engine_points_are_the_ones_the_engine_asks(self):
        """The rest are asked by the control layer, the bridge and the launcher, and
        tests/test_plug_points.py holds each of those where it stands."""
        self.assertEqual(set(Point) - neutral.ENGINE_POINTS,
                         {Point.START_ROUTE, Point.SURFACES, Point.SUPERVISION})


class NeutralPlugTests(unittest.TestCase):
    def test_every_codexsim_scenario_is_the_same_with_a_plug_that_always_defers(self):
        ids = neutral.scenarios()
        self.assertGreater(len(ids), 250, "the listing itself looks wrong")
        started = time.monotonic()
        results = neutral.run_all(ids)
        self.assertEqual(sorted(set(ids) - set(results)), [], "scenarios that never ran")
        self.assertEqual({key: result["error"] for key, result in results.items() if "error" in result}, {})
        self.assertEqual({key: result["difference"] for key, result in results.items()
                          if result["difference"]}, {},
                         "a plug that defers everywhere changed what a scenario did")
        self.assertEqual(sorted(key for key, result in results.items()
                                if result["standard_ok"] and not result["plugged_ok"]), [],
                         "a scenario that passes as the standard edition fails with the plug")
        self.assertEqual(sorted(key for key, result in results.items() if not result["standard_ok"]), [],
                         "a scenario fails as the standard edition: the comparison is of nothing")
        driven = [key for key, result in results.items() if result["engines"]]
        self.assertGreater(len(driven), 200, "the scenarios that build an engine are most of them")
        modules = {key.split(".", 1)[0] for key in driven}
        self.assertEqual(sorted(set(neutral.MODULES) - modules), [],
                         "a module listed as scenarios builds no engine in any of them")
        asked = set().union(*(set(result["asked"]) for result in results.values()))
        self.assertLessEqual({str(point) for point in neutral.ENGINE_POINTS}, asked,
                             "a point the engine asks that no scenario reached")
        self.assertLess(time.monotonic() - started, 1800)


class HarnessTests(unittest.TestCase):
    def test_the_comparison_sees_a_plug_that_does_something(self):
        class Holding(neutral.DeferringPlug):
            __slots__ = ()

            def gate(self, name, record, facts):
                super().gate(name, record, facts)
                return Alternative.HOLD

        since = time.time()
        runs = [neutral.run_one(SENDS, plug=plug, seed=SENDS)
                for plug in (None, Holding(), neutral.DeferringPlug())]
        standard, holding, deferring = (neutral.steady(run, since, time.time()) for run in runs)
        self.assertTrue(standard["ok"])
        self.assertGreater(standard["engines"], 0)
        self.assertTrue(any(call[0] == "send" for call in standard["calls"]))
        self.assertIn("backend call", neutral._difference(standard, holding))
        self.assertIsNone(neutral._difference(standard, deferring))

    def test_only_a_moment_read_off_the_wall_clock_is_held_still(self):
        since, until = 1000.0, 2000.0
        self.assertEqual(neutral.steady({"at": [999.5, 1500.0, 2000.5, 1500, "1500.0"]}, since, until),
                         {"at": [999.5, neutral.WALL_CLOCK, 2000.5, 1500, "1500.0"]})


if __name__ == "__main__":
    unittest.main()
