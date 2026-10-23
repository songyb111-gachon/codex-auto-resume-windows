"""NeutralPlug: an advanced installation with nothing turned on is the standard edition.

Every codexsim scenario is run twice, as it is written: once with NULL, the standard edition's
plug, and once with a plug that is asked at every point and defers at every one of them
(tests/neutral.py). The two runs have to leave the same rows in every store the scenario opened
and make the same calls of Codex, in the same order, and the scenario has to pass both times.
And the scenarios between them have to reach every point the engine asks, or a point nothing
reaches would pass for a neutral one.

Then the comparison is shown to be able to fail: a plug that holds every gate does change what
a scenario leaves behind, and the harness says so.

The comparison runs in SHARES, one module each (tests/test_neutral_plug_1.py to _4): as one test
it took 17 to 25 minutes of one CI part, and scripts/test_parts.py deals whole files. Each share
holds its own scenarios to every rule above; this module holds that the shares together are every
scenario exactly once, and that what was asked of all of them at once - most scenarios build an
engine, every module builds one somewhere, every point is reached - still follows from what each
share is held to.
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
# The scenarios in shares of about equal time, share N run by tests/test_neutral_plug_<N>.py. Each entry is a module, a
# class or one scenario, by its id; a scenario is in the share whose entry names it most closely, so a share can take
# one long scenario or class out of a module another share holds. The three longest scenarios - test_outcomes' T18
# usage chain and two T28 usage expiries, each a week of ticks - are in three shares, since none ends sooner than its
# longest scenario. With each: how many of its scenarios at least build an engine (the shares' figures add up to more
# than the 200 the whole run was held to), and the engine points its scenarios must reach between them (the shares'
# add up to every one).
SHARES = (
    {"entries": ("test_outcomes.T28UsageExpiryTests.test_T28_seven_days_unavailable_with_no_reset_is_a_terminal_failure",
                 "test_correlation"),
     "driven": 15, "points": frozenset()},
    {"entries": ("test_outcomes.T18ChainTests", "test_recovery", "test_ladder_and_guards", "test_rescan"),
     "driven": 53, "points": frozenset()},
    {"entries": ("test_outcomes",),
     "driven": 32, "points": frozenset()},
    {"entries": ("test_engine", "test_continuation_split", "test_once_words_engine", "test_skip_reasons", "test_checkup",
                 "test_engine_gates", "test_compat_io", "test_compat_characterization", "test_pause_unknown",
                 "test_engine_children"),
     "driven": 102, "points": neutral.ENGINE_POINTS},
)


def entry_of(test_id: str, entries) -> str | None:
    """The one of `entries` that names `test_id` most closely - itself, its class or its module - or None."""
    named = [entry for entry in entries if test_id == entry or test_id.startswith(entry + ".")]
    return max(named, key=len) if named else None


def share_of(test_id: str, shares=SHARES) -> int | None:
    """The 1-based share whose entry names `test_id` most closely, or None where no entry names it."""
    found = [(len(entry), index) for index, share in enumerate(shares, 1)
             for entry in [entry_of(test_id, share["entries"])] if entry]
    return max(found)[1] if found else None


def share_ids(share: int, ids=None) -> list:
    """The scenarios of share `share` (1-based), in the loader's order."""
    return [test_id for test_id in (neutral.scenarios() if ids is None else ids) if share_of(test_id) == share]


def check_share(case: unittest.TestCase, share: int) -> None:
    """Every scenario of share `share`, compared, held to what the whole run was held to: run with NULL and with a
    plug that defers everywhere (and, in the advanced lane, the advanced package's own plug), each the same."""
    rules = SHARES[share - 1]
    ids = share_ids(share)
    case.assertTrue(ids, "share %d has no scenarios" % share)
    results = neutral.run_all(ids)
    case.assertEqual(sorted(set(ids) - set(results)), [], "scenarios that never ran")
    case.assertEqual({key: result["error"] for key, result in results.items() if "error" in result}, {})
    case.assertEqual({key: result["difference"] for key, result in results.items()
                      if result["difference"]}, {},
                     "a plug that defers everywhere changed what a scenario did")
    case.assertEqual(sorted(key for key, result in results.items()
                            if result["standard_ok"] and not result["plugged_ok"]), [],
                     "a scenario that passes as the standard edition fails with the plug")
    case.assertEqual(sorted(key for key, result in results.items() if not result["standard_ok"]), [],
                     "a scenario fails as the standard edition: the comparison is of nothing")
    # The advanced lane runs each scenario with the package's own plug as well, nothing on:
    # the core suite there is the standard edition, so this is where the real plug is held.
    real = [result for result in results.values() if "real_difference" in result]
    case.assertEqual(len(real), len(results) if neutral.advanced_lane() else 0)
    case.assertEqual({result["id"]: result["real_difference"] for result in real
                      if result["real_difference"]}, {},
                     "the advanced plug with nothing on changed what a scenario did")
    case.assertEqual(sorted(result["id"] for result in real
                            if result["standard_ok"] and not result["real_ok"]), [],
                     "a scenario that passes as the standard edition fails with the advanced plug")
    driven = [key for key, result in results.items() if result["engines"]]
    case.assertGreaterEqual(len(driven), rules["driven"], "the scenarios that build an engine are most of them")
    entries = {entry_of(key, rules["entries"]) for key in driven}
    case.assertEqual(sorted(set(rules["entries"]) - entries), [],
                     "a module, class or scenario listed in this share builds no engine in any of its scenarios")
    asked = set().union(*(set(result["asked"]) for result in results.values()))
    case.assertLessEqual({str(point) for point in rules["points"]}, asked,
                         "a point the engine asks that no scenario reached")
    # No limit on the whole run's time: a slow runner is not a failure (STALL, in neutral.py).


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
                         {Point.START_ROUTE, Point.SURFACES, Point.SUPERVISION,
                          # v0.6.19: P20, told by the watcher as a notice goes (runtime/app.py).
                          Point.NOTICE})


