# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The automatic compatibility check: what it asks of a Codex, what it starts, when, and that a reader starts nothing.

No test runs a real codex.exe. `subprocess.run` is a stand-in that writes the schema's file where a real engine would, and
the schema is data/autocheck_schema.json: codex-cli 0.166.0-alpha.5.1's own document, cut down to what the check reads.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_autocheck.py
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.codex import transport  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import autocheck  # noqa: E402
from codex_auto_resume_advanced.codex import inuse  # noqa: E402
from codex_auto_resume_advanced.codex.protocol import MEASUREMENT_METHODS  # noqa: E402
from codex_auto_resume_advanced.vocabulary import AutoResult, CheckReach, Measurement  # noqa: E402

SCHEMA = json.loads((Path(__file__).resolve().parent / "data" / "autocheck_schema.json").read_text(encoding="utf-8"))
FEATURES = "plugin_hooks    removed    false\n"
VERSION = "codex-cli 0.166.0-alpha.6"


def without_method(document, name, union="ClientRequest"):
    changed = copy.deepcopy(document)
    table = changed["definitions"][union]
    table["oneOf"] = [item for item in table["oneOf"] if item["properties"]["method"]["enum"] != [name]]
    return changed


class TableTests(unittest.TestCase):
    def test_every_measurement_is_looked_at_once(self):
        self.assertEqual(set(autocheck.CHECKS), set(Measurement))

    def test_a_row_asks_only_calls_its_measurement_declared(self):
        for measurement, row in autocheck.CHECKS.items():
            with self.subTest(measurement=measurement):
                self.assertLessEqual(set(row.methods), set(MEASUREMENT_METHODS[measurement]))

    def test_a_row_that_asks_nothing_reaches_nothing_and_one_that_reaches_asks(self):
        for measurement, row in autocheck.CHECKS.items():
            asks = bool(row.methods or row.params or row.requests or row.fields or row.words or row.feature)
            with self.subTest(measurement=measurement):
                self.assertEqual(asks, row.reach != CheckReach.NONE)

    def test_a_call_only_a_probe_makes_never_fails_a_route(self):
        """v0.6.23 audit A-M6. Fails with M4's and M4B's rows on hooks/list again: a Codex without that call - one only
        their probes make - would turn Continue inside the turn off as a call its route makes."""
        for measurement in (Measurement.M4, Measurement.M4B):
            row = autocheck.CHECKS[measurement]
            self.assertEqual(row.reach, CheckReach.FAILS_ONLY, measurement)
            self.assertEqual((row.words, row.feature), (autocheck.CHECKS[Measurement.MHK].words,
                                                        autocheck.CHECKS[Measurement.MHK].feature), measurement)
        self.assertNotIn("hooks/list", {method for row in autocheck.CHECKS.values() for method in row.methods})

    def test_what_stays_a_hand_measurement_stays_one(self):
        """The app, a person's eyes, a real rollout or conversation: nothing here may claim to settle them."""
        for measurement in (Measurement.M1, Measurement.M5, Measurement.MW, Measurement.MIPC, Measurement.MOPEN,
                            Measurement.MO, Measurement.MXA, Measurement.MC2, Measurement.MWAKE, Measurement.MAL,
                            Measurement.MP2, Measurement.MP3, Measurement.MTOK, Measurement.ME):
            self.assertEqual(autocheck.CHECKS[measurement].reach, CheckReach.NONE, measurement)
        self.assertEqual({measurement for measurement, row in autocheck.CHECKS.items()
                          if row.reach == CheckReach.WHOLE}, {Measurement.MHK})
        self.assertEqual({measurement for measurement, row in autocheck.CHECKS.items()
                          if row.reach == CheckReach.PART},
                         {Measurement.M6, Measurement.M6B, Measurement.MU, Measurement.MN, Measurement.MR,
                          Measurement.MX, Measurement.MF})


