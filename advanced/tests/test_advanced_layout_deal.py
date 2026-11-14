"""The Advanced page's layout audits dealt over the five layout modules by what each costs (pagecase.layout_deal).

Until v0.6.17 the languages were dealt round: the module that drew Japanese took 43 minutes on GitHub's runners, the one
that drew English under one. v0.6.17 filled each module to the time of its longest audit, on the model that a module's
four processes run side by side. tests/data/durations.json (advanced lane, 22 languages) measured otherwise: 71 audits
of about ten seconds took 777 s in one module while one such audit alone takes 10 s, so a module takes about the SUM of
its audits. The deal now balances the sums: longest audit first, each to the module with the least summed cost so far
(the canary's cost counted in its module from the start). The costs (pagecase.AUDIT_COST) make the five modules' sums
620.5, 610, 610, 610 and 610 seconds, where the fill-to-the-longest deal gave about 1344, 1328, 42, 42 and 304. This
holds the deal to its rules without compiling anything:

* every language at every scaling is audited exactly once over the five modules, each module audits something, and each
  module runs exactly its share (LayoutTests.JOBS); the canary is in one module, the one CANARY_MODULE names;
* no module's summed cost is over the mean of the modules' sums plus the costliest single audit, and the longest module
  is under 0.8 times the longest module of the round deal (the languages dealt round, as before v0.6.17);
* inside a module deal_out gives the longest first to the share with the least, equal costs round as before, and probe()
  shares its jobs out that way; no Japanese audit shares a process with another.

Not a GUI test: it reads the deal and the five modules' classes, and runs no window (probe's processes are stood in for).
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pagecase  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402


def wall(costs: list) -> float:
    """How long a module of audits of these costs takes when its processes share one desktop: the sum of its audits
    (the measured model; see pagecase.AUDIT_COST)."""
    return sum(costs)


def module_costs(module: int) -> list:
    costs = [pagecase.audit_cost(locale) for locale, _ in pagecase.layout_jobs(module)]
    if module == pagecase.CANARY_MODULE:
        costs.append(pagecase.OTHER_AUDIT_COST)
    return costs


class DealTests(unittest.TestCase):
    def test_every_language_at_every_scaling_is_audited_exactly_once(self):
        dealt = [job for module in range(1, pagecase.LAYOUT_MODULES + 1) for job in pagecase.layout_jobs(module)]
        everything = [(str(locale), scale) for locale in l10n.LOCALES for scale in pagecase.SCALES]
        self.assertEqual(sorted(dealt), sorted(everything))
        self.assertEqual(len(dealt), len(set(dealt)))

    def test_every_module_audits_something(self):
        for module in range(1, pagecase.LAYOUT_MODULES + 1):
            with self.subTest(module=module):
                self.assertTrue(pagecase.layout_jobs(module))

    def test_each_module_runs_exactly_its_share_and_one_runs_the_canary(self):
        canaries = []
        for module in range(1, pagecase.LAYOUT_MODULES + 1):
            tests = importlib.import_module("test_advanced_page_layout_%d" % module).LayoutTests
            with self.subTest(module=module):
                self.assertEqual(tests.JOBS, pagecase.layout_jobs(module))
            if tests.CANARY:
                canaries.append(module)
        self.assertEqual(canaries, [pagecase.CANARY_MODULE])

    def test_the_deal_is_the_same_every_time(self):
        before = pagecase.layout_deal()
        pagecase.layout_deal.cache_clear()
        self.assertEqual(pagecase.layout_deal(), before)

    def test_no_module_sums_more_than_the_mean_plus_the_costliest_audit(self):
        """A module takes about the sum of its audits (measured: 71 audits of ~10 s took 777 s in one module), so no
        module's summed cost is over the mean module sum plus the costliest audit - the most an uneven last audit can add."""
        sums = [wall(module_costs(module)) for module in range(1, pagecase.LAYOUT_MODULES + 1)]
        costliest = max(pagecase.audit_cost(locale) for locale in l10n.LOCALES)
        for module, total in enumerate(sums, 1):
            with self.subTest(module=module):
                self.assertLessEqual(total, sum(sums) / len(sums) + costliest)

    def test_the_longest_module_is_under_four_fifths_of_the_round_deals_longest(self):
        """The longest module's summed cost is under 0.8 times the longest module's sum of the deal until v0.6.17: the
        languages round, each at every scaling, the canary in the last (measured: a module takes about the sum of its
        audits, tests/data/durations.json, advanced lane)."""
        dealt = max(wall(module_costs(module)) for module in range(1, pagecase.LAYOUT_MODULES + 1))
        locales = [str(locale) for locale in l10n.LOCALES]
        round_deal = []
        for module in range(1, pagecase.LAYOUT_MODULES + 1):
            costs = [pagecase.audit_cost(locale) for locale in locales[module - 1::pagecase.LAYOUT_MODULES]
                     for _ in pagecase.SCALES]
            if module == pagecase.LAYOUT_MODULES:
                costs.append(pagecase.OTHER_AUDIT_COST)
            round_deal.append(wall(costs))
        self.assertLess(dealt, max(round_deal) * 0.8)

    def test_the_modules_sums_are_the_ones_written_down(self):
        sums = [wall(module_costs(module)) for module in range(1, pagecase.LAYOUT_MODULES + 1)]
        self.assertEqual(sums, [620.5, 610.0, 610.0, 610.0, 610.0])

    def test_japanese_is_never_two_audits_in_one_process(self):
        for module in range(1, pagecase.LAYOUT_MODULES + 1):
            costs = module_costs(module)
            for share in pagecase.deal_out(costs, pagecase.LAYOUT_WORKERS):
                with self.subTest(module=module):
                    self.assertLessEqual(sum(1 for index in share if costs[index] == pagecase.audit_cost("ja")), 1)


class DealOutTests(unittest.TestCase):
    def test_the_longest_go_first_to_the_share_with_least(self):
        self.assertEqual(pagecase.deal_out([10, 1270, 10, 1270, 420, 10], 2), [[1, 4], [0, 2, 3, 5]])

    def test_equal_costs_deal_round_as_before(self):
        self.assertEqual(pagecase.deal_out([1] * 6, 4), [[0, 4], [1, 5], [2], [3]])

    def test_the_allowance_follows_the_share_not_the_count(self):
        each = pagecase.AUDIT_SECONDS * pagecase.audited_views()
        self.assertEqual(pagecase.audit_timeout([10] * 8, 4), 2 * each)
        self.assertEqual(pagecase.audit_timeout([pagecase.audit_cost("ja")] * 4, 4),
                         max(each, 3 * pagecase.audit_cost("ja")))

    def test_probe_shares_its_jobs_out_longest_first(self):
        jobs = [{"kind": "audit", "name": name, "cost": cost}
                for name, cost in (("en", 10), ("ja", 1270), ("de", 10), ("ja2", 1270), ("zh", 320))]

        class Exited:
            def __init__(self, *args, **kwargs):
                self.returncode, self.args = 1, args

            def communicate(self, timeout=None):
                return b"", b""

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(pagecase.subprocess, "Popen", Exited):
            work = Path(folder)
            pagecase.probe(work, work / "none.exe", jobs, timeout=1, workers=2)
            shares = [[job["name"] for job in json.loads((work / ("jobs-%d.json" % index)).read_text(encoding="utf-8"))]
                      for index in range(2)]
        self.assertEqual(shares, [["ja", "zh"], ["en", "de", "ja2"]])


if __name__ == "__main__":
    unittest.main()