class NeutralPlugTests(unittest.TestCase):
    def test_a_worker_that_says_nothing_is_stopped_and_named(self):
        """One hung scenario ends its worker after the stall limit; a slow machine alone never does."""
        import subprocess
        import sys
        import time
        hang = "import sys, time\nsys.stdin.readline()\ntime.sleep(600)\n"
        with subprocess.Popen([sys.executable, "-c", hang], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            started = time.monotonic()
            line, stalled = neutral.answer(process, "a.scenario", stall=1)
            self.assertEqual((line, stalled), ("", True))
            self.assertLess(time.monotonic() - started, 30)
            self.assertIsNotNone(process.wait(timeout=30))
        prompt = "import sys\nfor line in sys.stdin:\n    print(line.strip(), flush=True)\n"
        with subprocess.Popen([sys.executable, "-c", prompt], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            self.assertEqual(neutral.answer(process, "b.scenario", stall=60), ("b.scenario\n", False))
            process.stdin.close()

    def test_no_run_has_a_deadline_for_the_whole_of_it(self):
        """The 30-minute deadline for all scenarios failed slow runners with nothing wrong (2026-09-28)."""
        from pathlib import Path
        here = Path(neutral.__file__).resolve().parent
        for name in ("neutral.py", "test_released_calls.py"):
            source = (here / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertNotIn("deadline =", source)
                self.assertIn("answer(process, test_id, stall)", source)

    def test_the_shares_are_every_scenario_exactly_once(self):
        """What the one run of every scenario was held to as a whole, held over the shares: each scenario is in
        exactly one share, each share has a module of its own that runs it, every module is named by a share (whose
        check then has it build an engine), the shares' engines add up to more than 200 and their points to every
        point the engine asks."""
        ids = neutral.scenarios()
        self.assertGreater(len(ids), 250, "the listing itself looks wrong")
        self.assertEqual([key for key in ids if share_of(key) is None], [], "scenarios no share runs")
        self.assertEqual(sorted({share_of(key) for key in ids}), list(range(1, len(SHARES) + 1)), "a share with nothing")
        entries = [entry for share in SHARES for entry in share["entries"]]
        self.assertEqual(len(entries), len(set(entries)), "an entry in two shares")
        self.assertEqual([entry for entry in entries if not any(key == entry or key.startswith(entry + ".")
                                                                for key in ids)], [], "an entry that names nothing")
        self.assertEqual(sorted(set(neutral.MODULES) - set(entries)), [], "a module no share names as a whole")
        self.assertGreater(sum(share["driven"] for share in SHARES), 200)
        self.assertEqual(frozenset().union(*(share["points"] for share in SHARES)), neutral.ENGINE_POINTS)
        modules = sorted(path.stem for path in HERE.glob(Path(__file__).stem + "_*.py"))
        self.assertEqual(modules, ["%s_%d" % (Path(__file__).stem, index) for index in range(1, len(SHARES) + 1)])
        for index, name in enumerate(modules, 1):
            with self.subTest(name):
                module = __import__(name)
                self.assertEqual(module.SHARE, index)
                self.assertEqual(list(unittest.defaultTestLoader.getTestCaseNames(module.NeutralPlugShareTests)),
                                 ["test_every_scenario_of_this_share_is_the_same_with_a_plug_that_always_defers"])


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

    def test_a_read_a_scenario_put_in_place_is_spared_only_the_keywords_a_plug_adds(self):
        seen = []

        def of_since(since):
            seen.append(since)
            return ["one"]
        read = neutral.narrowed("latest_failures", of_since)
        self.assertEqual(read(5.0, admissible=True, shapes=True), ["one"])
        with self.assertRaises(TypeError):
            read(5.0, needs_you=frozenset({"x"}))         # a keyword it never took is still an error
        self.assertEqual(seen, [5.0])
        taking = lambda since, **keywords: keywords        # noqa: E731
        self.assertIs(neutral.narrowed("latest_failures", taking), taking)
        self.assertIs(neutral.narrowed("latest", of_since), of_since)

    def test_only_a_moment_read_off_the_wall_clock_is_held_still(self):
        since, until = 1000.0, 2000.0
        self.assertEqual(neutral.steady({"at": [999.5, 1500.0, 2000.5, 1500, "1500.0"]}, since, until),
                         {"at": [999.5, neutral.WALL_CLOCK, 2000.5, 1500, "1500.0"]})


if __name__ == "__main__":
    unittest.main()