class JudgeTests(unittest.TestCase):
    def word(self, document, measurement, features=FEATURES):
        return autocheck.judge(document, features)[measurement]

    def test_a_real_codex_passes_every_row(self):
        answer = autocheck.judge(SCHEMA, FEATURES)
        self.assertEqual({row for row, spec in autocheck.CHECKS.items() if spec.reach != CheckReach.NONE}, set(answer))
        self.assertEqual({word for word, _gone in answer.values()}, {AutoResult.PASS})

    def test_a_method_gone_fails_every_row_that_calls_it_and_names_it(self):
        answer = autocheck.judge(without_method(SCHEMA, "thread/queue/add"), FEATURES)
        for measurement in (Measurement.M7, Measurement.MC1):
            self.assertEqual(answer[measurement], (AutoResult.FAIL, ("thread/queue/add",)))
        self.assertEqual(answer[Measurement.MU][0], AutoResult.PASS)

    def test_a_request_we_answer_gone_fails_the_turn_rows(self):
        answer = autocheck.judge(without_method(SCHEMA, "execCommandApproval", "ServerRequest"), FEATURES)
        self.assertEqual(answer[Measurement.M6], (AutoResult.FAIL, ("execCommandApproval",)))
        self.assertEqual(answer[Measurement.MX][0], AutoResult.PASS)

    def test_a_field_of_a_methods_own_params_gone_is_a_fail(self):
        changed = copy.deepcopy(SCHEMA)
        del changed["definitions"]["v2"]["ThreadQueueAddParams"]["properties"]["clientUserMessageId"]
        self.assertEqual(self.word(changed, Measurement.M7),
                         (AutoResult.FAIL, ("thread/queue/add.clientUserMessageId",)))

    def test_params_that_may_be_null_are_followed(self):
        self.assertEqual(self.word(SCHEMA, Measurement.MU)[0], AutoResult.PASS)
        changed = copy.deepcopy(SCHEMA)
        del changed["definitions"]["v2"]["GetAccountRateLimitsParams"]["properties"]["excludeResetCreditDetails"]
        self.assertEqual(self.word(changed, Measurement.MU),
                         (AutoResult.FAIL, ("account/rateLimits/read.excludeResetCreditDetails",)))

    def test_a_word_gone_from_a_type_that_is_there_is_a_fail(self):
        changed = copy.deepcopy(SCHEMA)
        outcome = changed["definitions"]["v2"]["ConsumeAccountRateLimitResetCreditOutcome"]
        outcome["oneOf"] = [item for item in outcome["oneOf"] if item.get("enum") != ["noCredit"]]
        self.assertEqual(self.word(changed, Measurement.MN)[0], AutoResult.FAIL)

    def test_the_refusal_we_send_is_read_in_each_of_its_shapes(self):
        """`decline` is an enum alternative, `denied` an object's one key: a refusal Codex stopped taking is a fail."""
        changed = copy.deepcopy(SCHEMA)
        decision = changed["definitions"]["ReviewDecision"]
        decision["oneOf"] = [item for item in decision["oneOf"] if item.get("required") != ["denied"]
                             and item.get("enum") != ["denied"]]
        self.assertEqual(self.word(changed, Measurement.M6), (AutoResult.FAIL, ("ReviewDecision.denied",)))

    def test_a_type_not_there_at_all_says_nothing_rather_than_a_fail(self):
        """An alpha may rename a type and keep every word in it, and a fail turns a capability off."""
        changed = copy.deepcopy(SCHEMA)
        del changed["definitions"]["v2"]["RateLimitWindow"]
        self.assertEqual(self.word(changed, Measurement.MU), (AutoResult.UNKNOWN, ()))

    def test_whats_gone_outranks_a_type_it_could_not_read(self):
        changed = without_method(SCHEMA, "account/rateLimits/read")
        del changed["definitions"]["v2"]["RateLimitWindow"]
        self.assertEqual(self.word(changed, Measurement.MU)[0], AutoResult.FAIL)

    def test_a_document_that_is_not_the_whole_schema_is_no_answer_never_a_fail(self):
        self.assertEqual(autocheck.judge(without_method(SCHEMA, "turn/start"), FEATURES), {})
        thin = copy.deepcopy(SCHEMA)
        thin["definitions"]["ClientRequest"]["oneOf"] = [
            item for item in thin["definitions"]["ClientRequest"]["oneOf"]
            if item["properties"]["method"]["enum"][0] in autocheck.SANE_METHODS]
        self.assertEqual(autocheck.judge(thin, FEATURES), {})
        self.assertEqual(autocheck.judge({}, FEATURES), {})

    def test_mhk_is_the_probes_own_rule(self):
        self.assertEqual(self.word(SCHEMA, Measurement.MHK), (AutoResult.PASS, ()))
        self.assertEqual(self.word(SCHEMA, Measurement.MHK, "something else true\n"),
                         (AutoResult.FAIL, ("plugin_hooks",)))
        self.assertEqual(self.word(SCHEMA, Measurement.MHK, None), (AutoResult.UNKNOWN, ()))


