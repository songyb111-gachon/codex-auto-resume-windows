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
import re
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


# Where the editions page says a measurement is still open: "**Measurement MU: not settled yet**", "**MT: not made
# yet**", and the Korean page's "**측정 MU: 아직 정해지지 않음**".
OPEN_WORDS = (re.compile(r"\*\*(?:Measurements?\s+)?([A-Z][A-Z0-9]*):\s+not\s+(?:settled|made)\s+yet"),
              re.compile(r"\*\*(?:측정\s+)?([A-Z][A-Z0-9]*):\s+아직\s+(?:정해지지\s+않음|하지\s+않음)"))


class EditionsPageTests(unittest.TestCase):
    def test_the_editions_page_never_calls_a_measurement_the_table_settles_open(self):
        """MU passed on 2026-10-10, and the page went on saying "not settled yet" beside two capabilities."""
        for name in ("EDITIONS.md", "EDITIONS.ko.md"):
            path = ac.ROOT / "docs" / name
            if not path.is_file():
                continue                                    # main carries no Korean page
            text = path.read_text(encoding="utf-8")
            for pattern in OPEN_WORDS:
                for found in pattern.finditer(text):
                    try:
                        measurement = Measurement(found.group(1).lower())
                    except ValueError:
                        continue
                    with self.subTest(page=name, measurement=measurement):
                        self.assertNotIn(measurement, measured.MEASURED, "settled in measured.py, open on the page")

    def test_the_feature_matrix_cites_the_near_limit_capabilities_and_keep_it_on_turning_one_on(self):
        """v0.6.16-beta.4's usage meter, wrap-up, forced stop over the pipe, continuation after the reset, custom numbers
        and wordings, and Keep it on that turns a capability on: each with its rows and their tests, in both languages."""
        for name in ("FEATURE_MATRIX.md", "FEATURE_MATRIX.ko.md"):
            path = ac.ROOT / "docs" / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for cited in ("test_advanced_usagestop.py:StopTests", "test_advanced_usagestop.py:AfterResetTests",
                          "test_advanced_ipc.py:StopTests", "test_advanced_usage.py:MeterTests",
                          "test_advanced_usage.py:WrapUpTests", "test_advanced_wordings.py:CheckTests",
                          "test_advanced_state_v6.py:VersionSixTests", "KeepItOnTurnsItOnTests"):
                with self.subTest(page=name, cited=cited):
                    self.assertIn(cited, text)


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

    def test_the_readings_the_owner_recorded(self):
        """2026-10-10, everything made again on codex-cli 0.162.0-alpha.17.2 by the main session at the
        owner's word, the owner signing in where MA and MH needed it: MW, M1, M2b, M5 (TUI with --no-daemon,
        as the app's bundled engine runs it, and the VS Code extension), M6, M7, MA, MH and MP1-MP3 passed;
        M2 (a goal set elsewhere is not seen while the app holds the thread), M3 and M4 (no Stop-hook plugin
        yet) failed. MU was probed but waits for a 5-hour reset with no Codex use, MN needs an account with
        no reset credit (this one has some): neither is settled. 2026-10-11, the owner allowed one credit: MR
        passed - at a real limit one consume said reset, spent exactly one credit, spent none on the retry
        with its key, and the app ran a message afterwards (the usage read right after still showed the
        limit and no window changed). With none left, MN passed: both consumes said no_credit and the count
        stayed at zero. 2026-10-13, MU passed: the 5-hour window reset at 22:54 with no Codex use after it, the
        first message at 01:39 opened a new window resetting at 06:39, and its reset time stayed there.
        2026-10-16: MIPC passed (the Desktop's IPC pipe starts, adds to and interrupts a turn the app holds), MAWS
        failed (no documented shared app-server), MCLOUD failed - partial: `codex cloud` reads a task's state, nothing
        continues one. 2026-10-15 and 16, stage 4's nine: MC1 (a queued message shows at once as the person's own
        and runs), MXA (a person's /compact leaves compaction and reasoning only), MX (thread/compact/start compacts
        headless) and MF (a model at turn/start, put back by thread/settings/update and read back) passed; MB (Codex
        refuses any write under model_providers.openai), MO and MC2 (partial), M3B (an empty turn leaves no client
        id) and M6B (the sandbox helper asked for elevation) failed on 0.162.
        2026-10-17, on codex-cli 0.163.0-alpha.10.2 (app 26.1013.3656.0) the main session measured again MW, M1, M2b,
        M5, M6, M7, MP1-MP3, MIPC and stage 4's MO, M6B, MX, MF and M3B, and every one passed - MO, M6B and M3B,
        which had failed on 0.162, among them. The others stay as they were made, so on 0.163 they read as
        unmeasured; MAWS, MCLOUD and MB are as before.
        2026-10-20, on the same engine, the measurement session in one sitting with the Desktop holding none of the
        throwaway conversations (v0.6.17, issues #42 and #47): MQO passed (a continuation queued for opening with no
        marker ran once on open, as the person's own, and core's read found it by its client id) and MQP passed (two
        added at once, each in a session of its own, each queued, run and found only in its own conversation). MQG first
        failed, inconclusive - its goal ended inside its own turn - and was made again that night with a goal that takes
        many turns: on open the queued message ran first and once, then the goal carried on, a turn at a time, to its
        own end (nine turns), so it passed.
        2026-10-26, on codex-cli 0.164.0-alpha.11.1, the measurement session made M2b again (PR #53 asked): with the
        Desktop holding the throwaway conversation and its goal paused, the probe set the goal active and queued one
        turn; the turn ran once, and the goal stayed active and carried on after it, so it passed."""
        passed = {m for m, (verdict, _v) in measured.MEASURED.items() if verdict == Verdict.PASS}
        failed = {m for m, (verdict, _v) in measured.MEASURED.items() if verdict == Verdict.FAIL}
        self.assertEqual(passed, {Measurement.MW, Measurement.M1, Measurement.M2B, Measurement.M5,
                                  Measurement.M6, Measurement.M7, Measurement.MA, Measurement.MH,
                                  Measurement.MP1, Measurement.MP2, Measurement.MP3, Measurement.MR,
                                  Measurement.MN, Measurement.MU, Measurement.MIPC, Measurement.MC1,
                                  Measurement.MXA, Measurement.MX, Measurement.MF, Measurement.MO,
                                  Measurement.M3B, Measurement.M6B, Measurement.MQO, Measurement.MQP,
                                  Measurement.MQG, Measurement.MANCHOR})
        self.assertEqual(failed, {Measurement.M2, Measurement.M3, Measurement.M4, Measurement.MAWS,
                                  Measurement.MCLOUD, Measurement.MB, Measurement.MC2})
        new = "codex-cli 0.163.0-alpha.10.2"
        again = {Measurement.MW, Measurement.M1, Measurement.M5, Measurement.M6,
                 Measurement.M7, Measurement.MP1, Measurement.MP2, Measurement.MP3, Measurement.MIPC,
                 Measurement.MO, Measurement.M6B, Measurement.MX, Measurement.MF, Measurement.M3B}
        v0617 = {Measurement.MQO, Measurement.MQP, Measurement.MQG}
        self.assertEqual({m for m, (_v, version) in measured.MEASURED.items() if version == new}, again | v0617)
        self.assertTrue(all(measured.MEASURED[m][0] == Verdict.PASS for m in again | v0617))
        v0164 = {Measurement.M2B}
        self.assertEqual({m for m, (_v, version) in measured.MEASURED.items()
                          if version == "codex-cli 0.164.0-alpha.11.1"}, v0164)
        self.assertTrue(all(measured.MEASURED[m][0] == Verdict.PASS for m in v0164))
        # v0.6.20: MANCHOR, on the Codex app's bundled engine of 2026-10-29.
        self.assertEqual({m for m, (_v, version) in measured.MEASURED.items()
                          if version == "codex-cli 0.165.0-alpha.1.2"}, {Measurement.MANCHOR})
        self.assertEqual(set(Measurement) - passed - failed,
                         # v0.6.15-beta's own, for several conversations at once: not made yet.
                         {Measurement.MQ, Measurement.ME, Measurement.MS, Measurement.MK, Measurement.MT,
                          # v0.6.19's groundwork probes, made while its stage is built: not made yet.
                          Measurement.MTOK, Measurement.MOPEN, Measurement.MAL, Measurement.MWAKE, Measurement.MHK,
                          Measurement.M4B})


if __name__ == "__main__":
    unittest.main()
