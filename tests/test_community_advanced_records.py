"""A report's two optional keys, as the project reads them (build/community_report.py OPTIONAL_KEYS, v0.6.20).

`advanced_records` (codex-compat-reporter 1.5.4 on) are the records an advanced-edition feature carried by a route of
its own: held to every rule a record is, counted by the same rule into the advanced edition's own Reported counts
beside the version - and never into the verdict, a level, the standard counts or the counts a release ships
(reported.json). `credit` is a boolean and nothing else. Each test fails with its rule reverted.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import community_report as reader  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "community" / "codex-cli-0.155.0-alpha.9.2.json"
NOW = 1793500000.0


def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def raw(report) -> bytes:
    return reader.encode(report)


def refusals(report):
    return reader.inspect(raw(report), now=NOW, releases=None)[1]


class OptionalKeyTests(unittest.TestCase):
    def test_a_report_without_them_reads_as_before(self):
        self.assertEqual(refusals(sample()), [])

    def test_credit_is_a_boolean_and_nothing_else(self):
        for value in (True, False):
            self.assertEqual(refusals(dict(sample(), credit=value)), [])
        for value in ("yes", 1, None, "someone-else", {"login": "x"}):
            with self.subTest(value=value):
                self.assertIn("credit is not true or false", refusals(dict(sample(), credit=value)))
        self.assertTrue(reader.credited(dict(sample(), credit=True)))
        self.assertFalse(reader.credited(dict(sample(), credit="true")))

    def test_advanced_records_are_held_to_every_rule_a_record_is(self):
        report = sample()
        good = copy.deepcopy(report["records"][:1])
        self.assertEqual(refusals(dict(report, advanced_records=good)), [])
        bad = copy.deepcopy(good)
        bad[0]["state"] = "<script>"
        self.assertTrue(any(said.startswith("advanced_records[1].state") for said in
                            refusals(dict(report, advanced_records=bad))))
        extra = copy.deepcopy(good)
        extra[0]["note"] = "words"
        self.assertTrue(refusals(dict(report, advanced_records=extra)))
        for value in ([], "x", {"a": 1}):
            with self.subTest(value=value):
                self.assertTrue(refusals(dict(report, advanced_records=value)))
        many = [copy.deepcopy(good[0]) for _ in range(reader.MAX_RECORDS - len(report["records"]) + 1)]
        self.assertTrue(refusals(dict(report, advanced_records=many)))

    def test_any_other_key_is_still_refused(self):
        self.assertTrue(refusals(dict(sample(), login="someone")))


class CountedApartTests(unittest.TestCase):
    def setUp(self):
        self.plain = sample()
        self.carried = dict(sample(), advanced_records=copy.deepcopy(
            [record for record in sample()["records"] if record["delivered_at"]][:1]))
        self.carried["advanced_records"][0]["state"] = "recovery_turn_failed"

    def test_they_never_move_the_verdict_or_a_level(self):
        self.assertEqual(reader.recompute(self.carried)["verdict"], reader.recompute(self.plain)["verdict"])
        self.assertEqual(reader.recompute(self.carried)["capabilities"], reader.recompute(self.plain)["capabilities"])
        self.assertEqual(reader.graded(self.carried), reader.graded(self.plain))

    def test_they_are_counted_apart_in_the_index_and_the_readme(self):
        path = reader.canonical_path(self.carried["reporter"]["github_login"], self.carried["codex_version"])
        index = reader.build_index({path: self.carried}, generated_at=NOW)
        held = index["versions"][self.carried["codex_version"]]
        self.assertEqual(held["advanced"], {"reports": 1, "worked": 0, "failed": 1, "neither": 0, "both": 0})
        self.assertEqual(held["reported"], reader.build_index({path: self.plain}, generated_at=NOW)
                         ["versions"][self.carried["codex_version"]]["reported"])
        self.assertIn("### The advanced edition's own routes", reader.build_readme(index))
        plain = reader.build_index({path: self.plain}, generated_at=NOW)
        self.assertNotIn("advanced", plain["versions"][self.plain["codex_version"]])
        self.assertNotIn("advanced edition's own routes", reader.build_readme(plain))

    def test_the_counts_a_release_ships_never_see_them(self):
        path = reader.canonical_path(self.carried["reporter"]["github_login"], self.carried["codex_version"])
        self.assertEqual(reader.project(reader.build_index({path: self.carried}, generated_at=NOW)),
                         reader.project(reader.build_index({path: self.plain}, generated_at=NOW)))

    def test_the_filed_copy_keeps_them_and_the_credit_as_they_are(self):
        kept = reader.filed_copy(dict(self.carried, credit=True))
        self.assertEqual(kept["advanced_records"], self.carried["advanced_records"])
        self.assertIs(kept["credit"], True)


if __name__ == "__main__":
    unittest.main()