class DueTests(unittest.TestCase):
    KEY = ["d" * 64, 10, 20]

    def record(self, **changes):
        return dict(autocheck._attempt(None, self.KEY, 1, 1000.0), **changes)

    def test_nothing_known(self):
        self.assertTrue(autocheck.due(None, self.KEY, 1000.0))
        self.assertFalse(autocheck.due(None, None, 1000.0), "no engine file, no run")

    def test_an_answer_is_once_for_that_file_however_long_after(self):
        done = self.record(engine=VERSION, checked_at=1000.0)
        self.assertFalse(autocheck.due(done, self.KEY, 1000.0 + 10 ** 7))

    def test_a_run_with_no_answer_waits_and_tries_three_times(self):
        self.assertFalse(autocheck.due(self.record(), self.KEY, 1000.0 + autocheck.RETRY_AFTER - 1))
        self.assertTrue(autocheck.due(self.record(), self.KEY, 1000.0 + autocheck.RETRY_AFTER))
        self.assertFalse(autocheck.due(self.record(tries=autocheck.TRIES), self.KEY, 1000.0 + 10 ** 7))

    def test_a_new_engine_or_table_asks_again_but_never_sooner_than_the_gap(self):
        done = self.record(engine=VERSION, checked_at=1000.0)
        other = ["d" * 64, 11, 21]
        self.assertFalse(autocheck.due(done, other, 1000.0 + autocheck.AT_MOST_EVERY - 1))
        self.assertTrue(autocheck.due(done, other, 1000.0 + autocheck.AT_MOST_EVERY))
        self.assertTrue(autocheck.due(dict(done, revision=autocheck.REVISION - 1), self.KEY,
                                      1000.0 + autocheck.AT_MOST_EVERY))

    def test_a_clock_put_back_owes_no_wait(self):
        self.assertTrue(autocheck.due(self.record(), self.KEY[:2] + [99], 10.0))


class FakeEngine:
    """Stands in for `subprocess.run` in autocheck: writes the schema where it is told to, prints the features, and keeps
    every call."""

    def __init__(self, schema=SCHEMA, features=FEATURES, code=0):
        self.schema, self.features, self.code = schema, features, code
        self.calls = []

    def __call__(self, argv, **keywords):
        self.calls.append((list(argv), keywords))
        printed = ""
        if "generate-json-schema" in argv:
            folder = Path(argv[argv.index("--out") + 1])
            if self.schema is not None:
                (folder / autocheck.SCHEMA_FILE).write_text(json.dumps(self.schema), encoding="utf-8")
        elif "features" in argv:
            printed = self.features
        return subprocess.CompletedProcess(argv, self.code, printed, "")


def accepted(backend):
    backend.engine_version = VERSION
    return True


class RunTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.exe = self.home.parent / "codex.exe"
        self.exe.write_bytes(b"not really")
        self.addCleanup(inuse.forget, self.paths)
        self.addCleanup(autocheck._LOOKED.clear)
        self.addCleanup(autocheck._RUNNING.clear)

    def attempt(self):
        record = autocheck._attempt(self.paths, autocheck._engine_key(self.exe), 1, self.now)
        autocheck._write(self.paths, record)
        return record

    def run_with(self, engine, compatible=accepted):
        with mock.patch.object(autocheck.subprocess, "run", engine), \
                mock.patch.object(transport.Backend, "_compatible", compatible):
            autocheck.run_once(self.paths, self.exe, self.attempt(), clock=lambda: self.now + 5)

    def test_an_answer_is_written_for_the_version_the_engine_names(self):
        self.run_with(FakeEngine())
        record = autocheck.read_record(self.paths)
        self.assertEqual((record["engine"], record["checked_at"]), (VERSION, self.now + 5))
        self.assertEqual(autocheck.results_for(self.paths, VERSION)[Measurement.M6], AutoResult.PASS)

    def test_what_it_starts_is_exactly_these_windowless_on_a_scratch_home(self):
        engine, homes = FakeEngine(), []
        real_home = self.home.parent / "the person's codex home"

        def compatible(backend):
            homes.append(backend.codex_home)
            return accepted(backend)

        with mock.patch.dict(os.environ, {"CODEX_HOME": str(real_home)}):
            self.run_with(engine, compatible)
        options = transport.Backend(self.home, self.exe)._argv()[1:]
        said = [argv[len(options) + 1:] for argv, _keywords in engine.calls]
        self.assertEqual([each[:3] for each in said],
                         [["app-server", "generate-json-schema", "--experimental"], ["features", "list"]])
        for argv, keywords in engine.calls:
            self.assertEqual(Path(argv[0]), self.exe.resolve())
            self.assertEqual(argv[1:len(options) + 1], options, "core's own options: no analytics, no telemetry")
            self.assertEqual(keywords["creationflags"], NO_WINDOW)
            self.assertEqual(keywords["stdin"], subprocess.DEVNULL)
            self.assertIs(keywords["shell"], False)
            self.assertEqual(keywords["timeout"], autocheck.CHILD_SECONDS)
            self.assertEqual(Path(keywords["env"]["CODEX_HOME"]), homes[0])
            self.assertEqual(Path(keywords["env"]["CODEX_HOME"]).name, "codex-home")
            self.assertEqual(Path(keywords["cwd"]), homes[0].parent, "no project's own Codex config beside it")
            self.assertEqual(keywords["env"]["OTEL_SDK_DISABLED"], "true")
        self.assertNotIn(str(real_home), json.dumps([argv for argv, _keywords in engine.calls]))
        self.assertNotEqual(homes[0], real_home)
        self.assertFalse(homes[0].parent.exists(), "the scratch folder is gone")

    def test_it_never_starts_a_server_a_turn_or_a_sign_in(self):
        engine = FakeEngine()
        self.run_with(engine)
        words = {word for argv, _keywords in engine.calls for word in argv}
        self.assertFalse(words & {"--stdio", "exec", "login", "logout", "queue", "resume"})

    def test_an_engine_official_engine_refuses_starts_nothing_and_is_no_answer(self):
        engine = FakeEngine()
        with mock.patch.object(autocheck.subprocess, "run", engine), \
                mock.patch.object(transport, "official_engine", lambda path: (False, "wrong_signer")):
            autocheck.run_once(self.paths, self.exe, self.attempt())
        self.assertEqual(engine.calls, [])
        self.assertIsNone(autocheck.read_record(self.paths)["engine"])

    def test_no_answer_is_never_a_fail(self):
        for engine in (FakeEngine(code=2), FakeEngine(schema=None), FakeEngine(schema={"definitions": {}})):
            self.run_with(engine)
            record = autocheck.read_record(self.paths)
            self.assertIsNone(record["engine"])
            self.assertEqual(record["results"], {})
            self.assertEqual(autocheck.results_for(self.paths, VERSION), {})

    def test_a_raising_engine_check_is_no_answer_and_the_scratch_folder_goes(self):
        def refused(_backend):
            raise AdapterError("engine_refused")

        made, real = [], autocheck.tempfile.mkdtemp

        def kept(**keywords):
            made.append(real(**keywords))
            return made[-1]

        with mock.patch.object(autocheck.tempfile, "mkdtemp", kept):
            self.run_with(FakeEngine(), refused)
        self.assertEqual(len(made), 1)
        self.assertFalse(Path(made[0]).exists())
        self.assertIsNone(autocheck.read_record(self.paths)["engine"])

    def test_features_not_running_leaves_the_rows_that_need_no_features_answered(self):
        class NoFeatures(FakeEngine):
            def __call__(self, argv, **keywords):
                done = super().__call__(argv, **keywords)
                return subprocess.CompletedProcess(argv, 1 if "features" in argv else 0, done.stdout, "")

        self.run_with(NoFeatures())
        found = autocheck.results_for(self.paths, VERSION)
        self.assertEqual(found[Measurement.MHK], AutoResult.UNKNOWN)
        self.assertEqual(found[Measurement.MU], AutoResult.PASS)

    def test_a_fail_keeps_only_this_tables_names(self):
        self.run_with(FakeEngine(schema=without_method(SCHEMA, "thread/queue/add")))
        record = autocheck.read_record(self.paths)
        self.assertEqual(record["results"]["m7"], "fail")
        self.assertEqual(record["gone"]["m7"], ["thread/queue/add"])
        self.assertEqual(autocheck.diagnostics(self.paths)["gone"]["m7"], ["thread/queue/add"])


