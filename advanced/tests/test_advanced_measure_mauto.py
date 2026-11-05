# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""MAUTO: the automatic check's commands, on the real engine, as a probe the measurement session runs with no hands.

Nothing here runs a real codex.exe: the check's commands go to a stand-in, as test_advanced_autocheck's do, and the probe's
hand is a test's. What is held: it asks exactly what the check asks, says which half failed where the schema's command does
not answer, and its record passes the evidence writer with no path or word of Codex's in it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_measure_mauto.py
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401  (the paths)
from codex_auto_resume.codex import transport  # noqa: E402
from codex_auto_resume_advanced import autocheck, evidence, measure  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.measured import MEASURED  # noqa: E402
from codex_auto_resume_advanced.vocabulary import AutoResult, CheckReach, Measurement, Verdict  # noqa: E402

SCHEMA = json.loads((Path(__file__).resolve().parent / "data" / "autocheck_schema.json").read_text(encoding="utf-8"))
VERSION = "codex-cli 0.199.0"                 # a Codex no one has measured, whatever this build's table holds
SECRET = "PRIVATE-WORDS-5c1e"
PASSING = {"official": True, "engine_accepted": True, "version": VERSION, "schema_answered": True,
           "experimental_taken": True, "schema_written": True, "schema_whole": True, "features_answered": True,
           "options_without_flag": None, "flag_without_options": None, "scratch_home_files": 0,
           "scratch_home_signed_in": False}


def every_row(word="pass"):
    return {str(measurement): word for measurement, row in autocheck.CHECKS.items() if row.reach != CheckReach.NONE}


class Engine:
    """Stands in for `subprocess.run`: the schema's command answers unless `refuses` says of its argv that it does not."""

    def __init__(self, refuses=lambda argv: False, features=True):
        self.refuses, self.features = refuses, features
        self.calls = []

    def __call__(self, argv, **keywords):
        self.calls.append(list(argv))
        code, printed = 0, ""
        if "generate-json-schema" in argv:
            if self.refuses(argv):
                code = 2
            else:
                (Path(argv[argv.index("--out") + 1]) / autocheck.SCHEMA_FILE).write_text(json.dumps(SCHEMA), encoding="utf-8")
        elif "features" in argv:
            code = 0 if self.features else 1
            printed = "plugin_hooks removed false " + SECRET + "\n"
        return subprocess.CompletedProcess(argv, code, printed, SECRET)


def accepted(backend):
    backend.engine_version = VERSION
    return True


