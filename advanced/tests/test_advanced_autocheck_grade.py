# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The automatic check's grade: what it may say of a capability, and that it says no more than it proved.

Every rule against the shipped registry's own rows where one shows it, and a test capability where the shipped table has no
such case. A record is written the way the watcher writes it; nothing here starts a process.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_autocheck_grade.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import arming, autocheck, compatdata, registry  # noqa: E402
from codex_auto_resume_advanced.measured import MEASURED  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (TRIPWIRES, ArmingState, ArmingWarning, AutoResult, CheckGrade,  # noqa: E402
                                                   CheckReach, KEPT_NOTICES, Measurement, OffReason, Verdict)

HERE = "codex-cli 0.166.0-alpha.6"
EARLIER = "codex-cli 0.163.0-alpha.10.2"
OLDER = "codex-cli 0.162.0-alpha.17.2"
P, F, U = AutoResult.PASS, AutoResult.FAIL, AutoResult.UNKNOWN


def rows(*measurements, narrowed=()):
    return ac.definition(id="test_rows", measurements=tuple(measurements), narrowed_by=tuple(narrowed))


def view(version=HERE):
    return ac.view(version=version)


class SettledTests(unittest.TestCase):
    """The design's five rules, one each, first that holds."""

    def word(self, measurement, hand, found, version=HERE):
        return autocheck.settled(measurement, version, {measurement: hand} if hand else {},
                                 {measurement: found} if found else {})

    def test_a_person_s_fail_stands_on_any_codex_whatever_the_check_found(self):
        for found in (P, F, U, None):
            self.assertEqual(self.word(Measurement.M6, (Verdict.FAIL, EARLIER), found), autocheck.FAILED, found)
            self.assertEqual(self.word(Measurement.MHK, (Verdict.FAIL, HERE), found), autocheck.FAILED, found)

    def test_a_person_s_pass_here_outranks_a_call_gone(self):
        self.assertEqual(self.word(Measurement.M6, (Verdict.PASS, HERE), F), autocheck.HERE)

    def test_a_call_gone_shows_on_every_row_that_asks_it(self):
        self.assertEqual(self.word(Measurement.M6, (Verdict.PASS, EARLIER), F), autocheck.GONE)
        self.assertEqual(self.word(Measurement.M7, (Verdict.PASS, EARLIER), F), autocheck.GONE)
        self.assertEqual(self.word(Measurement.MT, None, F), autocheck.GONE)

    def test_a_part_pass_carries_only_a_person_s_earlier_pass(self):
        self.assertEqual(self.word(Measurement.M6, (Verdict.PASS, EARLIER), P), autocheck.STANDS_IN)
        self.assertEqual(self.word(Measurement.M6, None, P), autocheck.UNSETTLED, "nobody ever saw it work")

    def test_a_whole_pass_needs_no_person(self):
        self.assertEqual(self.word(Measurement.MHK, None, P), autocheck.STANDS_IN)

    def test_a_pass_on_a_row_that_can_only_fail_settles_nothing(self):
        self.assertEqual(self.word(Measurement.M7, (Verdict.PASS, EARLIER), P), autocheck.UNSETTLED)
        self.assertEqual(self.word(Measurement.M1, (Verdict.PASS, EARLIER), P), autocheck.UNSETTLED)

    def test_unknown_or_nothing_settles_nothing(self):
        self.assertEqual(self.word(Measurement.M6, (Verdict.PASS, EARLIER), U), autocheck.UNSETTLED)
        self.assertEqual(self.word(Measurement.M6, (Verdict.PASS, EARLIER), None), autocheck.UNSETTLED)


