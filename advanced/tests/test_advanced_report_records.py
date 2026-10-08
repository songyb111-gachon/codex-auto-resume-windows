"""The compatibility report's reader (report/records.py and report/evidence.py): it reads this PC's
own records as codex-compat-reporter 1.5.0 reads them, writes nothing, and lets nothing out but
counts, states, times and versions.

Every home is reportfixtures' - a temporary folder holding a product home and a Codex home, with
CODEX_HOME, LOCALAPPDATA and the profile pointed into it - so nothing real is read. The goldens in
golden/report/ are what the reporter's own `build` wrote of the same homes
(advanced/tests/reportgolden.py), so the reader's body is held to the reporter's byte for byte.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
from pathlib import Path
import re
import sqlite3
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reportfixtures as fixtures  # noqa: E402
from reportfixtures import ENGINE, NEWER, OLDER, Home  # noqa: E402

from codex_auto_resume import compat, config  # noqa: E402
from codex_auto_resume.runtime.app import ENGINE_LOG_WORDS  # noqa: E402
from codex_auto_resume.store import SCHEMA_VERSION as CORE_SCHEMA  # noqa: E402
from codex_auto_resume_advanced.report import evidence, records  # noqa: E402
from codex_auto_resume_advanced.report.records import ReadRefusal  # noqa: E402
from codex_auto_resume_advanced.state import journal, schema as ledger_schema  # noqa: E402

GOLDEN = HERE / "golden" / "report"
PACKAGE = fixtures.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "report"
DEFAULT = object()
ISO = re.compile(r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")


def receiver():
    """build/community_report.py, the project's own reader of a report as it arrives."""
    spec = importlib.util.spec_from_file_location("community_report_for_reader_tests",
                                                  fixtures.ROOT / "build" / "community_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(home, asked=None, *, view=DEFAULT, now=fixtures.NOW):
    with fixtures.isolated(home):
        return records.read(home.paths, home.codex, asked, now=now,
                            view=home.raw_view if view is DEFAULT else view)


def encode(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True)


class Case(unittest.TestCase):
    def home(self, rows=(), **given) -> Home:
        made = Home(rows, **given)
        self.addCleanup(made.close)
        return made

    def refused(self, code, home, asked=None, **options):
        with self.assertRaises(records.ReadRefused) as raised:
            read(home, asked, **options)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.args, (str(code),), "a refusal is its code and nothing else")


class GoldenTests(Case):
    def test_each_home_reads_as_the_reporter_wrote_it(self):
        for name in fixtures.SCENARIOS:
            with self.subTest(name):
                golden = json.loads((GOLDEN / ("%s.json" % name)).read_text(encoding="ascii"))
                home, asked = fixtures.scenario(name)
                self.addCleanup(home.close)
                found = read(home, asked)
                self.assertEqual(encode(found["body"]), encode(golden["body"]), "the body, key order and all")
                self.assertEqual(found["left_out"], golden["left_out"])

    def test_every_golden_is_a_home_the_reporter_1_5_0_wrote(self):
        self.assertEqual({path.stem for path in GOLDEN.glob("*.json")}, set(fixtures.SCENARIOS))
        for path in GOLDEN.glob("*.json"):
            golden = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual((golden["scenario"], golden["reporter"]), (path.stem, "1.5.0"))

    def test_the_homes_hold_every_case_the_reader_tells_apart(self):
        """Otherwise the goldens prove agreement on less than the reader does."""
        verdicts, reads, left = set(), set(), {}
        for name in fixtures.SCENARIOS:
            golden = json.loads((GOLDEN / ("%s.json" % name)).read_text(encoding="ascii"))
            verdicts.add(golden["body"]["verdict"])
            home, asked = fixtures.scenario(name)
            self.addCleanup(home.close)
            found = read(home, asked)
            reads.add((found["read"]["state_schema"], found["read"]["ledger_schema"], found["engine"]["from"]))
            for field, many in found["left_out"].items():
                if field == "unplaced":
                    for code, count in many.items():
                        left[code] = left.get(code, 0) + count
                else:
                    left[field] = left.get(field, 0) + many
        self.assertEqual(verdicts, {"PASS", "CHECKED"})
        self.assertEqual({state for state, _ledger, _from in reads}, {3, 4})
        self.assertEqual({ledger for _state, ledger, _from in reads}, {None, 1, 2})
        self.assertEqual({source for *_rest, source in reads}, {"log", "watcher_report"})
        self.assertTrue(all(left.get(name) for name in ("hidden", "another_route", "beyond_reach", "elsewhere",
                                                        *evidence.Unplaced)), left)