class ProbeEngineTests(unittest.TestCase):
    def setUp(self):
        self.where = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.where, ignore_errors=True))
        self.exe = self.where / "codex.exe"
        self.exe.write_bytes(b"not really")

    def probe(self, engine, compatible=accepted, official=True):
        with mock.patch.object(autocheck.subprocess, "run", engine), \
                mock.patch.object(transport.Backend, "_compatible", compatible), \
                mock.patch("codex_auto_resume.codex.pairing.official_engine", lambda path: (official, "x")):
            return autocheck.probe_engine(self.exe)

    def test_it_asks_exactly_what_the_check_asks_and_says_each_answered(self):
        engine = Engine()
        found = self.probe(engine)
        self.assertTrue(found["official"] and found["engine_accepted"] and found["experimental_taken"]
                        and found["schema_written"] and found["schema_whole"] and found["features_answered"])
        self.assertEqual(found["version"], VERSION)
        self.assertEqual(set(found["results"]), set(every_row()))
        self.assertEqual(set(found["results"].values()), {"pass"})
        self.assertEqual(len(engine.calls), 2, "the check's two: core's engine check is stubbed here")
        options = transport.Backend(self.where, self.exe)._argv()[1:]
        self.assertEqual(engine.calls[0][1:len(options) + 1], options, "behind core's -c options")
        self.assertIn("--experimental", engine.calls[0])
        self.assertIsNone(found["options_without_flag"], "asked only where the check's own form did not answer")

    def test_where_the_flag_is_refused_it_says_that_half(self):
        found = self.probe(Engine(refuses=lambda argv: "--experimental" in argv))
        self.assertFalse(found["experimental_taken"])
        self.assertFalse(found["schema_whole"])
        self.assertIs(found["options_without_flag"], True)
        self.assertIs(found["flag_without_options"], False)

    def test_where_the_options_are_refused_it_says_that_half(self):
        found = self.probe(Engine(refuses=lambda argv: "-c" in argv))
        self.assertFalse(found["experimental_taken"])
        self.assertIs(found["options_without_flag"], False)
        self.assertIs(found["flag_without_options"], True)

    def test_an_engine_it_cannot_run_is_said_and_nothing_raises(self):
        def refused(_backend):
            raise RuntimeError("no")

        engine = Engine()
        found = self.probe(engine, refused, official=False)
        self.assertFalse(found["engine_accepted"])
        self.assertFalse(found["official"])
        self.assertEqual(engine.calls, [])

    def test_the_scratch_home_is_counted_and_gone_and_the_watcher_s_record_is_not_written(self):
        homes = []

        def compatible(backend):
            homes.append(backend.codex_home)
            (backend.codex_home / "left-by-codex.txt").write_text("x", encoding="utf-8")
            return accepted(backend)

        with mock.patch.object(autocheck, "_write", side_effect=AssertionError("the watcher's own record")):
            found = self.probe(Engine(), compatible)
        self.assertEqual(found["scratch_home_files"], 1)
        self.assertIs(found["scratch_home_signed_in"], False)
        self.assertFalse(homes[0].parent.exists())

    def test_it_carries_no_path_or_word_of_codex(self):
        text = json.dumps(self.probe(Engine()))
        self.assertNotIn(SECRET, text)
        self.assertNotIn(str(self.where), text)
        self.assertNotIn("car-mauto", text)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.directory, ignore_errors=True))

    def run_it(self, answered):
        versions = {"product_version": "0.6.22", "codex_version": VERSION, "windows_build": "10.0.26300"}
        return measure.run(Measurement.MAUTO, versions=versions, directory=self.directory,
                           hands={"auto_check": lambda: answered})

    def test_it_is_declared_and_opens_no_session(self):
        self.assertEqual(protocol.MEASUREMENT_METHODS[Measurement.MAUTO], ())
        self.assertIs(measure.PROBES[Measurement.MAUTO], measure._mauto)
        self.assertEqual(autocheck.CHECKS[Measurement.MAUTO].reach, CheckReach.NONE)
        self.assertNotIn(Measurement.MAUTO, MEASURED)

    def test_no_capability_rests_on_it(self):
        from codex_auto_resume_advanced import registry
        for definition in registry.DEFINITIONS + tuple(item[0] for item in registry.WAITING):
            self.assertNotIn(Measurement.MAUTO, tuple(definition.measurements) + tuple(definition.narrowed_by))

    def test_a_pass_records_every_answer_and_a_grade_for_every_capability(self):
        made = self.run_it(dict(PASSING, results=every_row()))
        self.assertEqual(made["verdict"], str(Verdict.PASS))
        observed = made["observed"]
        self.assertIs(observed["experimental_taken"], True)
        self.assertEqual(observed["result_m6"], "pass")
        self.assertEqual(observed["grade_headless_run"], "auto_checked")
        self.assertEqual(observed["grade_model_fallback"], "auto_checked")
        self.assertEqual(observed["grade_queue_for_open"], "unmeasured")
        self.assertEqual(observed["grade_goal_continuation"], "failed_still_offered")
        self.assertEqual(observed["grade_stop_hook_continuation"], "failed_still_offered")
        self.assertIn("grade_account_auto_switch", observed, "hidden ones too")

    def test_the_record_is_written_and_holds_no_path_or_text(self):
        answered = dict(PASSING, results=every_row(), version="C:\\Users\\ExampleUser\\" + SECRET)
        made = self.run_it(answered)
        written = Path(made["recorded"]).read_text(encoding="utf-8")
        record = json.loads(written)
        self.assertEqual(record["format"], evidence.MEASUREMENT_FORMAT)
        self.assertNotIn(SECRET, written)
        self.assertNotIn("ExampleUser", written)
        self.assertNotIn("version\": \"C:", written)
        self.assertEqual(evidence.outcome(record)[0], Verdict.PASS)

    def test_a_row_the_check_finds_gone_is_the_check_s_finding_not_this_probe_s_fail(self):
        made = self.run_it(dict(PASSING, results=dict(every_row(), m7="fail")))
        self.assertEqual(made["verdict"], str(Verdict.PASS))
        self.assertEqual(made["observed"]["result_m7"], str(AutoResult.FAIL))
        self.assertEqual(made["observed"]["grade_marker_free_continuation"], "check_failed")

    def test_the_flag_refused_is_a_fail_that_says_the_check_gives_no_answer(self):
        made = self.run_it(dict(PASSING, schema_answered=False, experimental_taken=False, schema_written=False,
                                schema_whole=False, features_answered=False, options_without_flag=True,
                                flag_without_options=False, results={}))
        self.assertEqual(made["verdict"], str(Verdict.FAIL))
        self.assertIs(made["observed"]["options_without_flag"], True)
        self.assertEqual(made["observed"]["grade_headless_run"], "unmeasured", "no answer is the old warning")

    def test_the_features_not_answering_is_a_fail(self):
        made = self.run_it(dict(PASSING, features_answered=False, results=dict(every_row(), mhk="unknown")))
        self.assertEqual(made["verdict"], str(Verdict.FAIL))

    def test_no_engine_at_all_is_blocked_never_a_verdict(self):
        made = self.run_it({"official": False, "engine_accepted": False, "results": {}})
        self.assertEqual(made["verdict"], str(Verdict.BLOCKED))

    def test_a_word_or_an_id_outside_the_closed_lists_never_reaches_the_record(self):
        made = self.run_it(dict(PASSING, scratch_home_files="many", official=SECRET,
                                results=dict(every_row(), m6=SECRET, nothing="pass")))
        written = Path(made["recorded"]).read_text(encoding="utf-8")
        self.assertNotIn(SECRET, written)
        self.assertNotIn("result_nothing", written)
        self.assertIsNone(made["observed"]["official"])
        self.assertIsNone(made["observed"]["scratch_home_files"])


if __name__ == "__main__":
    unittest.main()