class WarningTests(unittest.TestCase):
    """warnings_for, as a statement and a tripwire read it."""

    def warned(self, definition, table, checked, **keywords):
        return arming.warnings_for(definition, view(), table, checked=checked, **keywords)

    def test_with_no_check_it_says_what_it_always_said(self):
        table = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.assertEqual(arming.warnings_for(rows(Measurement.M6), view(), table), (ArmingWarning.UNMEASURED,))
        self.assertEqual(self.warned(rows(Measurement.M6), table, {}), (ArmingWarning.UNMEASURED,))

    def test_an_automatic_pass_lifts_unmeasured_only_where_every_row_is_carried(self):
        table = {Measurement.MX: (Verdict.PASS, EARLIER), Measurement.MXA: (Verdict.PASS, OLDER)}
        self.assertEqual(self.warned(rows(Measurement.MX), table, {Measurement.MX: P}), ())
        self.assertEqual(self.warned(rows(Measurement.MX, Measurement.MXA), table, {Measurement.MX: P}),
                         (ArmingWarning.UNMEASURED,))

    def test_a_row_only_a_part_rests_on_counts_too(self):
        table = {Measurement.MU: (Verdict.PASS, OLDER), Measurement.MR: (Verdict.PASS, OLDER)}
        definition = rows(Measurement.MU, narrowed=(Measurement.MR,))
        self.assertEqual(self.warned(definition, table, {Measurement.MU: P}), (ArmingWarning.UNMEASURED,))
        self.assertEqual(self.warned(definition, table, {Measurement.MU: P, Measurement.MR: P}), ())

    def test_a_failed_measurement_is_never_turned_into_a_pass(self):
        table = {Measurement.M2: (Verdict.FAIL, OLDER)}
        self.assertEqual(self.warned(rows(Measurement.M2), table, {Measurement.M2: P}),
                         (ArmingWarning.MEASUREMENT_FAILED,))

    def test_a_call_gone_warns_at_once_beside_a_failed_measurement_too(self):
        table = {Measurement.M2: (Verdict.FAIL, OLDER), Measurement.M6: (Verdict.PASS, EARLIER)}
        self.assertEqual(self.warned(rows(Measurement.M6), table, {Measurement.M6: F}),
                         (ArmingWarning.AUTO_CHECK_FAILED,))
        self.assertEqual(self.warned(rows(Measurement.M2), table, {Measurement.M2: F}),
                         (ArmingWarning.MEASUREMENT_FAILED, ArmingWarning.AUTO_CHECK_FAILED))


class GradeTests(unittest.TestCase):
    def grade(self, measurements, table, results):
        return autocheck.grade(tuple(measurements), HERE, table, results)

    def test_no_measurement_is_no_grade(self):
        self.assertEqual(self.grade((), {}, {}), (CheckGrade.NONE, None))

    def test_measured_by_a_person_on_this_codex(self):
        self.assertEqual(self.grade((Measurement.M6,), {Measurement.M6: (Verdict.PASS, HERE)}, {}),
                         (CheckGrade.MEASURED, None))

    def test_checked_automatically_names_the_oldest_person_s_pass(self):
        table = {Measurement.M6: (Verdict.PASS, EARLIER), Measurement.MU: (Verdict.PASS, OLDER)}
        self.assertEqual(self.grade((Measurement.M6, Measurement.MU), table, {Measurement.M6: P, Measurement.MU: P}),
                         (CheckGrade.AUTO_CHECKED, OLDER))

    def test_a_whole_row_has_no_person_to_name(self):
        self.assertEqual(self.grade((Measurement.MHK,), {}, {Measurement.MHK: P}), (CheckGrade.AUTO_CHECKED, None))

    def test_a_mix_of_measured_and_checked_says_checked(self):
        table = {Measurement.M6: (Verdict.PASS, HERE), Measurement.MU: (Verdict.PASS, OLDER)}
        self.assertEqual(self.grade((Measurement.M6, Measurement.MU), table, {Measurement.MU: P}),
                         (CheckGrade.AUTO_CHECKED, OLDER))

    def test_still_unmeasured_says_whether_the_calls_were_at_least_there(self):
        table = {Measurement.M7: (Verdict.PASS, EARLIER), Measurement.M1: (Verdict.PASS, EARLIER)}
        self.assertEqual(self.grade((Measurement.M7,), table, {Measurement.M7: P}), (CheckGrade.OFFERED_ONLY, None))
        self.assertEqual(self.grade((Measurement.M7,), table, {}), (CheckGrade.UNMEASURED, None))
        self.assertEqual(self.grade((Measurement.M7, Measurement.M1), table, {Measurement.M7: P}),
                         (CheckGrade.UNMEASURED, None), "M1 has no check, so the calls being there does not cover it")

    def test_a_failed_record_says_what_the_check_shows_and_stays_failed(self):
        table = {Measurement.M2: (Verdict.FAIL, OLDER)}
        self.assertEqual(self.grade((Measurement.M2,), table, {Measurement.M2: P}),
                         (CheckGrade.FAILED_STILL_OFFERED, None))
        self.assertEqual(self.grade((Measurement.M2,), table, {}), (CheckGrade.FAILED, None))
        self.assertEqual(self.grade((Measurement.M2,), table, {Measurement.M2: F}), (CheckGrade.FAILED, None))

    def test_a_call_gone_is_its_own_grade(self):
        self.assertEqual(self.grade((Measurement.M7,), {Measurement.M7: (Verdict.PASS, EARLIER)}, {Measurement.M7: F}),
                         (CheckGrade.CHECK_FAILED, None))