class ContentFreeTests(Case):
    POISON = ("C:\\Users\\ExampleUser\\secret.txt", "someone@example.com", "Hello, world",
              "0a1b2c3d-9999-7000-8000-000000000999", "/home/exampleuser/x")

    def test_nothing_but_times_versions_and_closed_words_comes_out(self):
        """A path in last_error, a UUID as a category, an e-mail in limit_type, a sentence as a state:
        every string the reader answers with is a time, a version or a word of a closed list."""
        path, mail, sentence, uuid, unix = self.POISON
        poisoned = fixtures.recovered(40, 15, 13, last_error=path, category=uuid, limit_type=mail, state=sentence,
                                      recovery_turn_status=unix, thread_id=path,
                                      gate_eval=json.dumps({"engine_compatible": ["PASS", path], mail: ["PASS"]}))
        report = fixtures.watcher()
        report["capabilities"][path] = {"state": sentence, "reason": "local_checks_passed"}
        home = self.home(fixtures.BASE + [poisoned], watcher_report=report)
        found = read(home)
        text = encode(found)
        for leak in self.POISON:
            self.assertNotIn(json.dumps(leak)[1:-1], text)
        words = (evidence.CATEGORIES | evidence.STATES | evidence.REASONS | evidence.TURN_STATUSES
                 | {evidence.OTHER, "PASS", "CHECKED", "NONE", compat.VERIFIED, compat.CHECKED}
                 | set(evidence.REPORTABLE) | set(evidence.PROGRESS) | set(evidence.Unplaced)
                 | set(records.HistoryRead) | set(records.EngineSource))
        keys = ({"read", "state_schema", "ledger_schema", "history", "paused", "engine", "current", "from",
                 "left_out", "hidden", "another_route", "beyond_reach", "elsewhere", "unplaced", "body",
                 "codex_version", "verdict", "local_checks", "reports", "first", "last", "covers", "records",
                 "capabilities", "detected_at", "delivered_at", "outcome_at", "category", "state", "reason",
                 "turn_status", "gates_passed", "progress_items", "confirmed", "missed", "last_confirmed", "level"}
                | set(evidence.REPORTABLE) | set(evidence.PROGRESS) | set(evidence.Unplaced))

        def walk(value, where="answer"):
            if isinstance(value, dict):
                for name, inner in value.items():
                    self.assertIn(name, keys, where)
                    walk(inner, "%s.%s" % (where, name))
            elif isinstance(value, list):
                for inner in value:
                    walk(inner, where)
            elif isinstance(value, str):
                self.assertTrue(ISO.match(value) or evidence.VERSION.match(value) or value in words,
                                "%s holds %r" % (where, value))
            else:
                self.assertTrue(value is None or isinstance(value, (bool, int)), where)
        walk(found)
        self.assertIn("other", [record["state"] for record in found["body"]["records"]])