class RecordTests(ac.AdvancedCase):
    def record(self, **changes):
        made = dict(autocheck._attempt(self.paths, ["d" * 64, 1, 2], 1, self.now), engine=VERSION, checked_at=self.now,
                    results={"m6": "pass", "m7": "fail"}, gone={"m7": ["thread/queue/add"]})
        made.update(changes)
        return made

    def test_the_answer_counts_only_for_exactly_that_engine_and_this_table(self):
        autocheck._write(self.paths, self.record())
        self.assertEqual(autocheck.results_for(self.paths, VERSION),
                         {Measurement.M6: AutoResult.PASS, Measurement.M7: AutoResult.FAIL})
        self.assertEqual(autocheck.results_for(self.paths, "codex-cli 0.166.0-alpha.7"), {})
        self.assertEqual(autocheck.results_for(self.paths, None), {})
        autocheck._write(self.paths, self.record(revision=autocheck.REVISION + 1))
        self.assertEqual(autocheck.results_for(self.paths, VERSION), {})

    def test_a_record_wrong_in_any_part_is_not_read_at_all(self):
        for changes in ({"results": {"m6": "maybe"}}, {"results": {"nothing": "pass"}}, {"gone": {"m7": "text"}},
                        {"format": "other"}, {"engine": "C:\\a path"}, {"tries": "1"}, {"tried_at": None},
                        {"engine": VERSION, "checked_at": None}):
            autocheck._write(self.paths, self.record(**changes))
            with self.subTest(changes=changes):
                self.assertIsNone(autocheck.read_record(self.paths))
                self.assertEqual(autocheck.results_for(self.paths, VERSION), {})
        self.paths.advanced_dir.joinpath(autocheck.FILE).write_bytes(b"\xff not json")
        self.assertIsNone(autocheck.read_record(self.paths))

    def test_it_lives_where_a_purge_finds_it(self):
        autocheck._write(self.paths, self.record())
        self.assertIn(self.paths.advanced_dir / autocheck.FILE, self.paths.owned_advanced_files())


class TendTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.exe = self.home.parent / "codex.exe"
        self.exe.write_bytes(b"not really")
        self.addCleanup(inuse.forget, self.paths)
        self.addCleanup(autocheck._LOOKED.clear)
        self.addCleanup(autocheck._RUNNING.clear)
        self.started = []
        patcher = mock.patch.object(autocheck, "run_once", lambda *args, **kwargs: self.started.append(args))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tend(self, later=0.0):
        self.now += later
        started = autocheck.tend(self.paths, clock=lambda: self.now)
        for thread in autocheck._RUNNING.values():
            thread.join(5)
        return started

    def test_nothing_told_nothing_read_nothing_written(self):
        """A process that holds no watcher - the bridge, the page, a test - has been told no engine."""
        with mock.patch.object(autocheck, "read_record", side_effect=AssertionError("read")), \
                mock.patch.object(autocheck, "_write", side_effect=AssertionError("written")):
            self.assertFalse(self.tend())
        self.assertFalse(self.paths.advanced_dir.exists())

    def test_the_engine_told_is_checked_once_and_the_attempt_is_written_first(self):
        inuse.tell(self.paths, self.exe, self.home.parent)
        self.assertTrue(self.tend())
        self.assertEqual(len(self.started), 1)
        self.assertEqual(Path(self.started[0][1]), self.exe.resolve())
        record = autocheck.read_record(self.paths)
        self.assertEqual((record["tries"], record["tried_at"], record["engine"]), (1, self.now, None))

    def test_it_looks_at_most_once_a_minute(self):
        inuse.tell(self.paths, self.exe, self.home.parent)
        self.tend()
        with mock.patch.object(autocheck, "read_record", side_effect=AssertionError("read")):
            self.assertFalse(self.tend(autocheck.LOOK_EVERY - 1))

    def test_a_watcher_restarting_asks_nothing_more(self):
        inuse.tell(self.paths, self.exe, self.home.parent)
        self.tend()
        record = dict(autocheck.read_record(self.paths), engine=VERSION, checked_at=self.now)
        autocheck._write(self.paths, record)
        autocheck._LOOKED.clear()
        autocheck._RUNNING.clear()
        self.assertFalse(self.tend(1000.0))
        self.assertEqual(len(self.started), 1)

    def test_a_new_engine_file_asks_again_only_after_the_gap(self):
        inuse.tell(self.paths, self.exe, self.home.parent)
        self.tend()
        autocheck._write(self.paths, dict(autocheck.read_record(self.paths), engine=VERSION, checked_at=self.now))
        self.exe.write_bytes(b"not really, and a new build")
        self.assertFalse(self.tend(autocheck.LOOK_EVERY))
        self.assertTrue(self.tend(autocheck.AT_MOST_EVERY))
        self.assertEqual(autocheck.read_record(self.paths)["tries"], 1)
        self.assertIsNone(autocheck.read_record(self.paths)["engine"], "the old engine's answer is not this one's")

    def test_a_run_with_no_answer_is_tried_three_times_and_no_more(self):
        inuse.tell(self.paths, self.exe, self.home.parent)
        self.assertTrue(self.tend())
        self.assertFalse(self.tend(autocheck.RETRY_AFTER - 1))
        self.assertTrue(self.tend(1 + autocheck.LOOK_EVERY))
        self.assertTrue(self.tend(autocheck.RETRY_AFTER))
        self.assertFalse(self.tend(autocheck.RETRY_AFTER * 10))
        self.assertEqual(autocheck.read_record(self.paths)["tries"], autocheck.TRIES)

    def test_one_run_at_a_time(self):
        inuse.tell(self.paths, self.exe, self.home.parent)
        hold = threading.Event()
        with mock.patch.object(autocheck, "run_once", lambda *args, **kwargs: hold.wait(10)):
            self.assertTrue(autocheck.tend(self.paths, clock=lambda: self.now))
            self.now += 10 ** 6
            self.exe.write_bytes(b"not really, and a new build")
            self.assertFalse(autocheck.tend(self.paths, clock=lambda: self.now))
            hold.set()
            for thread in autocheck._RUNNING.values():
                thread.join(5)


class WatcherOnlyTests(ac.AdvancedCase):
    def test_the_tick_tends_it_with_nothing_on_and_answers_as_null_does(self):
        made = self.runtime()
        with mock.patch.object(autocheck, "tend") as tend:
            self.assertIs(made.tick({}), DEFER)
        tend.assert_called_once()
        self.assertEqual(tend.call_args.args[0], self.paths)

    def test_a_check_that_raises_costs_the_tick_nothing(self):
        made = self.runtime()
        with mock.patch.object(autocheck, "tend", side_effect=RuntimeError("no")):
            self.assertIs(made.tick({}), DEFER)

    def test_the_plug_told_its_engine_starts_nothing_there(self):
        exe = self.home.parent / "codex.exe"
        exe.write_bytes(b"not really")
        plug = self.plug()
        self.addCleanup(inuse.forget, self.paths)
        with mock.patch.object(threading, "Thread", side_effect=AssertionError("a thread")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("a process")):
            plug.codex(exe, self.home.parent)

    def test_a_reader_starts_nothing(self):
        """The bridge, the page, a statement, MCP and Diagnostics read the record; only the watcher's tick runs a check."""
        autocheck._write(self.paths, autocheck._attempt(self.paths, ["d" * 64, 1, 2], 1, self.now))
        made = self.runtime()
        with mock.patch.object(threading, "Thread", side_effect=AssertionError("a thread")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("a process")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("a process")):
            autocheck.results_for(self.paths, VERSION)
            autocheck.diagnostics(self.paths)
            made.arming.listing()

    def test_core_never_names_it(self):
        """Off in the standard edition by having nothing there: plug points only."""
        core = ac.ROOT / "src" / "codex_auto_resume"
        for path in core.rglob("*.py"):
            self.assertNotIn("autocheck", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