class ShippedTests(unittest.TestCase):
    """How many capabilities it actually helps, on what the build ships: a change to this list is a change to what the
    design says plainly, so it fails here first."""

    def on_page(self):
        return [definition for definition in registry.REGISTRY if definition.measurements or definition.narrowed_by]

    def grade_all(self, results):
        version = HERE
        found = {}
        for definition in self.on_page():
            found[definition.id] = autocheck.grade(tuple(definition.measurements) + tuple(definition.narrowed_by), version,
                                                   MEASURED, results)[0]
        return found

    def every_row_passes(self):
        return {measurement: P for measurement, row in autocheck.CHECKS.items() if row.reach != CheckReach.NONE}

    def test_five_capabilities_read_compatible(self):
        graded = self.grade_all(self.every_row_passes())
        self.assertEqual({name for name, word in graded.items() if word == CheckGrade.AUTO_CHECKED},
                         {"headless_run", "model_fallback", "reset_credit", "reset_message", "usage_meter"})

    def test_what_a_call_gone_reaches(self):
        gone = {measurement: F for measurement in self.every_row_passes()}
        warned = {definition.id for definition in self.on_page()
                  if ArmingWarning.AUTO_CHECK_FAILED in arming.warnings_for(definition, view(), MEASURED, checked=gone)}
        self.assertEqual(warned, {"headless_run", "model_fallback", "reset_credit", "reset_message", "usage_meter",
                                  "marker_free_continuation", "goal_continuation", "compact_continue",
                                  "silent_continuation", "codex_chat", "account_switch", "window_anchor", "usage_pause",
                                  "usage_analytics"})

    def test_what_stays_unmeasured_or_failed_says_so(self):
        graded = self.grade_all(self.every_row_passes())
        self.assertEqual(graded["queue_for_open"], CheckGrade.UNMEASURED)
        self.assertEqual(graded["marker_free_continuation"], CheckGrade.OFFERED_ONLY)
        self.assertEqual(graded["goal_continuation"], CheckGrade.FAILED_STILL_OFFERED)
        self.assertEqual(graded["steer_send"], CheckGrade.FAILED)

    def test_it_never_lets_a_hidden_capability_out(self):
        """registry.offered reads the table it is given, and the automatic answer is never in that table."""
        before = registry.offered(MEASURED)
        table = dict(MEASURED)
        self.assertEqual(registry.offered(table), before)
        self.assertNotIn("stop_hook_continuation", {definition.id for definition in before})


class RecordCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(version=HERE, capability=ac.COMPAT)

    def found(self, **words):
        results = {name: word for name, word in words.items()}
        autocheck._write(self.paths, dict(autocheck._attempt(self.paths, ["d" * 64, 1, 2], 1, self.now), engine=HERE,
                                          checked_at=self.now, results=results,
                                          gone={name: ["thread/resume"] for name, word in words.items() if word == "fail"}))

    def armed(self, runtime, *warnings, **changes):
        result = self.arm(runtime, acknowledged_version=HERE, warnings=[str(word) for word in warnings], **changes)
        self.assertTrue(result["done"], result)