class ReadOnlyTests(Case):
    def test_reading_writes_makes_and_leaves_nothing(self):
        """Every file under both homes keeps its size, its time and its bytes, and nothing is made beside
        them - no -journal, no folder - whether the read answers or refuses."""
        for name in fixtures.SCENARIOS:
            with self.subTest(name):
                home, asked = fixtures.scenario(name)
                self.addCleanup(home.close)
                before = home.snapshot()
                read(home, asked)
                self.assertEqual(home.snapshot(), before)
        for given, code in ((dict(state=5), ReadRefusal.STATE_NEWER),
                            (dict(ledger=ledger_schema.SCHEMA_VERSION + 1), ReadRefusal.LEDGER_NEWER),
                            (dict(state=None), ReadRefusal.NO_STATE)):
            with self.subTest(code):
                home = self.home(fixtures.BASE, **given)
                before = home.snapshot()
                self.refused(code, home)
                self.assertEqual(home.snapshot(), before)

    def test_it_asks_the_databases_only_what_the_report_needs(self):
        """Every statement sent, traced: reads of the report's tables only, never a write, an attach or
        a migration - and of Codex, its history alone."""
        connect, said = sqlite3.connect, []

        def traced(*arguments, **keywords):
            connection = connect(*arguments, **keywords)
            said.append(str(arguments[0]))
            connection.set_trace_callback(lambda statement: said.append(statement))
            return connection

        home, asked = fixtures.scenario("state4_ledger2")
        self.addCleanup(home.close)
        with mock.patch("sqlite3.connect", side_effect=traced):
            read(home, asked)
        opened = [line for line in said if line.startswith("file:")]
        self.assertTrue(opened and all(line.endswith("?mode=ro") for line in opened), opened)
        self.assertEqual({Path(line.split("?")[0]).name for line in opened},
                         {"state.sqlite", "advanced.sqlite", "thread_history_10.sqlite"})
        statements = [line for line in said if not line.startswith("file:")]
        for statement in statements:
            with self.subTest(statement):
                self.assertRegex(statement, r"\A(SELECT|PRAGMA) ")
                self.assertNotRegex(statement.upper(), r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ATTACH|REPLACE|ALTER)\b")
                tables = set(re.findall(r"\bFROM (\w+)", statement))
                self.assertLessEqual(tables, {"interruptions", "settings", "spend", "sqlite_master",
                                              "sqlite_sequence", "thread_items"})
        self.assertIn("PRAGMA query_only = ON", statements)

    def test_the_store_is_never_opened_and_nothing_is_written(self):
        """Read from the source: no Store, which makes its folder and opens the file writable, and no
        call that writes, makes or removes a file."""
        writes = {"write_text", "write_bytes", "mkdir", "unlink", "rename", "replace", "touch", "rmdir",
                  "commit", "executescript"}
        for path in sorted(PACKAGE.glob("*.py")):
            with self.subTest(path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = {getattr(node, "attr", None) or getattr(node, "id", None) for node in ast.walk(tree)}
                self.assertEqual(names & (writes | {"Store", "open_state", "AdvancedState"}), set())
        source = (PACKAGE / "records.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("sqlite3.connect("), 1)
        self.assertIn('as_uri() + "?mode=ro", uri=True', source)


class RefusalTests(Case):
    def test_a_state_the_reader_does_not_know_is_refused(self):
        self.refused(ReadRefusal.NO_STATE, self.home(state=None))
        self.refused(ReadRefusal.STATE_NEWER, self.home(fixtures.BASE, state=5))
        self.refused(ReadRefusal.STATE_OLDER, self.home(fixtures.BASE, state=2))
        self.refused(ReadRefusal.STATE_UNREADABLE, self.home(fixtures.BASE, columns=["gate_eval"]))
        damaged = self.home(state=None)
        (damaged.paths.state_dir / "state.sqlite").write_bytes(b"not a database, whatever its name says")
        self.refused(ReadRefusal.STATE_UNREADABLE, damaged)

    def test_the_schemas_read_are_core_s_and_the_ledgers_own(self):
        self.assertIn(CORE_SCHEMA, records.STATE_SCHEMAS)
        self.assertEqual(max(records.STATE_SCHEMAS), CORE_SCHEMA, "a newer state is read on purpose, or not at all")
        for version in range(1, ledger_schema.SCHEMA_VERSION + 1):
            with self.subTest(ledger=version):
                self.assertEqual(read(self.home(fixtures.BASE, ledger=version))["read"]["ledger_schema"], version)

    def test_a_ledger_the_reader_does_not_know_is_refused(self):
        self.refused(ReadRefusal.LEDGER_NEWER, self.home(fixtures.BASE, ledger=ledger_schema.SCHEMA_VERSION + 1))
        self.refused(ReadRefusal.LEDGER_UNREADABLE, self.home(fixtures.BASE, ledger=0))
        bare = self.home(fixtures.BASE)
        bare.paths.advanced_dir.mkdir()
        db = sqlite3.connect(bare.paths.advanced_dir / ledger_schema.FILE_NAME)
        db.execute("CREATE TABLE spend (spend_id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL)")
        db.execute("PRAGMA user_version = 2")
        db.commit()
        db.close()
        self.refused(ReadRefusal.LEDGER_UNREADABLE, bare)

    def test_with_no_records_the_ledger_is_not_read_as_1_5_0_does_not_read_it(self):
        """1.5.0's by_route asks the ledger only when there are records to tell apart: with none, a ledger
        it does not know, or one that is not a database, still gives the report a home without one gives."""
        plain = read(self.home((), watcher_report=fixtures.watcher()))
        self.assertEqual(len(plain["body"]["records"]), 0)
        damaged = self.home((), ledger=2, watcher_report=fixtures.watcher())
        (damaged.paths.advanced_dir / ledger_schema.FILE_NAME).write_bytes(b"not a database, whatever its name says")
        for name, home in (("newer", self.home((), ledger=ledger_schema.SCHEMA_VERSION + 1,
                                               watcher_report=fixtures.watcher())),
                           ("none", self.home((), ledger=0, watcher_report=fixtures.watcher())),
                           ("damaged", damaged)):
            with self.subTest(ledger=name):
                found = read(home)
                self.assertEqual(encode(found["body"]), encode(plain["body"]))
                self.assertEqual(found["left_out"], plain["left_out"])
                self.assertIsNone(found["read"]["ledger_schema"], "it was not read")
        self.refused(ReadRefusal.LEDGER_NEWER, self.home(fixtures.BASE, ledger=ledger_schema.SCHEMA_VERSION + 1,
                                                        watcher_report=fixtures.watcher()))

    def test_a_locked_state_is_busy_not_waited_for(self):
        home = self.home(fixtures.BASE)
        blocker = sqlite3.connect(home.paths.state_dir / "state.sqlite", timeout=0)
        self.addCleanup(blocker.close)
        blocker.execute("BEGIN EXCLUSIVE")
        self.addCleanup(blocker.rollback)
        with mock.patch.object(records, "TIMEOUT", 0.1):
            self.refused(ReadRefusal.STATE_BUSY, home)

    @unittest.skipUnless(sys.platform == "win32", "a junction is Windows'")
    def test_a_junction_is_never_followed(self):
        import _winapi
        home = self.home(fixtures.BASE, ledger=2)
        elsewhere = home.root / "elsewhere"
        home.paths.advanced_dir.rename(elsewhere)
        _winapi.CreateJunction(str(elsewhere), str(home.paths.advanced_dir))
        self.refused(ReadRefusal.LEDGER_UNREADABLE, home)
        state = self.home(fixtures.BASE)
        moved = state.root / "moved"
        state.paths.state_dir.rename(moved)
        _winapi.CreateJunction(str(moved), str(state.paths.state_dir))
        self.refused(ReadRefusal.STATE_UNREADABLE, state)

    def test_no_engine_version_anywhere_is_refused(self):
        self.refused(ReadRefusal.NO_ENGINE_VERSION,
                     self.home(fixtures.BASE, log_files={"auto-resume.log": [fixtures.line(fixtures.sep(9), "tick ok")]}))

    def test_a_version_not_in_the_products_one_spelling_is_refused(self):
        home = self.home(fixtures.BASE, watcher_report=fixtures.watcher())
        for asked in ("0.01.0", "00.158.0", "codex-cli 1.2", "0.158.0-alpha.2.0", "banana", "", "0.158.0 "):
            with self.subTest(asked):
                if asked == "0.158.0 ":
                    self.assertEqual(read(home, asked)["body"]["codex_version"], ENGINE)
                else:
                    self.refused(ReadRefusal.VERSION_INVALID, home, asked)
        self.assertEqual(read(home, "0.158.0")["body"]["codex_version"], ENGINE)
        odd = self.home(fixtures.BASE, watcher_report=fixtures.watcher("codex-cli 0.158.00"))
        self.refused(ReadRefusal.VERSION_INVALID, odd)

    def test_more_records_than_a_report_holds_is_refused(self):
        many = [fixtures.recovered(100 + number, 23, 9, detected_at=fixtures.sep(23, 9) + number)
                for number in range(evidence.MAX_RECORDS + 1)]
        self.refused(ReadRefusal.TOO_MANY_RECORDS, self.home(many, watcher_report=fixtures.watcher()))
        self.assertEqual(len(read(self.home(many[:-1], watcher_report=fixtures.watcher()))["body"]["records"]),
                         evidence.MAX_RECORDS)


class RouteTests(Case):
    def row(self, **fields):
        return fixtures.recovered(50, 15, **fields)

    def test_each_of_the_products_own_marks_is_another_route(self):
        key = fixtures.key(50)
        self.assertTrue(evidence.another_route(fixtures.CLIENT_ID, {}))
        self.assertFalse(evidence.another_route(self.row(recovery_client_id=fixtures.CLIENT_ID["recovery_client_id"]), {}),
                         "the client id of another record's continuation is no mark of this one")
        for gate, word in (("thread_available", "plugged"), ("usage", "held"), ("identity", "plugged")):
            with self.subTest(gate=gate, word=word):
                self.assertTrue(evidence.another_route(self.row(gate_eval=fixtures.gates(**{gate: ["PASS", word]})), {}))
        self.assertFalse(evidence.another_route(self.row(gate_eval=fixtures.gates(consent=["WAIT", "held"])), {}),
                         "held at consent is a person's hold, the standard edition's own")
        claimed = self.row()
        self.assertTrue(evidence.another_route(claimed, {key: {claimed["last_claim_at"]}}))
        self.assertFalse(evidence.another_route(claimed, {key: {claimed["last_claim_at"] + 1}}))
        self.assertFalse(evidence.another_route(self.row(gate_eval=json.dumps({"usage": ["PASS", 7]})), {}))

    def test_a_ledger_that_lost_units_tells_claims_only_from_its_reach(self):
        bounds = dict(max_age=journal.EVENT_MAX_AGE, limit=journal.EVENT_LIMIT)
        now = fixtures.NOW
        self.assertIsNone(evidence.ledger_reach(3, fixtures.sep(1), 3, now, **bounds), "nothing was pruned")
        self.assertEqual(evidence.ledger_reach(3, fixtures.sep(1), 5, now, **bounds), now - journal.EVENT_MAX_AGE)
        self.assertEqual(evidence.ledger_reach(3, fixtures.at(5, 1), 5, now, **bounds), fixtures.at(5, 1))
        self.assertEqual(evidence.ledger_reach(journal.EVENT_LIMIT, fixtures.sep(1), journal.EVENT_LIMIT + 1, now,
                                               **bounds), fixtures.sep(1), "count pruned: only the oldest vouches")
        self.assertEqual(evidence.ledger_reach(3, fixtures.sep(1), None, now, **bounds), now - journal.EVENT_MAX_AGE,
                         "no count kept: it may have lost some")
        self.assertTrue(evidence.beyond_reach(fixtures.LONG_AGO, now - journal.EVENT_MAX_AGE))
        self.assertFalse(evidence.beyond_reach(fixtures.INSIDE_REACH, now - journal.EVENT_MAX_AGE))
        self.assertFalse(evidence.beyond_reach(fixtures.LONG_AGO, None))

    def test_the_bounds_are_the_ledgers_own_and_not_copied(self):
        home, asked = fixtures.scenario("state4_ledger1_pruned")
        self.addCleanup(home.close)
        self.assertEqual(read(home, asked)["left_out"]["beyond_reach"], 1)
        with mock.patch.object(journal, "EVENT_MAX_AGE", fixtures.NOW - fixtures.at(6, 1)):
            self.assertEqual(read(home, asked)["left_out"]["beyond_reach"], 0, "the reach moved with the ledger's own")
        tree = ast.parse((PACKAGE / "records.py").read_text(encoding="utf-8")
                         + (PACKAGE / "evidence.py").read_text(encoding="utf-8"))
        numbers = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, int) and not isinstance(node.value, bool)}
        self.assertEqual(numbers & {90, 5000, 86400, 90 * 86400}, set())


class PlacementTests(Case):
    TIMELINE = [(100.0, OLDER), (200.0, OLDER), (300.0, ENGINE), (400.0, ENGINE)]

    def test_each_reason_a_record_cannot_be_placed(self):
        self.assertEqual(evidence.placement(self.TIMELINE, 50, 60, ENGINE), (None, evidence.Unplaced.NO_ENGINE_LINE_BEFORE))
        self.assertEqual(evidence.placement(self.TIMELINE, 250, 350, ENGINE),
                         (None, evidence.Unplaced.ENGINE_CHANGED_DURING))
        self.assertEqual(evidence.placement(self.TIMELINE, 250, 260, ENGINE),
                         (None, evidence.Unplaced.NEXT_LINE_OTHER_VERSION))
        self.assertEqual(evidence.placement(self.TIMELINE, 450, 460, NEWER), (None, evidence.Unplaced.ENGINE_CHANGED_AFTER))
        self.assertEqual(evidence.placement(self.TIMELINE, 150, 160, ENGINE), (OLDER, None))
        self.assertEqual(evidence.placement(self.TIMELINE, 450, 460, ENGINE), (ENGINE, None))

    def test_the_engine_lines_that_say_the_checks_passed(self):
        for word, words in ENGINE_LOG_WORDS.items():
            with self.subTest(word):
                text = "engine %s %s. Delivery is still proven." % (ENGINE, words)
                self.assertEqual(evidence.passes_checks(text, ENGINE), word != "incompatible")
                self.assertFalse(evidence.passes_checks(text, OLDER))
        self.assertTrue(evidence.passes_checks("engine %s accepted because `codex queue` still offers "
                                               "--thread/--message." % OLDER, OLDER))
        self.assertEqual(records.log_names(config.Paths("x"))[-1], "auto-resume.log")
        self.assertEqual(len(records.log_names(config.Paths("x"))), 6)


class SwitchTests(Case):
    def test_the_pause_is_read_with_the_records(self):
        self.assertIs(read(self.home(fixtures.BASE, enabled=True))["read"]["paused"], False)
        paused = read(self.home(fixtures.BASE, enabled=False))
        self.assertIs(paused["read"]["paused"], True)
        self.assertTrue(paused["body"]["records"], "a pause stops no reading and no writing")
        gone = self.home(fixtures.BASE)
        db = sqlite3.connect(gone.paths.state_dir / "state.sqlite")
        db.execute("DELETE FROM settings")
        db.commit()
        db.close()
        self.assertIsNone(read(gone)["read"]["paused"], "a switch that cannot be read is not read as either")


class WatcherTests(Case):
    def test_a_report_no_reader_may_use_leaves_the_version_to_the_log(self):
        """The raw file the reporter reads is no report core's reader accepts; through the real
        reader_view it says nothing, and the version is the log's, with none of its capabilities."""
        home = self.home(fixtures.BASE, watcher_report=fixtures.watcher(NEWER))
        found = read(home, view=None)
        self.assertEqual(found["engine"], {"current": ENGINE, "from": "log"})
        self.assertEqual(found["body"]["local_checks"]["covers"], ["engine_present", "exact_thread_recovery"])
        stale = compat.unusable_view("stale", engine={"found": True, "version": NEWER})
        self.assertEqual(read(home, view=lambda: stale)["engine"], {"current": ENGINE, "from": "log"})
        self.assertEqual(read(home, view=lambda: None)["engine"]["from"], "log")

    def test_a_report_in_force_names_the_version_and_its_passing_capabilities(self):
        home = self.home(fixtures.BASE, watcher_report=fixtures.watcher())
        found = read(home)
        self.assertEqual(found["engine"], {"current": ENGINE, "from": "watcher_report"})
        self.assertEqual(found["body"]["local_checks"]["covers"],
                         ["engine_present", "exact_thread_recovery", "loaded_state_detection", "usage_probe"])
        self.assertEqual(read(home, OLDER)["body"]["local_checks"]["covers"],
                         ["engine_present", "exact_thread_recovery"], "it says nothing of another version")


class HistoryTests(Case):
    def test_counts_come_from_the_newest_history_or_not_at_all(self):
        found = read(self.home(fixtures.BASE, watcher_report=fixtures.watcher()))
        self.assertEqual(found["read"]["history"], "read")
        self.assertEqual(found["body"]["records"][0]["progress_items"],
                         {"agentMessage": 2, "commandExecution": 0, "fileChange": 1, "mcpToolCall": 0},
                         "generation 10, not 9; and never a kind it does not count")
        absent = read(self.home(fixtures.BASE, watcher_report=fixtures.watcher(), history=False))
        self.assertEqual(absent["read"]["history"], "absent")
        self.assertEqual({str(record["progress_items"]) for record in absent["body"]["records"]}, {"None"})
        moved = self.home(fixtures.BASE, watcher_report=fixtures.watcher())
        db = sqlite3.connect(moved.codex / "thread_history_11.sqlite")
        db.execute("CREATE TABLE thread_items (thread_id, turn_id, item_type)")
        db.commit()
        db.close()
        unreadable = read(moved)
        self.assertEqual(unreadable["read"]["history"], "unreadable", "a newer generation whose schema moved")
        self.assertEqual({str(record["progress_items"]) for record in unreadable["body"]["records"]}, {"None"})


class VocabularyTests(unittest.TestCase):
    def test_the_readers_words_keep_the_editions_rule(self):
        for words in (records.ReadRefusal, records.HistoryRead, records.EngineSource, evidence.Unplaced):
            values = [member.value for member in words]
            self.assertEqual(len(values), len(set(values)), words.__name__)
            for member in words:
                self.assertEqual(member.name, member.value.upper().replace("-", "_"))

    def test_its_words_and_limits_are_the_receiving_sides(self):
        """What the project refuses on arrival, the reader never writes."""
        project = receiver()
        self.assertEqual(evidence.MAX_RECORDS, project.MAX_RECORDS)
        self.assertEqual(evidence.REPORTABLE, tuple(sorted(project.REPORTABLE)))
        self.assertEqual(evidence.GATE, project.GATE)
        self.assertEqual(evidence.OUTCOMES, project.OUTCOMES)
        self.assertEqual(evidence.PROGRESS, project.PROGRESS)
        for mine, theirs in ((evidence.CATEGORIES, project.CATEGORIES), (evidence.STATES, project.STATES),
                             (evidence.REASONS, project.REASONS), (evidence.TURN_STATUSES, project.TURN_STATUSES)):
            self.assertEqual(mine | {evidence.OTHER}, theirs)
        for spelling in ("codex-cli 0.158.0", "0.158.0", "codex-cli 0.159.0-alpha.2", "codex-cli 0.1.0-alpha.3.4",
                         "codex-cli 00.1.0", "codex-cli 0.1.0-alpha.0", "codex-cli 0.1.0-alpha.2.0", "codex-cli 1.2"):
            with self.subTest(spelling):
                mine = evidence.canonical_version(spelling)
                self.assertEqual(mine is not None and project.engine_version(mine),
                                 mine is not None, "anything it writes, the project takes")
                if spelling.startswith("codex-cli ") and project.engine_version(spelling):
                    self.assertEqual(mine, spelling)

    def test_nothing_of_the_rest_of_the_edition_is_imported_but_the_ledgers_bounds(self):
        """So a standard export could take the two modules unchanged (the design's option X)."""
        for path in (PACKAGE / "records.py", PACKAGE / "evidence.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            relative = {(node.level, node.module) for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.level}
            with self.subTest(path.name):
                self.assertLessEqual(relative, {(1, None), (2, "state.journal"), (2, "state.schema")})
        self.assertNotIn("codex_auto_resume_advanced", inspect.getsource(evidence))


if __name__ == "__main__":
    unittest.main()
