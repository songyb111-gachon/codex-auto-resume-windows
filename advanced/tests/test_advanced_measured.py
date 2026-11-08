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

    def test_the_re_measure_of_2026_11_08_offers_exactly_what_was_offered_before(self):
        """MSTEER2 and MTOK passed and MWAKE failed, but only the waiting capabilities are held back by a measurement: the
        two that were offered still are, and codex_retry_settings (MB2 failed) and stop_hook_continuation (M4 failed) stay
        hidden."""
        from codex_auto_resume_advanced import registry
        self.assertEqual({definition.id for definition in registry.offered(measured.MEASURED)},
                         {"open_to_send", "account_auto_switch"})

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
        turn; the turn ran once, and the goal stayed active and carried on after it, so it passed.
        2026-10-29, on codex-cli 0.165.0-alpha.1.2, the measurement session made two of issue #50's: MIMG passed (a message
        queued with a local image file showed at once as the person's own, the picture in it, and ran); MSTEER failed -
        turn/steer from the product's own app-server session was refused (-32600) for the turn the Desktop was running.
        The same evening, two more: MOPEN failed - a conversation the app did not hold, opened through its link, came to
        the front in about 7 s but was held by the app only after about 13 s, over the ten allowed; MSTEER2 failed - a
        steer over the Desktop's IPC pipe was accepted and reached the running turn once, with no new turn, and the reply
        followed it, but the app never showed the line as the person's message. That night MOPEN was made again against
        the owner's limit of thirty seconds, its load timed by the lock's holder count alone: the window came to the
        front and the app held the conversation within 2-10 s, so it passed.
        2026-10-31, on codex-cli 0.166.0-alpha.5.1, before the v0.6.20 final: MB failed again (Codex refuses the write) and
        MHK passed (plugin hooks a listed feature, Stop one of their events), both on scratch Codex homes; M4 failed - the
        probe made its own failed turn, and Codex ran a plugin's Stop hook after a completed turn but none after it.
        2026-11-01, on the same engine, MAL failed, partial: a sign-out made with `codex logout` outside the app reached the
        running app, but the `codex login` after it did not within about a minute; the app came back signed in through its
        own sign-in. 2026-11-02, the same engine: MALR passed - after that sign-out and sign-in, the product's own restart
        of Codex brought the app up signed in.
        2026-11-05, on codex-cli 0.166.0-alpha.6, the measurement session's no-hands sitting: MW, MHK, M3B and MF passed, M3
        and MB failed as before. MB2's scratch part held and waits for its live part; MGAVE and MN stayed blocked by their
        probes, MN because this account has reset credits now, so its record at zero credits stands.
        2026-11-06, the same engine: MAUTO passed - the automatic check's own commands answered on a scratch home. MB2
        failed: Codex refused thread/resume (-32600) of a conversation made under the built-in openai provider under a
        provider of our own (modelProviderMismatch). MPROFILE passed - a second saved account read on a scratch home, the
        real sign-in left as it was - and MSWAP passed by the owner's word: the app came up as the other saved account and
        back, each with no sign-in page and no other Codex engine running.
        2026-11-08, on codex-cli 0.167.0-alpha.3.2 (the app's own engine), the measurement session made the advanced
        re-measure in eight sittings, the owner having said to go on without asking and to skip passwords, credits and
        typing into an IDE. Passed again: MW, M1, M2b, M3B, M6, M6B, M7, MF, MHK, MX, MXA, MC1, MIMG (ten pictures, the
        add's answer over a megabyte read), MIPC, MOPEN, MP1-MP3, MQO, MQP, MQG, MAUTO, MPROFILE and MSWAP (the app came up
        as the other saved account and back; the other account's first start shows its welcome and onboarding questions).
        Failed again: M2 (partial - a goal set active from another server reads active in storage, but the app keeps
        showing it paused and runs no turn), M3, M4 (Codex ran a plugin's Stop hook after a completed turn, not after the
        failed one the probe made), MB, MB2, MC2 (partial - the app's automatic review answered the approval, so no wait
        showed), MSTEER, MAWS and MCLOUD (partial - the engine's help reads a cloud task's state and continues none).
        Newly passed: MSTEER2 (a steer over the Desktop's pipe appeared once inside the running turn as the person's own
        message, with no new turn), which had failed on 0.165; MTOK, its first record (token counts read from a rollout
        and Codex's own columns, read-only). Newly failed: MWAKE, its first record - the 180-second wake timer fired
        while the PC slept in Modern Standby, but the PC left standby only at a mouse move six minutes later.
        Not settled: M5 and MO came back blocked (their VS Code half needs typing in an IDE) and MN blocked (this account
        has reset credits), so their older records stay; MK stayed blocked (Codex offered no plan to read), and so did
        MGAVE (every rollout of a capacity-failed turn is gone). Not made again, each for what it needs: MA, MAL and MALR
        (a sign-out and a browser sign-in), MH (a browser sign-in on a second home), MR (a credit), MU, MANCHOR, ME and MS
        (a condition that was not there), MQ and MT (the product's own sender), M4B (M4 did not pass)."""
        passed = {m for m, (verdict, _v) in measured.MEASURED.items() if verdict == Verdict.PASS}
        failed = {m for m, (verdict, _v) in measured.MEASURED.items() if verdict == Verdict.FAIL}
        self.assertEqual(passed, {Measurement.MW, Measurement.M1, Measurement.M2B, Measurement.M5,
                                  Measurement.M6, Measurement.M7, Measurement.MA, Measurement.MH,
                                  Measurement.MP1, Measurement.MP2, Measurement.MP3, Measurement.MR,
                                  Measurement.MN, Measurement.MU, Measurement.MIPC, Measurement.MC1,
                                  Measurement.MXA, Measurement.MX, Measurement.MF, Measurement.MO,
                                  Measurement.M3B, Measurement.M6B, Measurement.MQO, Measurement.MQP,
                                  Measurement.MQG, Measurement.MANCHOR, Measurement.MIMG, Measurement.MOPEN,
                                  Measurement.MHK, Measurement.MALR, Measurement.MAUTO, Measurement.MPROFILE,
                                  Measurement.MSWAP, Measurement.MSTEER2, Measurement.MTOK})
        self.assertEqual(failed, {Measurement.M2, Measurement.M3, Measurement.M4, Measurement.MAWS,
                                  Measurement.MCLOUD, Measurement.MB, Measurement.MC2, Measurement.MSTEER,
                                  Measurement.MAL, Measurement.MB2, Measurement.MWAKE})
        by_engine = {}
        for m, (_v, version) in measured.MEASURED.items():
            by_engine.setdefault(version, set()).add(m)
        # v0.6.22: the advanced re-measure of 2026-11-08 on the app's own engine - everything it could make again, and
        # MTOK and MWAKE for the first time.
        self.assertEqual(by_engine.pop("codex-cli 0.167.0-alpha.3.2"),
                         {Measurement.M1, Measurement.M2, Measurement.M2B, Measurement.M3, Measurement.M3B,
                          Measurement.M4, Measurement.M6, Measurement.M6B, Measurement.M7, Measurement.MW,
                          Measurement.MP1, Measurement.MP2, Measurement.MP3, Measurement.MIPC, Measurement.MAWS,
                          Measurement.MCLOUD, Measurement.MC1, Measurement.MXA, Measurement.MX, Measurement.MF,
                          Measurement.MB, Measurement.MC2, Measurement.MQO, Measurement.MQP, Measurement.MQG,
                          Measurement.MIMG, Measurement.MSTEER, Measurement.MSTEER2, Measurement.MOPEN,
                          Measurement.MHK, Measurement.MAUTO, Measurement.MB2, Measurement.MPROFILE,
                          Measurement.MSWAP, Measurement.MTOK, Measurement.MWAKE})
        # What was not made again stays on the engine it was made on: M5 and MO (their re-runs came back blocked) on 0.163,
        # the five that need a sign-in, a credit or a reset on 0.162, MANCHOR on 0.165, MAL and MALR on 0.166.
        self.assertEqual(by_engine, {
            "codex-cli 0.163.0-alpha.10.2": {Measurement.M5, Measurement.MO},
            "codex-cli 0.162.0-alpha.17.2": {Measurement.MA, Measurement.MH, Measurement.MR, Measurement.MN,
                                             Measurement.MU},
            "codex-cli 0.165.0-alpha.1.2": {Measurement.MANCHOR},
            "codex-cli 0.166.0-alpha.5.1": {Measurement.MAL, Measurement.MALR}})
        self.assertEqual(set(Measurement) - passed - failed,
                         # v0.6.15-beta's own, for several conversations at once: not made yet.
                         {Measurement.MQ, Measurement.ME, Measurement.MS, Measurement.MK, Measurement.MT,
                          # v0.6.19's groundwork probe: its condition (M4 passing) is not there.
                          Measurement.M4B,
                          # v0.6.20: which code a turn kept at capacity through Codex's retries records.
                          Measurement.MGAVE})


if __name__ == "__main__":
    unittest.main()