class StandingTests(RecordCase):
    """The tripwire every warning follows: no new semantics."""

    def definition(self, **changes):
        return ac.definition(**dict(dict(measurements=(Measurement.M6,)), **changes))

    def test_a_call_gone_turns_off_what_rests_on_it_with_its_own_reason(self):
        made = self.runtime(self.definition())
        self.measured = {Measurement.M6: (Verdict.PASS, HERE)}
        self.armed(made)
        self.measured = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.found(m6="fail")
        self.assertEqual(made.arming.current()["test_wake"], ArmingState.OFF)
        self.assertEqual(made.state.arming()["test_wake"]["reason"], OffReason.AUTO_CHECK_FAILED)
        self.assertIn(OffReason.AUTO_CHECK_FAILED, TRIPWIRES)

    def test_a_warning_the_person_confirmed_never_trips_it(self):
        self.measured = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.found(m6="fail")
        made = self.runtime(self.definition())
        self.armed(made, ArmingWarning.AUTO_CHECK_FAILED)
        self.assertEqual(made.arming.current()["test_wake"], ArmingState.ARMED)

    def test_kept_on_it_is_noted_instead(self):
        made = self.runtime(self.definition())
        self.measured = {Measurement.M6: (Verdict.PASS, HERE)}
        self.armed(made)
        result = made.arming.set_keep_on("test_wake", True, generation=made.state.meta()["generation"],
                                         confirmed=["keep_on"], actor="dashboard")
        self.assertTrue(result["done"], result)
        self.measured = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.found(m6="fail")
        self.assertEqual(made.arming.current()["test_wake"], ArmingState.ARMED)
        self.assertEqual(made.state.arming()["test_wake"]["reason"], OffReason.AUTO_CHECK_FAILED)
        self.assertIn(OffReason.AUTO_CHECK_FAILED, KEPT_NOTICES)

    def test_on_a_row_only_a_part_rests_on_it_warns_and_never_trips(self):
        made = self.runtime(ac.definition(narrowed_by=(Measurement.MR,)))
        self.measured = {Measurement.MR: (Verdict.PASS, HERE)}
        self.armed(made)
        self.measured = {Measurement.MR: (Verdict.PASS, EARLIER)}
        self.found(mr="fail")
        self.assertEqual(made.arming.current()["test_wake"], ArmingState.ARMED)
        self.assertIn(ArmingWarning.AUTO_CHECK_FAILED, made.arming.warnings(made.registry.get("test_wake")))

    def test_a_pass_takes_nothing_away_and_a_lost_record_only_warns_again(self):
        self.measured = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.found(m6="pass")
        made = self.runtime(self.definition())
        self.armed(made)
        self.assertEqual(made.arming.current()["test_wake"], ArmingState.ARMED)
        (self.paths.advanced_dir / autocheck.FILE).unlink()
        self.assertEqual(made.arming.warnings(made.registry.get("test_wake")), (ArmingWarning.UNMEASURED,))
        self.assertEqual(made.arming.current()["test_wake"], ArmingState.ARMED, "unmeasured was never a tripwire")

    def test_another_engine_s_record_is_no_answer(self):
        self.measured = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.found(m6="pass")
        self.compat = ac.view(version="codex-cli 0.167.0", capability=ac.COMPAT)
        made = self.runtime(self.definition())
        self.assertEqual(made.arming.warnings(made.registry.get("test_wake")), (ArmingWarning.UNMEASURED,))


class NeverAMeasurementTests(RecordCase):
    """A grade of its own: nothing that widens a route reads it."""

    def test_verdict_is_a_person_s_alone(self):
        self.measured = {Measurement.M6: (Verdict.PASS, EARLIER)}
        self.found(m6="pass")
        made = self.runtime()
        self.assertIsNone(made.arming.verdict(Measurement.M6), "a narrowed route stays narrowed until a person measures")
        self.assertEqual(made.arming.checked(), {Measurement.M6: AutoResult.PASS})

    def test_the_table_and_the_compatibility_data_do_not_hold_it(self):
        self.found(m6="pass", m7="fail")
        self.assertEqual(compatdata.table_for(self.paths, HERE), compatdata.table_for(None, HERE))
        self.assertEqual(self.paths.advanced_dir / autocheck.FILE,
                         autocheck._path(self.paths), "not in the data's own place, config/compat-advanced.json")

    def test_a_data_pass_for_this_engine_reads_as_measured(self):
        self.assertEqual(autocheck.grade((Measurement.M6,), HERE, {Measurement.M6: (Verdict.PASS, HERE)},
                                         {Measurement.M6: P}), (CheckGrade.MEASURED, None))


if __name__ == "__main__":
    unittest.main()
