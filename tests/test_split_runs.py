"""The suite in parts is the suite: scripts/test_parts.py, and the workflows that run it.

The owner asked for the suite to run in parts wherever it runs (2026-09-28), on one condition: the same
result a whole run gives. What is held here:

* DiscoveredSuiteTests - for every suite and every part count a workflow uses, the parts together are
  exactly the tests `unittest discover` finds, each once, and a part loads its files in discover's order.
  Loaded in fresh interpreters: importing every test module into this one would put other files' import
  side effects into whichever part runs this test, which is the kind of sharing the split must not have.
* DealTests - the deal is a partition, the same every time, and balanced by the recorded durations.
* LaneDurationsTests - each lane is dealt by its own seconds, then by the figure for every lane, then
  round-robin; a recorded run writes its own lane; and each lane's parts come out about even.
* WorkerTests - a real worker on a small suite records each test id's outcome as unittest reports it, and
  the whole run - `unittest discover` itself, the run the parts are compared with - records the same.
* PartTests - every suite of a part runs, and the part fails after the last if any of them failed.
* CompareTests - a part run alone is held to a whole run on its own files, and a difference in parts run
  at once names its part and the run that checks it alone.
* LaneTests - what each lane runs, and with what on the path.
* WorkflowPartsTests - test.yml and release.yml run every part of every lane, and what a lane checks
  once still runs once.
* MainTreeTests - test.yml's main-tree job runs the release's lane on dev's tree with every Korean
  source taken off, as main and the release will hold it.

The comparison of a whole run with a parallel one, test id by test id, is in CONTRIBUTING.md; it takes
as long as the suite, so it is a command rather than a test. It was made on both editions' lanes.
tests/data/durations.json holds each lane's seconds on GitHub's runners, read from CI's job logs; its
`about` names the runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import languages  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
RUNNER = ROOT / "scripts" / "test_parts.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _runner():
    spec = importlib.util.spec_from_file_location("test_parts_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parts = _runner()


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def job(source: str, name: str) -> str:
    start = re.search(r"(?m)^  %s:\s*$" % re.escape(name), source)
    if not start:
        raise AssertionError("job %s not found" % name)
    rest = source[start.end():]
    end = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", rest)
    return rest[:end.start()] if end else rest


def step(source: str, name: str) -> str:
    start = source.index("- name: %s\n" % name)
    end = source.find("\n      - name:", start)
    return source[start:] if end < 0 else source[start:end]


def declared_parts(text: str) -> int:
    """PARTS in a job, and the matrix's part list, which must be 1..PARTS."""
    listed = re.search(r"(?m)^\s*part: \[([0-9, ]+)\]\s*$", text)
    count = re.search(r'(?m)^\s*PARTS: "(\d+)"\s*$', text)
    if not (listed and count):
        raise AssertionError("no part list or no PARTS")
    numbers = [int(value) for value in listed.group(1).split(",")]
    if numbers != list(range(1, int(count.group(1)) + 1)):
        raise AssertionError("the part list %s is not 1..PARTS=%s" % (numbers, count.group(1)))
    return int(count.group(1))


