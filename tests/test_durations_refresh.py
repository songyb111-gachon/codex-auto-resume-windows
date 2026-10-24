"""The CI parts re-deal themselves: .github/workflows/durations.yml and scripts/test_parts.py --refresh-seconds.

Until 2026-10-10 the durations the parts are dealt by were refreshed by hand, and the deal drifted: one
dev run's advanced lane took 33, 28, 15 and 62 minutes. Now every green tests run on dev offers its
seconds, and a refresh is committed when it shortens some lane's longest part by enough.

* GainRuleTests - the bounds a refresh must clear, just above and just below each.
* DealComparisonTests - the longest part under the current deal and under the fresh one, on a small
  synthetic table, and --refresh-seconds writing the table only when the rule holds.
* WorkflowShapeTests - durations.yml read as text, as the other workflow tests read workflows: its
  trigger, the success, head and self-commit guards, no force, its grants, its pins, and that what it
  greps for and runs is what the script prints and what test.yml runs.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_split_runs import declared_parts, edition_parts  # noqa: E402
from test_workflow_privilege import job, steps  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
TRAILER = "Refreshed-by: .github/workflows/durations.yml"


def _runner():
    spec = importlib.util.spec_from_file_location("test_parts_for_the_refresh", ROOT / "scripts" / "test_parts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parts = _runner()


class GainRuleTests(unittest.TestCase):
    def test_the_bounds_are_ten_percent_and_three_minutes(self):
        self.assertEqual(parts.REFRESH_FRACTION, 0.10)
        self.assertEqual(parts.REFRESH_SECONDS, 180.0)

    def test_a_long_lane_must_shrink_by_ten_percent(self):
        # 3000 s: a tenth is 300 s, more than 3 minutes, so the tenth decides.
        self.assertTrue(parts.worth_refreshing(3000.0, 2700.0))
        self.assertTrue(parts.worth_refreshing(3000.0, 2699.0))
        self.assertFalse(parts.worth_refreshing(3000.0, 2701.0))

    def test_a_short_lane_must_shrink_by_three_minutes(self):
        # 1200 s: a tenth is 120 s, less than 3 minutes, so the minutes decide.
        self.assertTrue(parts.worth_refreshing(1200.0, 1020.0))
        self.assertTrue(parts.worth_refreshing(1200.0, 1019.0))
        self.assertFalse(parts.worth_refreshing(1200.0, 1021.0))
        self.assertFalse(parts.worth_refreshing(1200.0, 1079.0), "a tenth alone is not enough")

    def test_a_longer_part_is_never_a_gain(self):
        self.assertFalse(parts.worth_refreshing(3000.0, 3000.0))
        self.assertFalse(parts.worth_refreshing(3000.0, 4000.0))


class DealComparisonTests(unittest.TestCase):
    FILES = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"]

    def test_the_longest_part_under_the_current_deal_and_under_the_fresh_one(self):
        current = {name: 1.0 for name in self.FILES}
        # The current table deals a and c together, b and d together; fresh seconds make a and c long.
        fresh = {"tests/test_a.py": 600.0, "tests/test_c.py": 600.0, "tests/test_b.py": 10.0, "tests/test_d.py": 10.0}
        self.assertEqual(parts.deal(self.FILES, 2, current), [["tests/test_a.py", "tests/test_c.py"],
                                                              ["tests/test_b.py", "tests/test_d.py"]])
        self.assertEqual(parts.lane_gain(self.FILES, 2, current, fresh), (1200.0, 610.0))

    def test_a_file_the_fresh_seconds_lack_keeps_its_figure_in_both(self):
        current = {"tests/test_a.py": 1.0, "tests/test_b.py": 1.0, "tests/test_c.py": 1.0, "tests/test_d.py": 500.0}
        fresh = {"tests/test_a.py": 600.0, "tests/test_c.py": 600.0}
        # Current deal: d, then a, b, c by name to the lighter part - [d] and [a, b, c] - so 1201 s by the
        # fresh figures, d at its 500 s. Fresh: a, c, d, b - [a, d] 1100 s and [b, c] 601 s.
        self.assertEqual(parts.lane_gain(self.FILES, 2, current, fresh), (1201.0, 1100.0))

    def test_the_same_deal_is_no_gain(self):
        current = {name: 100.0 for name in self.FILES}
        self.assertEqual(parts.lane_gain(self.FILES, 2, current, dict(current)), (200.0, 200.0))

    def seconds_folder(self, folder: Path, lane: str, seconds: dict) -> Path:
        out = folder / "downloaded" / ("seconds-%s-3.14-1" % lane) / "seconds.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"lane": lane, "parts": 2, "part": "1/2", "python": "3.14", "run": "7",
                                   "seconds": seconds}), encoding="utf-8")
        return folder / "downloaded"

    def refresh(self, fresh: dict, count: str = "2", lane: dict | None = None, every: dict | None = None):
        """--refresh-seconds of `fresh` over a table whose standard lane holds `lane` (every file at 1 s by default)
        and whose figures for every lane are `every` (the same by default)."""
        folder = self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        table = folder / "durations.json"
        lane = {name: 1.0 for name in self.FILES} if lane is None else lane
        before = {"seconds": dict(lane) if every is None else every, "lanes": {"standard": lane}}
        table.write_text(json.dumps(before), encoding="utf-8")
        said = []
        with mock.patch.object(parts, "lane_files", lambda lane: list(self.FILES)), \
                mock.patch.object(parts, "DURATIONS", table), mock.patch.object(parts, "say", said.append):
            code = parts.main(["--refresh-seconds", str(self.seconds_folder(folder, "standard", fresh)), "--parts", count])
        self.assertEqual(code, 0)
        return json.loads(table.read_text(encoding="utf-8")), before, said

    def test_enough_of_a_gain_writes_the_table(self):
        after, before, said = self.refresh({"tests/test_a.py": 600.0, "tests/test_c.py": 600.0})
        self.assertNotEqual(after, before)
        self.assertEqual(after["lanes"]["standard"]["tests/test_a.py"], 600.0)
        self.assertEqual(said[0], "lane standard: longest of 2 parts 20.0 min under the current table, "
                                  "10.0 min under the fresh one - enough")
        self.assertTrue(said[-1].startswith("written: "))

    # Figures under STALE_FACTOR from what the fresh seconds say, so only the gain is weighed.
    NEAR = {"tests/test_a.py": 400.0, "tests/test_b.py": 300.0, "tests/test_c.py": 400.0, "tests/test_d.py": 450.0}

    def test_too_little_of_a_gain_leaves_the_table_as_it_was(self):
        # 1200 s to 1100 s: under 3 minutes.
        after, before, said = self.refresh({"tests/test_a.py": 600.0, "tests/test_c.py": 600.0, "tests/test_d.py": 500.0},
                                           lane=dict(self.NEAR))
        self.assertEqual(said[0], "lane standard: longest of 2 parts 20.0 min under the current table, "
                                  "18.3 min under the fresh one")
        self.assertEqual(after, before)
        self.assertEqual(said[-1], "kept: no lane's longest part shrinks by 10% and 3 minutes, and no file is dealt by "
                                   "a figure 2 times and a minute from what it took")

    def test_a_figure_more_than_twice_off_is_written_with_no_gain(self):
        """The split files of 2026-10-23 kept their estimates: test_neutral_plug_4 was dealt by 147 s and took 421."""
        self.assertEqual((parts.STALE_FACTOR, parts.STALE_SECONDS), (2.0, 60.0))
        lane = dict(self.NEAR, **{"tests/test_d.py": 200.0})
        after, before, said = self.refresh({"tests/test_a.py": 600.0, "tests/test_b.py": 500.0, "tests/test_c.py": 600.0,
                                            "tests/test_d.py": 500.0}, lane=lane)
        self.assertNotIn("enough", said[0])
        self.assertIn("stale: lane standard: tests/test_d.py is dealt by 200 s and took 500 s", said)
        self.assertEqual(after["lanes"]["standard"]["tests/test_d.py"], 500.0)
        self.assertEqual(after["lanes"]["standard"]["tests/test_a.py"], 600.0, "the whole merge is written, not one file")
        self.assertTrue(said[-1].startswith("written: "))

    def test_twice_off_by_less_than_a_minute_is_noise(self):
        lane = dict(self.NEAR, **{"tests/test_b.py": 20.0})
        after, before, said = self.refresh({"tests/test_a.py": 600.0, "tests/test_b.py": 55.0, "tests/test_c.py": 600.0,
                                            "tests/test_d.py": 500.0}, lane=lane)
        self.assertEqual(after, before)
        self.assertFalse([line for line in said if line.startswith("stale: ")])

    def test_a_file_its_lane_never_measured_is_written_once_a_minute_off(self):
        lane = {name: value for name, value in self.NEAR.items() if name != "tests/test_d.py"}
        fresh = {"tests/test_a.py": 600.0, "tests/test_b.py": 500.0, "tests/test_c.py": 600.0}
        # Dealt by the figure for every lane, 450 s: 50 s off is kept, 70 s off is written.
        after, before, said = self.refresh(dict(fresh, **{"tests/test_d.py": 500.0}), lane=lane,
                                           every=dict(self.NEAR, **{"tests/test_d.py": 450.0}))
        self.assertEqual(after, before)
        after, before, said = self.refresh(dict(fresh, **{"tests/test_d.py": 520.0}), lane=lane,
                                           every=dict(self.NEAR, **{"tests/test_d.py": 450.0}))
        self.assertIn("stale: lane standard: tests/test_d.py is dealt by 450 s (its table has none) and took 520 s", said)
        self.assertEqual(after["lanes"]["standard"]["tests/test_d.py"], 520.0)

    def test_a_table_that_leaves_a_lane_uneven_is_refused_and_not_written(self):
        # A gain - 4000 s to 3500 s - but test_a and test_b, 3500 s, against 2010 s: past SPREAD.
        after, before, said = self.refresh({"tests/test_a.py": 2000.0, "tests/test_c.py": 2000.0,
                                            "tests/test_b.py": 1500.0, "tests/test_d.py": 10.0})
        self.assertEqual(after, before)
        self.assertIn("refused: the standard lane's 2 parts would take [3500, 2010] s, more than 1.2 times apart: "
                      "tests/test_a.py alone takes 2000 s", said)
        self.assertEqual(said[-1], "kept: the fresh table would leave a lane's parts uneven")

    def test_the_refusal_leaves_no_fresh_table_behind(self):
        self.refresh({"tests/test_a.py": 2000.0, "tests/test_c.py": 2000.0, "tests/test_b.py": 1500.0,
                      "tests/test_d.py": 10.0})
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["downloaded", "durations.json"])

    def test_each_lane_is_dealt_into_its_own_count_where_a_workflow_gives_one(self):
        """test.yml deals the standard lane into 3 parts and the advanced into 4 (2026-10-20): the refresh
        weighs each lane at its own count, and holds its fresh table to the spread at that count only."""
        self.assertEqual(parts.parse_parts("4"), 4)
        self.assertEqual(parts.parse_parts("standard=3,advanced=4,release=4"),
                         {"standard": 3, "advanced": 4, "release": 4})
        for text in ("standard=3,advanced=4", "standard=3,advanced=4,release=4,rust=2"):
            with self.subTest(text), self.assertRaises(SystemExit):
                parts.parse_parts(text)
        after, before, said = self.refresh({"tests/test_a.py": 600.0, "tests/test_c.py": 600.0},
                                           "standard=2,advanced=4,release=4")
        self.assertEqual(after["lanes"]["standard"]["tests/test_a.py"], 600.0)
        self.assertTrue(said[0].startswith("lane standard: longest of 2 parts "), said)
        after, before, said = self.refresh({"tests/test_a.py": 600.0, "tests/test_c.py": 600.0},
                                           "standard=4,advanced=2,release=2")
        self.assertTrue(said[0].startswith("lane standard: longest of 4 parts "), said)

    def test_the_spread_is_asked_of_each_lane_at_its_own_count_only(self):
        # Four files of 1 s: even in 2 parts and in 4, uneven in 3 (2 s against 1 s).
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        table = folder / "durations.json"
        table.write_text(json.dumps({"seconds": {name: 1.0 for name in DealComparisonTests.FILES}}), encoding="utf-8")
        with mock.patch.object(parts, "lane_files", lambda lane: list(DealComparisonTests.FILES)):
            self.assertEqual(parts.uneven_lanes({"standard": [2], "advanced": [4], "release": [4]}, table), [])
            self.assertEqual([line.split(" lane")[0] for line in parts.uneven_lanes([3], table)],
                             ["the standard", "the advanced", "the release"], "a list is every lane's counts")
            found = parts.uneven_lanes({"standard": [3], "advanced": [4], "release": [2]}, table)
            self.assertEqual(len(found), 1, found)
            self.assertIn("the standard lane's 3 parts", found[0])

    def test_the_tracked_table_and_a_refresh_share_one_spread_check(self):
        source = (ROOT / "tests" / "test_split_runs.py").read_text(encoding="utf-8")
        self.assertIn("parts.uneven_lanes(counts)", source)
        self.assertNotRegex(source, r"SPREAD = ")


class WorkflowShapeTests(unittest.TestCase):
    def setUp(self):
        self.source = (WORKFLOWS / "durations.yml").read_text(encoding="utf-8")
        self.measure, self.write = job(self.source, "measure"), job(self.source, "write")
        self.measure_steps, self.write_steps = steps(self.measure), steps(self.write)
        self.commit = self.write_steps["Commit to dev and test it"]

    def test_it_wakes_only_on_a_finished_tests_run_on_dev(self):
        on = self.source[self.source.index("\non:"):self.source.index("\npermissions:")]
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", on), ["workflow_run"])
        self.assertIn('workflows: ["tests"]', on)
        self.assertIn("types: [completed]", on)
        self.assertIn("branches: [dev]", on)
        self.assertIn("name: tests\n", (WORKFLOWS / "test.yml").read_text(encoding="utf-8"))

    def test_only_a_green_run_of_dev_from_here_that_is_not_its_own_refresh(self):
        guard = self.measure[self.measure.index("if: >-"):self.measure.index("runs-on:")]
        for condition in ("github.event.workflow_run.conclusion == 'success'",
                          "github.event.workflow_run.head_branch == 'dev'",
                          "github.event.workflow_run.head_repository.full_name == github.repository",
                          "!contains(github.event.workflow_run.head_commit.message, '%s')" % TRAILER):
            self.assertIn(condition, guard)
        check = self.measure_steps["Check what the run tested"]
        self.assertIn('git ls-remote "https://github.com/$GITHUB_REPOSITORY.git" refs/heads/dev', check)
        self.assertIn('if [ "$dev" != "$HEAD_SHA" ]; then', check)
        self.assertIn("grep -qx '%s'" % TRAILER, check)
        for name in ("Read the run's seconds", "Set up Python", "Weigh a new deal"):
            self.assertIn("if: steps.check.outputs.go == 'yes'", self.measure_steps[name])
        self.assertIn("needs.measure.outputs.refresh == 'yes'", self.write)

    def test_a_refused_table_is_a_warning_and_nothing_committed(self):
        weigh = self.measure_steps["Weigh a new deal"]
        self.assertIn("grep '^refused: ' \"$out/report.txt\" | sed 's/^refused: /::warning::nothing committed: /' "
                      "|| true", weigh)
        self.assertLess(weigh.index("--refresh-seconds"), weigh.index("git diff --quiet -- tests/data/durations.json"))

    def test_the_commit_it_writes_carries_the_trailer_it_stops_at(self):
        self.assertIn("\\n\\n%s' \"$RUN\"" % TRAILER, self.commit)

    def test_dev_moves_only_from_the_tested_commit_only_forward_and_once_more_at_most(self):
        first = self.commit.index('if [ "$dev" != "$HEAD_SHA" ]; then')
        self.assertLess(first, self.commit.index('commit=$(commit_on "$dev")'))
        self.assertIn('api -X PATCH "repos/$repo/git/refs/heads/dev" -f sha="$1" -F force=false', self.commit)
        self.assertEqual(self.commit.count('move "$commit"'), 2, "one move, and one retry at most")
        self.assertEqual(self.source.count("git/refs/heads/"), 1)
        for forbidden in ("git push", "--force", "force=true", '"force":true', "force: true", "-X DELETE",
                          "-X PUT", "heads/main", "heads/ko", "--ref main", "--ref ko"):
            self.assertNotIn(forbidden, self.source)

    def test_after_the_move_it_asks_for_a_tests_run_on_dev(self):
        self.assertTrue(self.commit.rstrip().endswith('"$gh" workflow run test.yml --ref dev'))
        self.assertRegex((WORKFLOWS / "test.yml").read_text(encoding="utf-8"),
                         r"(?m)^on:\n(?:  .*\n|\s*#.*\n)*  workflow_dispatch:")

    def test_nothing_at_the_top_and_exactly_these_grants(self):
        self.assertRegex(self.source, r"(?m)^permissions: \{\}\s*$")
        self.assertEqual(self.source.count("permissions:"), 3)
        grants = lambda block: re.findall(r"(?m)^      ([a-z-]+): (read|write|none)\s*$", block)  # noqa: E731
        self.assertEqual(grants(self.measure), [("contents", "read"), ("actions", "read")])
        self.assertEqual(grants(self.write), [("contents", "write"), ("actions", "write")])

    def test_the_token_is_only_where_python_never_runs(self):
        holders = {name for name, block in {**self.measure_steps, **self.write_steps}.items()
                   if "secrets.GITHUB_TOKEN" in block}
        self.assertEqual(holders, {"Read the run's seconds", "Commit to dev and test it"})
        for name in holders:
            block = {**self.measure_steps, **self.write_steps}[name]
            for code in ("python", ".py", ".ps1", "unittest", "pip install", "eval", "scripts/"):
                self.assertNotIn(code, block)
        self.assertNotIn("actions/checkout", self.write)
        self.assertNotIn("setup-python", self.write)

    def test_every_action_is_pinned_by_full_sha_and_the_checkout_keeps_no_token(self):
        uses = re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)", self.source)
        self.assertEqual(len(uses), 4)
        for ref in uses:
            self.assertRegex(ref, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
        self.assertEqual(self.source.count("persist-credentials: false"), 1)
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", self.measure)

    def test_it_is_bounded(self):
        self.assertIn("concurrency:\n  group: durations\n  cancel-in-progress: false", self.source)
        self.assertIn("timeout-minutes: 15", self.measure)
        self.assertIn("timeout-minutes: 10", self.write)
        for block in (self.measure, self.write):
            self.assertIn("github.repository == 'songyb111-gachon/codex-auto-resume-windows'", block)

    def test_it_deals_as_many_parts_as_test_yml_runs_and_runs_no_test(self):
        weigh = self.measure_steps["Weigh a new deal"]
        call = re.findall(r"python scripts/test_parts\.py (.*)", weigh)
        self.assertEqual(call, ['--refresh-seconds "$RUNNER_TEMP/seconds" --parts standard=4,advanced=6,release=5 '
                                '> "$out/report.txt"'])
        # Each lane's own count: test.yml's test job gives each edition one, and its main-tree job and
        # release.yml deal the release lane into theirs.
        tests = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
        counts = edition_parts(job(tests, "test"))
        counts["release"] = declared_parts(job(tests, "main-tree"))
        self.assertEqual(declared_parts(job((WORKFLOWS / "release.yml").read_text(encoding="utf-8"), "test")),
                         counts["release"])
        self.assertEqual(parts.parse_parts(call[0].split("--parts ")[1].split(" ")[0]), counts)

    def test_what_it_greps_for_is_what_the_script_prints(self):
        pattern = re.search(r"grep -E '([^']+)'", self.commit).group(1)
        # The script's own line, from a refresh that is enough and one that is not.
        for fresh in ({"tests/test_a.py": 600.0, "tests/test_c.py": 600.0},
                      {"tests/test_a.py": 600.0, "tests/test_c.py": 600.0, "tests/test_d.py": 500.0}):
            said = DealComparisonTests("test_the_same_deal_is_no_gain").refresh(fresh)[2]
            with self.subTest(said[0]):
                self.assertRegex(said[0], pattern)


if __name__ == "__main__":
    unittest.main()
