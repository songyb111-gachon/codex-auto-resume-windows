"""What a release knows of the measurements (measured.py) is what the records beside it say.

The records are the source tree's docs/evidence/live/measurement-*.json; an installed copy has
only the table. A record re-measured - a blocked probe completed, a fail measured again as a
pass, a new Codex - fails here until the table follows it, so a statement never warns of what
the evidence no longer says, nor stays quiet about what it does.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import evidence, measured  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict  # noqa: E402

RECORDS = ac.ROOT / "docs" / "evidence" / "live"


def record(verdict, completion=None, **changes) -> dict:
    made = {"format": evidence.MEASUREMENT_FORMAT, "step": "m2", "verdict": verdict,
            "codex_version": "codex-cli 0.158.0-alpha.2.1"}
    if completion is not None:
        made["completion"] = {"verdict": completion, "note": "as_expected", "recorded_at": "x"}
    made.update(changes)
    return made


class OutcomeTests(unittest.TestCase):
    def test_a_pass_or_a_fail_is_what_it_says_and_a_completion_settles_a_blocked_probe(self):
        version = "codex-cli 0.158.0-alpha.2.1"
        self.assertEqual(evidence.outcome(record("pass")), (Verdict.PASS, version))
        self.assertEqual(evidence.outcome(record("fail")), (Verdict.FAIL, version))
        self.assertEqual(evidence.outcome(record("blocked", "pass")), (Verdict.PASS, version))
        self.assertEqual(evidence.outcome(record("blocked", "fail")), (Verdict.FAIL, version))

    def test_what_settles_nothing_is_no_verdict_never_a_pass(self):
        for found in (record("blocked"), record("blocked", "blocked"), record("maybe"),
                      record("pass", format="codex-auto-resume-live/1"), record("pass", codex_version=None),
                      "pass", None, []):
            with self.subTest(found=found):
                self.assertIsNone(evidence.outcome(found))

    def test_a_completion_beside_a_pass_or_a_fail_does_not_change_it(self):
        """Only a blocked probe is completed by hand (evidence.complete refuses the rest)."""
        self.assertEqual(evidence.outcome(record("fail", "pass"))[0], Verdict.FAIL)


class TableTests(unittest.TestCase):
    def test_the_table_is_what_the_records_settle(self):
        if not RECORDS.is_dir():
            self.skipTest("the records are the source tree's, and this is not one")
        found = {}
        for path in sorted(RECORDS.glob("measurement-*.json")):
            settled = evidence.outcome(json.loads(path.read_text(encoding="utf-8")))
            if settled is not None:
                found[Measurement(path.stem.split("-", 1)[1])] = settled
        self.assertTrue(found, "no settled measurement read; the records moved")
        self.assertEqual(measured.MEASURED, found)

    def test_every_entry_is_a_measurement_a_pass_or_a_fail_and_a_version(self):
        for measurement, entry in measured.MEASURED.items():
            with self.subTest(measurement):
                self.assertIsInstance(measurement, Measurement)
                verdict, version = entry
                self.assertIn(verdict, (Verdict.PASS, Verdict.FAIL))
                self.assertTrue(isinstance(version, str) and version)

    def test_the_2026_09_26_readings_the_owner_recorded(self):
        """MW, M1, M6 and M7 passed; M2, M3, M4 and M5 failed; MH and MA were never completed; and
        M2b, added on 2026-09-28 for the goal continuation, has not been run yet."""
        passed = {m for m, (verdict, _v) in measured.MEASURED.items() if verdict == Verdict.PASS}
        failed = {m for m, (verdict, _v) in measured.MEASURED.items() if verdict == Verdict.FAIL}
        self.assertEqual(passed, {Measurement.MW, Measurement.M1, Measurement.M6, Measurement.M7})
        self.assertEqual(failed, {Measurement.M2, Measurement.M3, Measurement.M4, Measurement.M5})
        self.assertEqual(set(Measurement) - passed - failed,
                         {Measurement.MH, Measurement.MA, Measurement.M2B})


if __name__ == "__main__":
    unittest.main()