def documented_counts() -> set[int]:
    """The part counts CONTRIBUTING.md tells a contributor to run on their own machine."""
    text = (ROOT / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    return {int(value) for value in re.findall(r"test_parts\.py[^\n`]*?--(?:parallel |part \d+/|parts )(\d+)", text)}


def counts_used() -> list[int]:
    """Every part count a workflow uses, every count CONTRIBUTING.md shows, and 1: the whole suite as
    one part."""
    tests = workflow("test.yml")
    return sorted({1, declared_parts(job(tests, "test")), declared_parts(job(tests, "main-tree")),
                   declared_parts(job(workflow("release.yml"), "test")),
                   declared_parts(job(workflow("sync-ko.yml"), "test"))} | documented_counts())


class DiscoveredSuiteTests(unittest.TestCase):
    def test_every_count_used_splits_every_suite_into_exactly_the_discovered_tests(self):
        counts = counts_used()
        self.assertGreater(max(counts), 1)
        self.assertTrue(documented_counts() - {1}, "the counts CONTRIBUTING.md shows are no longer read")
        done = subprocess.run([sys.executable, str(RUNNER), "--check", "--counts", ",".join(map(str, counts))],
                              cwd=str(ROOT), capture_output=True, stdin=subprocess.DEVNULL, timeout=900,
                              creationflags=NO_WINDOW)
        answer = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
        suites = {entry["suite"]: entry for entry in answer["suites"]}
        self.assertEqual(sorted(suites), ["advanced/tests", "tests"], answer)
        for suite, entry in suites.items():
            with self.subTest(suite):
                self.assertNotIn("error", entry, entry.get("error"))
                self.assertGreater(entry["tests"], 100 if suite == "tests" else 10)
                self.assertTrue(entry["unique"], "discover finds one id twice in %s" % suite)
                self.assertTrue(entry["same_order"], "the files loaded one by one are not what discover finds")
                self.assertEqual(entry["wrong"], [])
        self.assertEqual(done.returncode, 0, answer)

    def test_the_files_dealt_are_the_files_discover_imports(self):
        for suite in ("tests", "advanced/tests"):
            with self.subTest(suite):
                listed = sorted(path.name for path in (ROOT / suite).glob("test*.py"))
                self.assertEqual(parts.suite_files(suite), listed)
                self.assertIn("test_split_runs.py", parts.suite_files("tests"))


class DealTests(unittest.TestCase):
    FILES = ["tests/test_%s.py" % letter for letter in "abcdefghij"]

    def test_every_lane_in_every_count_used_is_a_partition(self):
        for lane in parts.LANES:
            files, seconds = parts.lane_files(lane), parts.load_durations(lane)
            for count in counts_used():
                with self.subTest(lane=lane, count=count):
                    dealt = parts.deal(files, count, seconds)
                    self.assertEqual(len(dealt), count)
                    self.assertTrue(all(dealt), "a part with nothing in it")
                    together = [name for part in dealt for name in part]
                    self.assertEqual(sorted(together), sorted(files))
                    self.assertEqual(len(set(together)), len(together))
                    for part in dealt:
                        self.assertEqual(part, [name for name in files if name in part], "a part out of order")

    def test_the_same_files_and_durations_deal_the_same_way(self):
        seconds = {name: float(len(name) % 7) for name in self.FILES}
        first = parts.deal(self.FILES, 3, seconds)
        again = parts.deal(list(reversed(self.FILES)), 3, dict(reversed(list(seconds.items()))))
        self.assertEqual([sorted(part) for part in first], [sorted(part) for part in again])

    def test_the_longest_go_first_to_the_part_with_least(self):
        seconds = {"tests/test_a.py": 10, "tests/test_b.py": 9, "tests/test_c.py": 2, "tests/test_d.py": 1}
        self.assertEqual(parts.deal(sorted(seconds), 2, seconds),
                         [["tests/test_a.py", "tests/test_d.py"], ["tests/test_b.py", "tests/test_c.py"]])

    def test_files_never_measured_go_round_robin_after_the_measured_ones(self):
        seconds = {"tests/test_a.py": 5}
        self.assertEqual(parts.deal(self.FILES[:5], 2, seconds),
                         [["tests/test_a.py", "tests/test_b.py", "tests/test_d.py"],
                          ["tests/test_c.py", "tests/test_e.py"]])

    def test_no_part_may_be_empty_or_count_below_one(self):
        with self.assertRaises(SystemExit):
            parts.deal(self.FILES[:2], 3, {})
        with self.assertRaises(SystemExit):
            parts.deal(self.FILES, 0, {})

    def test_the_recorded_durations_name_only_files_that_are_there(self):
        document = json.loads(parts.DURATIONS.read_text(encoding="utf-8"))
        present = {name for lane in parts.LANES for name in parts.lane_files(lane)}
        self.assertLessEqual(set(document["seconds"]), present)
        self.assertGreater(len(document["seconds"]), len(present) // 2, "most files were never measured")
        self.assertEqual(sorted(document["lanes"]), sorted(parts.LANES), "a lane with no table of its own")
        for lane, table in document["lanes"].items():
            with self.subTest(lane):
                self.assertLessEqual(set(table), set(parts.lane_files(lane)), "a file the lane does not run")
                self.assertGreater(len(table), len(parts.lane_files(lane)) // 2, "most files were never measured")
                self.assertEqual(parts.seconds_table(table), table, "an entry that is not a number of seconds")

    def test_a_part_is_read_as_k_of_n(self):
        self.assertEqual(parts.parse_part("2/8"), (2, 8))
        for wrong in ("0/4", "5/4", "2", "a/b", ""):
            with self.subTest(wrong), self.assertRaises(Exception):
                parts.parse_part(wrong)


class LaneDurationsTests(unittest.TestCase):
    """Each lane is dealt by its own seconds. One table for every lane - the medians over all of them - left
    the advanced lane's four parts 21 to 41 minutes long on GitHub's runners (dev's CI run 37056482710),
    where the standard lane's took 19 to 29: a file can take one lane far longer than another, as
    tests/test_neutral_plug.py takes 1305 s with the advanced package beside core and 841 s without it."""

    # The longest part of a lane, at most this many times its shortest. Dealt by the one table for every
    # lane, the parts today's lane tables predict are 1.21 times apart in the standard lane, 1.26 in the
    # advanced one and 1.76 in the release one; dealt by each lane's own, under 1.01 in all three.
    SPREAD = 1.2

    def durations(self, document) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name, "durations.json")
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_a_lane_takes_its_own_table_then_the_figure_for_every_lane(self):
        path = self.durations({
            "seconds": {"tests/test_a.py": 1, "tests/test_b.py": 9, "tests/test_c.py": -1},
            "lanes": {"advanced": {"tests/test_a.py": 10, "tests/test_c.py": 2, "tests/test_d.py": True,
                                   "tests/test_e.py": "5", "tests/test_f.py": -3},
                      "release": [1, 2], "nowhere": {"tests/test_a.py": 99}}})
        self.assertEqual(parts.load_durations("advanced", path),
                         {"tests/test_a.py": 10.0, "tests/test_b.py": 9.0, "tests/test_c.py": 2.0})
        for lane in ("standard", "release", None):
            with self.subTest(lane):
                self.assertEqual(parts.load_durations(lane, path), {"tests/test_a.py": 1.0, "tests/test_b.py": 9.0})
        self.assertEqual(parts.read_durations(path)[1], {"advanced": {"tests/test_a.py": 10.0, "tests/test_c.py": 2.0},
                                                         "release": {}})
        # The file of v0.6.12-alpha, with one table for every lane, is read as it was.
        self.assertEqual(parts.load_durations("advanced", self.durations({"seconds": {"tests/test_a.py": 4}})),
                         {"tests/test_a.py": 4.0})
        for wrong in ([1, 2], {"seconds": "no"}, "not json"):
            with self.subTest(wrong=wrong):
                broken = self.durations(wrong)
                if wrong == "not json":
                    broken.write_text("{", encoding="utf-8")
                self.assertEqual(parts.load_durations("advanced", broken), {})
        self.assertEqual(parts.read_durations(path.with_name("absent.json")), ({}, {}))

    def test_the_runner_deals_each_lane_by_its_own_table(self):
        """One file as long as all the rest together goes alone into part 1 of 2: a different file in each
        lane's table, and the figure for every lane where a lane has no table."""
        files = parts.lane_files("advanced")
        first, last = parts.lane_files("standard")[0], files[-1]
        self.assertEqual(set(files), set(parts.lane_files("standard")) | set(parts.lane_files("release")))
        path = self.durations({"seconds": dict({name: 1 for name in files}, **{first: 1000}),
                               "lanes": {"advanced": {last: 1000, first: 1}}})
        worker = lambda suite, names, env, verbose: (0, b"", {"ok": True, "outcomes": {}, "counts": {"run": 1}})

        class Child:
            def __init__(self, argv, **options):
                Path(argv[argv.index("--report") + 1]).write_text(
                    json.dumps({"ok": True, "outcomes": {}, "counts": {"run": 1}}), encoding="utf-8")
                self.returncode = 0

            def poll(self):
                return 0

        said = []
        with mock.patch.object(parts, "DURATIONS", path), mock.patch.object(parts, "say", said.append):
            for lane, alone in (("advanced", last), ("standard", first), ("release", first)):
                with self.subTest(lane):
                    self.assertEqual(parts.run_part(lane, 1, 2, worker=worker)["files"], [alone])
                    with mock.patch.object(parts.subprocess, "Popen", Child):
                        self.assertEqual(parts.run_parallel(lane, 2)[0]["deal"][0], [alone])
            self.assertEqual(parts.main(["--list", "--lane", "advanced", "--parts", "2"]), 0)
        self.assertIn("part 1 of 2, lane advanced: 1 files, 1000 s measured, 0 not measured", said)
        self.assertIn("  %s  1000.0 s" % last, said)

    def test_a_recorded_run_writes_its_own_lane_and_keeps_the_rest(self):
        a, b, c = parts.lane_files("standard")[:3]
        gone = "tests/test_no_such_file_any_more.py"
        path = self.durations({"seconds": {a: 1.0, gone: 5.0},
                               "lanes": {"standard": {a: 2.0, b: 3.0, gone: 4.0}, "release": {a: 7.0}}})

        def record(lane, seconds):
            merged = {"ok": True, "outcomes": {}, "counts": {"run": 1}, "seconds": seconds}
            with mock.patch.object(parts, "DURATIONS", path), mock.patch.object(parts, "say"), \
                    mock.patch.object(parts, "run_part", return_value=merged) as ran:
                self.assertEqual(parts.main(["--lane", lane, "--part", "1/4", "--record-durations"]), 0)
            self.assertEqual(ran.call_args[0][:3], (lane, 1, 4))
            return json.loads(path.read_text(encoding="utf-8"))

        # A lane with no table yet gets one; the figures for every lane take what they lacked, and keep
        # what they had; a file no lane runs is dropped from every table.
        document = record("advanced", {b: 30.04, c: 40.0})
        self.assertEqual(document["lanes"], {"advanced": {b: 30.0, c: 40.0}, "release": {a: 7.0},
                                             "standard": {a: 2.0, b: 3.0}})
        self.assertEqual(document["seconds"], {a: 1.0, b: 30.0, c: 40.0})
        self.assertIn("The advanced lane's table", document["about"])
        # A lane's table keeps the files the run did not include.
        document = record("standard", {a: 9.0})
        self.assertEqual(document["lanes"]["standard"], {a: 9.0, b: 3.0})
        self.assertEqual(document["lanes"]["advanced"], {b: 30.0, c: 40.0})
        self.assertEqual(document["seconds"], {a: 1.0, b: 30.0, c: 40.0})

    def test_each_lanes_parts_take_about_as_long_as_each_other(self):
        """At every count a workflow deals a lane into, by the lane's own seconds."""
        tests = workflow("test.yml")
        counts = sorted({declared_parts(job(tests, "test")), declared_parts(job(tests, "main-tree")),
                         declared_parts(job(workflow("release.yml"), "test")),
                         declared_parts(job(workflow("sync-ko.yml"), "test"))})
        for lane in parts.LANES:
            seconds = parts.load_durations(lane)
            for count in counts:
                with self.subTest(lane=lane, count=count):
                    totals = [sum(seconds.get(name, 0.0) for name in part)
                              for part in parts.deal(parts.lane_files(lane), count, seconds)]
                    self.assertLessEqual(max(totals), self.SPREAD * min(totals),
                                         "the %s lane's parts would take %s s" % (lane, [round(t) for t in totals]))


class WorkerTests(unittest.TestCase):
    """A real worker, on a suite made for it, records what unittest reports."""

    FILES = {
        "test_one.py": '''
import unittest

class One(unittest.TestCase):
    def test_passes(self):
        pass

    def test_fails(self):
        self.assertEqual(1, 2)

    def test_errs(self):
        raise RuntimeError("no")

    @unittest.skip("not here")
    def test_skipped(self):
        pass

    def test_a_subtest_fails(self):
        for value in (1, 2):
            with self.subTest(value=value):
                self.assertEqual(value, 1)

    @unittest.expectedFailure
    def test_expected(self):
        self.assertTrue(False)
''',
        "test_two.py": '''
import unittest

class Broken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise RuntimeError("the class cannot be set up")

    def test_never(self):
        pass
''',
        "test_three.py": "import a_module_that_is_not_there\n",
        "helper.py": "raise RuntimeError('not a test file, never imported')\n",
    }

    OUTCOMES = {
        "test_one.One.test_passes": "pass",
        "test_one.One.test_fails": "fail",
        "test_one.One.test_errs": "error",
        "test_one.One.test_skipped": "skip",
        "test_one.One.test_a_subtest_fails": "fail",
        "test_one.One.test_a_subtest_fails (value=2)": "fail",
        "test_one.One.test_expected": "expected-failure",
        "setUpClass (test_two.Broken)": "error",
        "unittest.loader._FailedTest.test_three": "error",
    }

    def run_in(self, names):
        """The worker on the suite above: its files by name, or all of it as discover finds it."""
        with tempfile.TemporaryDirectory() as folder:
            for name, text in self.FILES.items():
                Path(folder, name).write_text(text.lstrip(), encoding="utf-8")
            self.assertEqual(parts.suite_files(folder), ["test_one.py", "test_three.py", "test_two.py"])
            with mock.patch.object(parts, "write_out"):
                code, output, record = parts.run_worker(folder, parts.suite_files(folder) if names else [],
                                                        {}, False)
        self.assertEqual(code, 1, output)
        self.assertFalse(record["ok"])
        # A file's seconds are its tests' and their fixtures'; test_two's never started, and test_three is
        # the loader's stand-in for a module that could not be imported.
        self.assertEqual(sorted(record["seconds"]), ["%s/test_one.py" % folder])
        return record

    def test_the_whole_suite_is_discover_itself_and_comes_out_as_its_files_do(self):
        whole = self.run_in(names=False)
        self.assertEqual(whole["outcomes"], self.OUTCOMES)
        self.assertEqual(whole["counts"], self.run_in(names=True)["counts"])

    def test_the_whole_suite_is_run_by_unittest_main_as_python_m_unittest_runs_it(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("unittest.main(module=None, argv=list(sys.argv), testRunner=Runner, exit=False)", source)
        self.assertIn("part, count = options.part or (None, 1)", source)

    def test_the_outcomes_are_unittests(self):
        record = self.run_in(names=True)
        self.assertEqual(record["outcomes"], self.OUTCOMES)
        self.assertEqual(record["counts"], {"run": 7, "failures": 2, "errors": 3, "skipped": 1,
                                            "expected failures": 1, "unexpected successes": 0})


class PartTests(unittest.TestCase):
    def test_every_suite_runs_and_the_part_fails_after_the_last(self):
        ran = []

        def worker(suite, names, env, verbose):
            ran.append((suite, dict(env)))
            if suite == "tests":
                return 1, b"FAIL: test_x (test_a.A.test_x)\nTraceback: it broke :: here\n", \
                    {"ok": False, "outcomes": {"test_a.A.test_x": "fail"}, "counts": {"run": 1, "failures": 1}}
            return 0, b"", {"ok": True, "outcomes": {"test_b.B.test_y": "pass"}, "counts": {"run": 1}}

        said = []
        with mock.patch.object(parts, "say", said.append):
            merged = parts.run_part("advanced", 1, 1, annotate=True, worker=worker)
        self.assertEqual([suite for suite, _ in ran], ["tests", "advanced/tests"])
        self.assertFalse(merged["ok"])
        self.assertEqual(merged["outcomes"], {"test_a.A.test_x": "fail", "test_b.B.test_y": "pass"})
        self.assertEqual(merged["counts"], {"run": 2, "failures": 1})
        annotations = [line for line in said if line.startswith("::error")]
        self.assertEqual(len(annotations), 1)
        self.assertTrue(annotations[0].startswith("::error title=test suite failed (tests, part 1 of 1)::FAIL:"))
        self.assertNotIn("::", annotations[0].split("::", 2)[2], "a '::' in the text would end the command")

    def test_the_whole_lane_leaves_finding_its_files_to_discover(self):
        seen = []

        def worker(suite, names, env, verbose):
            seen.append((suite, list(names)))
            return 0, b"", {"ok": True, "outcomes": {"%s.T.test" % suite: "pass"}, "counts": {"run": 1}}

        with mock.patch.object(parts, "say"):
            merged = parts.run_part("advanced", None, 1, worker=worker)
        self.assertEqual(seen, [("tests", []), ("advanced/tests", [])])
        self.assertTrue(merged["ok"])

    def test_a_worker_that_died_fails_its_part(self):
        with mock.patch.object(parts, "say"):
            merged = parts.run_part("standard", 1, 1, worker=lambda *arguments: (3, b"", {}))
        self.assertFalse(merged["ok"])


class CompareTests(unittest.TestCase):
    """--compare holds two --outcomes files to each other test id by test id. Parts run at once on one
    machine contend with each other, so a test that differs there is checked by running its part alone and
    holding that part to the whole run - on the part's own files, the only ones it ran."""

    WHOLE = {"lane": "standard", "parts": 1, "files": ["tests/test_a.py", "tests/test_b.py"],
             "outcomes": {"test_a.A.test_x": "pass", "test_b.B.test_y": "pass", "test_b.B.test_z": "skip"}}

    def compare(self, first, second):
        said = []
        with tempfile.TemporaryDirectory() as folder:
            names = []
            for index, document in enumerate((first, second)):
                Path(folder, "%d.json" % index).write_text(json.dumps(document), encoding="utf-8")
                names.append(str(Path(folder, "%d.json" % index)))
            with mock.patch.object(parts, "say", said.append):
                code = parts.compare(*names)
        return code, said

    def test_a_part_alone_is_held_to_the_whole_run_on_its_own_files(self):
        alone = {"lane": "standard", "parts": 2, "part": "2/2", "files": ["tests/test_b.py"],
                 "outcomes": {"test_b.B.test_y": "pass", "test_b.B.test_z": "skip"}}
        code, said = self.compare(self.WHOLE, alone)
        self.assertEqual(code, 0, said)
        self.assertFalse([line for line in said if line.startswith("test_a.")], said)
        # A class whose fixture failed in the part leaves its tests absent there, and that still differs;
        # so does a file the part could not import.
        alone["outcomes"] = {"setUpClass (test_b.B)": "error", "unittest.loader._FailedTest.test_b": "error"}
        code, said = self.compare(self.WHOLE, alone)
        self.assertEqual(code, 1)
        for line in ("setUpClass (test_b.B): absent / error", "test_b.B.test_y: pass / absent",
                     "unittest.loader._FailedTest.test_b: absent / error"):
            self.assertIn(line, said)
        self.assertFalse([line for line in said if line.startswith("test_a.")], said)

    def test_runs_of_the_same_files_and_files_that_do_not_say_are_held_whole(self):
        at_once = dict(self.WHOLE, parts=2, outcomes={"test_b.B.test_y": "pass", "test_b.B.test_z": "skip"})
        self.assertIn("test_a.A.test_x: pass / absent", self.compare(self.WHOLE, at_once)[1])
        unsaid = {"outcomes": {"test_b.B.test_y": "pass"}}
        self.assertIn("test_a.A.test_x: pass / absent", self.compare(self.WHOLE, unsaid)[1])

    def test_a_difference_in_parts_run_at_once_names_its_part_and_the_run_that_checks_it(self):
        at_once = dict(self.WHOLE, parts=2, deal=[["tests/test_a.py"], ["tests/test_b.py"]],
                       outcomes={"test_a.A.test_x": "pass", "test_b.B.test_y": "fail", "test_b.B.test_z": "skip"})
        code, said = self.compare(self.WHOLE, at_once)
        self.assertEqual(code, 1)
        self.assertIn("test_b.B.test_y: pass / fail (part 2 of 2)", said)
        self.assertTrue([line for line in said if "--lane standard --part 2/2 --outcomes" in line], said)
        self.assertFalse([line for line in said if "--part 1/2" in line], said)

    def test_the_outcomes_say_which_files_the_run_ran(self):
        worker = lambda suite, names, env, verbose: (0, b"", {"ok": True, "outcomes": {}, "counts": {"run": 1}})
        with mock.patch.object(parts, "say"):
            merged = parts.run_part("release", 2, 3, worker=worker)
        dealt = parts.deal(parts.lane_files("release"), 3, parts.load_durations("release"))
        self.assertEqual(merged["files"], dealt[1])
        self.assertEqual(merged["part"], "2/3")
        with tempfile.TemporaryDirectory() as folder:
            parts.write_outcomes(str(Path(folder, "o.json")), "release", 3, merged)
            document = json.loads(Path(folder, "o.json").read_text(encoding="utf-8"))
        self.assertEqual((document["files"], document["part"]), (dealt[1], "2/3"))

    def test_parts_run_at_once_record_the_deal(self):
        class Child:
            def __init__(self, argv, **options):
                report = argv[argv.index("--report") + 1]
                Path(report).write_text(json.dumps({"ok": True, "outcomes": {}, "counts": {"run": 1}}),
                                        encoding="utf-8")
                self.returncode = 0

            def poll(self):
                return 0

        with mock.patch.object(parts.subprocess, "Popen", Child), mock.patch.object(parts, "say"):
            merged, _ = parts.run_parallel("standard", 3)
        self.assertEqual(merged["deal"], parts.deal(parts.lane_files("standard"), 3, parts.load_durations("standard")))
        self.assertEqual(merged["files"], parts.lane_files("standard"))


class LaneTests(unittest.TestCase):
    def test_each_lane_runs_its_suites_with_its_path(self):
        advanced_path = os.pathsep.join(("src", "advanced/src"))
        self.assertEqual({lane: [(suite, env["PYTHONPATH"], env["CODEX_AR_EDITION"]) for suite, env in suites]
                          for lane, suites in parts.LANES.items()}, {
            "standard": [("tests", "src", "standard")],
            "advanced": [("tests", advanced_path, "advanced"), ("advanced/tests", advanced_path, "advanced")],
            "release": [("tests", "src", "standard"), ("advanced/tests", advanced_path, "advanced")],
        })

    def test_the_runner_starts_every_child_with_no_window_and_never_pythonw(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertEqual(source.count("subprocess.Popen(") + source.count("subprocess.run("),
                         source.count("creationflags=NO_WINDOW"))
        with mock.patch.object(parts.sys, "executable", r"C:\Python\pythonw.exe"), \
                mock.patch.object(parts.Path, "is_file", return_value=True):
            self.assertEqual(Path(parts.interpreter()).name, "python.exe")

    def test_each_part_of_a_parallel_run_has_its_own_temporary_directory(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("env = dict(os.environ, TEMP=str(folder), TMP=str(folder))", source)


class WorkflowPartsTests(unittest.TestCase):
    def setUp(self):
        self.tests = job(workflow("test.yml"), "test")
        self.matrix = self.tests[self.tests.index("\n    strategy:"):self.tests.index("\n    steps:")]

    def test_every_lane_runs_in_parts_and_each_part_names_its_lane(self):
        count = declared_parts(self.tests)
        self.assertGreater(count, 1)
        run = step(self.tests, "Run the automated test suite")
        self.assertIn('run: python scripts/test_parts.py --lane $env:CODEX_AR_EDITION --part "$env:PART/$env:PARTS"'
                      " -v --annotate", run)
        self.assertIn("PART: ${{ matrix.part }}", run)
        self.assertIn("fail-fast: false", self.matrix)

    def test_the_future_python_runs_every_part_of_each_edition(self):
        include = self.matrix[self.matrix.index("include:"):]
        entries = re.findall(r'(?m)^          - \{python-version: "([\d.]+)", experimental: true, '
                             r'edition: (\w+), part: (\d+)\}\s*$', include)
        self.assertEqual(len(entries), len(re.findall(r"(?m)^          - ", include)), "an entry of another shape")
        self.assertEqual(len({python for python, _, _ in entries}), 1)
        editions = re.search(r"(?m)^        edition: \[([^\]]+)\]\s*$", self.matrix).group(1)
        expected = {(edition.strip(), str(part)) for edition in editions.split(",")
                    for part in range(1, declared_parts(self.tests) + 1)}
        self.assertEqual(sorted((edition, part) for _, edition, part in entries), sorted(expected))

    def test_what_a_lane_checks_once_runs_in_its_first_part_only(self):
        for name in ("Compile all sources", "CLI smoke test in an isolated home"):
            with self.subTest(name):
                self.assertIn("if: matrix.part == 1", step(self.tests, name))
        self.assertEqual(self.tests.count("if: matrix.part == 1"), 2)
        self.assertEqual(len(re.findall(r"(?m)^\s+if:", self.tests)), 2, "no other step is left out of a part")

    def test_the_release_builds_only_after_every_part_passed(self):
        release = workflow("release.yml")
        test, build = job(release, "test"), job(release, "build")
        self.assertGreater(declared_parts(test), 1)
        self.assertIn('run: python scripts/test_parts.py --lane release --part "$env:PART/$env:PARTS" -v --annotate',
                      test)
        self.assertIn("fail-fast: false", test)
        self.assertRegex(build, r"(?m)^    needs: test\s*$")
        self.assertNotIn("unittest", build, "the suite runs in the test job, once")
        self.assertNotIn("test_parts.py", build)
        self.assertLess(release.index("\n  test:"), release.index("\n  build:"))

    def test_the_ko_sync_splits_with_the_runner_when_the_commit_has_it(self):
        test = job(workflow("sync-ko.yml"), "test")
        self.assertGreater(declared_parts(test), 1)
        self.assertIn('if [ -f scripts/test_parts.py ]; then\n'
                      '            exec python scripts/test_parts.py --lane standard --part "$PART/$PARTS"\n'
                      '          fi', test)


class MainTreeTests(unittest.TestCase):
    """dev holds every document in English and Korean, and a promotion deletes every *.ko.md before main
    and the release see the tree (scripts/promote.py). A test that read a Korean source without asking
    tests/languages.py whether this checkout holds one passed dev's CI and failed main's and the release
    on 2026-10-02. test.yml's main-tree job runs the release's lane on dev's tree with the Korean taken
    off, and tells the branch check which tree it is."""

    STRIP = "Take every Korean source off, as a promotion to main does"
    SUITE = "Run the release lane on main's tree, this part"

    def setUp(self):
        self.source = workflow("test.yml")
        self.main = job(self.source, "main-tree")
        self.release = job(workflow("release.yml"), "test")

    def test_it_is_the_releases_lane_in_the_releases_parts_on_the_releases_python(self):
        self.assertEqual(declared_parts(self.main), declared_parts(self.release))
        pinned = r'python-version: "(3\.\d+)"'
        self.assertEqual(re.findall(pinned, self.main), re.findall(pinned, self.release))
        suite = step(self.main, self.SUITE)
        self.assertIn('run: python scripts/test_parts.py --lane release --part "$env:PART/$env:PARTS" -v --annotate',
                      suite)
        self.assertIn("PART: ${{ matrix.part }}", suite)
        self.assertIn("fail-fast: false", self.main)
        self.assertNotIn("continue-on-error", self.main, "a Korean read on main must fail the run")

    def test_it_takes_every_korean_source_off_the_index_before_the_suite_runs(self):
        strip = step(self.main, self.STRIP)
        self.assertIn("git rm -q --ignore-unmatch -- '*.ko.md'", strip)
        self.assertIn("test -z \"$(git ls-files -- '*.ko.md')\"", strip)
        self.assertLess(self.main.index("- name: " + self.STRIP), self.main.index("- name: " + self.SUITE))

    def test_the_pathspec_takes_off_what_a_promotion_takes_off(self):
        """scripts/promote.py deletes every tracked path ending in .ko.md, at any depth; the job's pathspec
        must name the same files, README.ko.md at the root among them."""
        def listed(*pathspec):
            done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *pathspec],
                                  capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
            return sorted(name for name in done.stdout.decode("utf-8").split("\0") if name)
        korean = listed("*.ko.md")
        self.assertEqual(korean, [name for name in listed() if name.endswith(".ko.md")])
        if languages.both_languages():
            for name in ("README.ko.md", "docs/GUIDE.ko.md"):
                self.assertIn(name, korean)

    def test_the_suite_is_told_the_tree_is_mains_and_only_there(self):
        self.assertIn("%s: main" % languages.TREE, step(self.main, self.SUITE))
        self.assertEqual(languages.RULES["main"], "english")
        self.assertNotIn(languages.TREE, job(self.source, "test"))

    def test_it_runs_wherever_the_tree_is_not_already_mains(self):
        self.assertRegex(self.main, r"(?m)^    if: github\.ref != 'refs/heads/main' && github\.base_ref != 'main'\s*$")
        self.assertEqual(len(re.findall(r"(?m)^\s+if:", self.main)), 1, "every step runs in every part")


if __name__ == "__main__":
    unittest.main()
