"""Usage and token analytics (v0.6.20, plans/v0619-design/D-analytics.md): the capability's definition, its pass over
the rollouts at P8 into token_days and token_files, the meter's samples while it stands on, the narrower route where
MTOK failed, the 90-day bound - and that nothing core decides or any gate of this edition reads any of it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests -p test_advanced_analytics.py
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_usage import Session, reply  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.codex import tokens  # noqa: E402
from codex_auto_resume_advanced.engine import analytics  # noqa: E402
from codex_auto_resume_advanced.registry import USAGE_ANALYTICS, USAGE_METER  # noqa: E402
from codex_auto_resume_advanced.state import StateError  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, Measurement, OptionKey,  # noqa: E402
                                                   Verdict)

ADVANCED = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
T1 = "0199a000-0000-7000-8000-0000000000a1"
T2 = "0199a000-0000-7000-8000-0000000000a2"
T3 = "0199a000-0000-7000-8000-0000000000a3"
PROJECT_A, PROJECT_B = "a" * 64, "b" * 64
SECRET = "SECRET-WORDS-OF-A-PROMPT"


def stamp(at):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at))


def rollout(path, thread, events, cwd="C:\\work\\Example"):
    """A rollout: its first line naming `thread`, then a token_count event (and a turn begun) for each (at, numbers)."""
    lines = [{"timestamp": stamp(ac.NOW), "type": "session_meta", "payload": {"id": thread, "cwd": cwd}}]
    total = [0, 0, 0, 0]
    for at, numbers in events:
        total = [a + b for a, b in zip(total, numbers)]
        usage = lambda values: dict(zip(tokens.KINDS + ("total_tokens",), values + [sum(values)]))
        lines.append({"timestamp": stamp(at), "type": "event_msg", "payload": {"type": "task_started"}})
        lines.append({"timestamp": stamp(at), "type": "response_item", "payload": {"text": SECRET}})
        lines.append({"timestamp": stamp(at), "type": "event_msg", "payload": {
            "type": "token_count", "info": {"last_token_usage": usage(numbers), "total_token_usage": usage(total)}}})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        for line in lines if not path.exists() or path.stat().st_size == 0 else lines[1:]:
            stream.write(json.dumps(line).encode("utf-8") + b"\n")
    return path


class FakeSource:
    """Core's reader of one Codex home, as far as the ingest asks it: a conversation's project key."""
    KEYS = {T1: PROJECT_A, T2: PROJECT_A, T3: None}

    def __init__(self, home):
        self.home = home

    def project_key(self, thread):
        return self.KEYS.get(thread)


def _view():
    return {"status": "ok", "engine": {"found": True, "version": ac.ENGINE},
            "capabilities": {"usage_probe": {"state": "COMPATIBLE", "reason": "local_checks_passed"}}}


class AnalyticsCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = _view()
        self.rt = self.runtime(USAGE_METER, USAGE_ANALYTICS)
        self.rt.arming.catalogs = statement.CATALOGS
        self.answer, self.calls = reply(), []
        meter = self.rt._code_of(USAGE_METER)
        meter._session = lambda: Session(self.answer, self.calls)
        meter._app_running = lambda: True
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.codex = Path(folder.name) / "codex-home"
        self.sessions = self.codex / "sessions" / "2027" / "01" / "15"
        self.sessions.mkdir(parents=True)
        code = self.rt._code_of(USAGE_ANALYTICS)
        code._homes = lambda: [self.codex]
        code._source = FakeSource
        code._local = time.gmtime

    def on(self, capability):
        definition = self.rt.registry.get(capability)
        also = [{"capability": other, "revision": self.rt.registry.get(other).revision,
                 "warnings": [str(w) for w in self.rt.arming.warnings(self.rt.registry.get(other))],
                 "engine_version": ac.ENGINE}
                for other in self.rt.registry.requires(capability)
                if self.rt.arming.current().get(other) != ArmingState.ARMED]
        result = self.rt.arming.arm(capability, state="armed", revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)],
                                    also=also or None, actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def look(self):
        answer = self.rt.tick(None)
        if answer is not DEFER:
            answer.run(lambda: None)
        self.rt.states(fresh=True)

    def days(self):
        return {(row["day"], row["thread_id"]): (row["project_digest"], row["input"], row["cached"], row["output"],
                                                 row["reasoning"], row["turns"]) for row in self.rt.state.token_days()}

    def file(self, thread):
        return self.sessions / ("rollout-2027-01-15T00-00-00-%s.jsonl" % thread)


class DefinitionTests(unittest.TestCase):
    def test_it_departs_rests_and_needs_what_the_design_says(self):
        self.assertEqual(USAGE_ANALYTICS.departs_from, ("B6", "C4", "C9", "D2", "F3"))
        self.assertEqual((USAGE_ANALYTICS.points, USAGE_ANALYTICS.compat, USAGE_ANALYTICS.requires),
                         (frozenset({Point.TICK}), "usage_probe", ("usage_meter",)))
        self.assertEqual(USAGE_ANALYTICS.measurements, (Measurement.MTOK, Measurement.MU))
        self.assertEqual((USAGE_ANALYTICS.ceilings.per_day, USAGE_ANALYTICS.ceilings.per_conversation), (1, 1))
        self.assertEqual(USAGE_ANALYTICS.codes, ("ingested", "capped", "unreadable"))
        self.assertEqual(USAGE_ANALYTICS.option(OptionKey.ANALYTICS_DAYS).choices, (7, 30, 90))
        self.assertIn("usage_analytics", registry.REGISTRY.ids)
        self.assertEqual(statement.CATALOGS.missing(USAGE_ANALYTICS), [])

    def test_it_is_shown_right_after_keep_going_and_answers_at_p8_before_the_wake_timer(self):
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index("keep_going") + 1], "usage_analytics")
        # The wake timer stays last at P8, so its errand reads the due times the others' errands kept.
        self.assertEqual([d.id for d in registry.REGISTRY.at(Point.TICK)][-2:], ["usage_analytics", "wake_for_reset"])

    def test_its_route_is_the_rollouts_unless_mtok_failed(self):
        self.assertEqual((analytics.route("pass"), analytics.route(None), analytics.route("fail")),
                         ("per_day", "per_day", "lifetime"))


class IngestTests(AnalyticsCase):
    def test_off_nothing_is_read_and_no_sample_is_kept(self):
        rollout(self.file(T1), T1, [(ac.NOW - 60, [10, 2, 3, 1])])
        self.on("usage_meter")
        self.look()
        self.assertEqual(self.rt.state.token_days(), [])
        self.assertEqual(self.rt.state.token_files(), {})
        self.assertEqual(self.rt.state.usage_samples(), [])
        self.assertTrue(self.rt.state.meter())                 # the meter alone reads as it always did

    def test_a_pass_keeps_the_numbers_by_day_under_the_project_key_and_where_each_file_stands(self):
        day = time.strftime("%Y-%m-%d", time.gmtime(ac.NOW))
        yesterday = time.strftime("%Y-%m-%d", time.gmtime(ac.NOW - 86400))
        rollout(self.file(T1), T1, [(ac.NOW - 86400, [100, 40, 20, 5]), (ac.NOW - 60, [10, 2, 3, 1])])
        rollout(self.file(T2), T2, [(ac.NOW - 30, [7, 0, 7, 0])])
        rollout(self.file(T3), T3, [(ac.NOW - 30, [1, 1, 1, 1])], cwd="D:\\elsewhere\\Other")
        self.on("usage_analytics")
        self.look()
        found = self.days()
        self.assertEqual(found[(yesterday, T1)], (PROJECT_A[:16], 100, 40, 20, 5, 1))
        self.assertEqual(found[(day, T1)], (PROJECT_A[:16], 10, 2, 3, 1, 1))
        self.assertEqual(found[(day, T2)], (PROJECT_A[:16], 7, 0, 7, 0, 1))
        # No key from core: the digest of the folder the rollout names, never the folder.
        self.assertRegex(found[(day, T3)][0], r"\A[0-9a-f]{16}\Z")
        self.assertNotEqual(found[(day, T3)][0], PROJECT_A[:16])
        files = self.rt.state.token_files()
        self.assertEqual(sorted(row["thread_id"] for row in files.values()), sorted([T1, T2, T3]))
        for key, row in files.items():
            self.assertRegex(key, r"\A[0-9a-f]{16}\Z")
            self.assertEqual(row["offset"], row["size"])
        self.assertEqual(self.rt.state.stamped("usage_analytics", OptionKey.LAST_INGEST), int(ac.NOW))
        self.assertIn("analytic.ingested", [row["code"] for row in self.rt.state.journal(capability="usage_analytics")])

    def test_a_pass_runs_at_most_every_ten_minutes_and_adds_only_what_is_new(self):
        rollout(self.file(T1), T1, [(ac.NOW - 60, [10, 0, 1, 0])])
        self.on("usage_analytics")
        self.look()
        rollout(self.file(T1), T1, [(ac.NOW + 30, [5, 0, 5, 0])])
        self.now += 300
        self.look()
        self.assertEqual(sum(row["input"] for row in self.rt.state.token_days()), 10)
        self.now += analytics.INGEST_EVERY
        self.look()
        self.assertEqual(sum(row["input"] for row in self.rt.state.token_days()), 15)
        self.assertEqual(sum(row["turns"] for row in self.rt.state.token_days()), 2)

    def test_watched_it_reads_nothing(self):
        rollout(self.file(T1), T1, [(ac.NOW - 60, [10, 0, 1, 0])])
        self.on("usage_meter")
        definition = self.rt.registry.get("usage_analytics")
        result = self.rt.arming.arm("usage_analytics", state="shadow", revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)
        self.look()
        self.assertEqual((self.rt.state.token_days(), self.rt.state.usage_samples()), ([], []))

    def test_where_mtok_failed_no_rollout_is_read(self):
        self.measured = {Measurement.MTOK: (Verdict.FAIL, ac.ENGINE)}
        rollout(self.file(T1), T1, [(ac.NOW - 60, [10, 0, 1, 0])])
        self.on("usage_analytics")
        self.look()
        self.assertEqual((self.rt.state.token_days(), self.rt.state.token_files()), ([], {}))
        self.assertEqual(self.rt.state.stamped("usage_analytics", OptionKey.LAST_INGEST), int(ac.NOW))

    def test_a_pass_stops_at_its_byte_budget_and_the_next_goes_on(self):
        for index, thread in enumerate((T1, T2, T3)):
            rollout(self.file(thread), thread, [(ac.NOW - 60 - index, [1, 0, 0, 0])] * 50)
        size = self.file(T1).stat().st_size
        self.on("usage_analytics")
        from unittest import mock
        with mock.patch.object(tokens, "PASS_BYTES", size + 10):
            self.look()
            first = len(self.rt.state.token_files())
            self.assertLess(first, 3)
            self.assertIn("analytic.capped", [row["code"] for row in self.rt.state.journal(capability="usage_analytics")])
            self.now += analytics.INGEST_EVERY
            self.look()
            self.now += analytics.INGEST_EVERY
            self.look()
        self.assertEqual(len(self.rt.state.token_files()), 3)
        self.assertEqual(sum(row["input"] for row in self.rt.state.token_days()), 150)


class SampleTests(AnalyticsCase):
    def test_the_meter_keeps_each_reading_as_a_sample_only_while_the_analytics_stand_on(self):
        self.on("usage_meter")
        self.look()
        self.assertEqual(self.rt.state.usage_samples(), [])
        self.on("usage_analytics")
        self.now += 15 * 60
        self.answer = reply(five=42.0, week=21.0)
        self.look()
        samples = self.rt.state.usage_samples()
        self.assertEqual(sorted((row["minutes"], row["used_percent"]) for row in samples), [(300, 42.0), (10080, 21.0)])
        self.assertEqual({row["at"] for row in samples}, {self.now})

    def test_only_the_meter_writes_samples_and_only_the_analytics_their_numbers(self):
        state = self.rt.state
        self.on("usage_analytics")
        meter_view = state.scoped("usage_meter", on=lambda: True, armed=lambda other: False)
        with self.assertRaises(StateError):
            meter_view.analytics.sample([{"bucket": "codex", "window_minutes": 300, "used_percent": 5.0}])
        own = state.scoped("usage_analytics", on=lambda: True, armed=lambda other: True)
        with self.assertRaises(StateError):
            own.analytics.sample([{"bucket": "codex", "window_minutes": 300, "used_percent": 5.0}])
        other = state.scoped("keep_going", on=lambda: True, armed=lambda other: True)
        with self.assertRaises(StateError):
            other.analytics.ingest("0" * 16, T1, size=1, offset=1, mtime_ns=1, days={}, project_key=None)
        off = state.scoped("usage_analytics", on=lambda: False)
        with self.assertRaises(StateError):
            off.analytics.ingest("0" * 16, T1, size=1, offset=1, mtime_ns=1, days={}, project_key=None)


class BoundTests(AnalyticsCase):
    def test_the_journals_pass_drops_what_is_older_than_ninety_days(self):
        state = self.rt.state
        old_day = time.strftime("%Y-%m-%d", time.gmtime(ac.NOW - 100 * 86400))
        new_day = time.strftime("%Y-%m-%d", time.gmtime(ac.NOW - 10 * 86400))
        for key, day, age in (("1" * 16, old_day, 100), ("2" * 16, new_day, 10)):
            state.ingest_file(key, T1, size=1, offset=1, mtime_ns=1, days={day: [1, 1, 1, 1, 1]}, project_key=None,
                              at=ac.NOW - age * 86400)
        state.add_samples([{"bucket": "codex", "window_minutes": 300, "used_percent": 1.0, "reset_at": None}],
                          at=ac.NOW - 100 * 86400)
        with state._transaction() as connection:
            state._prune(connection, ac.NOW)
        self.assertEqual([row["day"] for row in state.token_days()], [new_day])
        self.assertEqual(list(state.token_files()), ["2" * 16])
        self.assertEqual(state.usage_samples(), [])

    def test_a_row_of_the_wrong_shape_is_refused(self):
        state = self.rt.state
        for bad in ({"file_key": "nothex"}, {"thread_id": T1.upper()}, {"project_key": "x" * 16},
                    {"days": {"2027-1-1": [1, 1, 1, 1, 1]}}, {"days": {"2027-01-01": [1, 1, 1, -1, 1]}}):
            arguments = dict(file_key="3" * 16, thread_id=T1, size=1, offset=1, mtime_ns=1,
                             days={"2027-01-01": [1, 1, 1, 1, 1]}, project_key=None)
            arguments.update(bad)
            with self.subTest(bad=bad), self.assertRaises(StateError):
                state.ingest_file(arguments.pop("file_key"), arguments.pop("thread_id"), **arguments)


class StructureTests(unittest.TestCase):
    """No gate, dispatch or plug answer reads the analytics (E11): only their own modules, the schema and the journal's
    bound name the three tables or import the engine and the reader, and core names none of them."""
    TABLES = re.compile(r"\b(token_days|token_files|usage_samples)\b")
    READERS = re.compile(r"(engine\.analytics|engine import [^\n]*\banalytics\b|codex\.tokens|codex import "
                         r"[^\n]*\btokens\b|from \.analytics import|from \.tokens import)")
    OWN = {"state/analytics.py", "state/schema.py", "state/journal.py", "engine/analytics.py", "control/analytics.py",
           "codex/tokens.py", "registry.py"}

    def test_only_the_analytics_own_modules_read_their_tables(self):
        for path in sorted(ADVANCED.rglob("*.py")):
            name = path.relative_to(ADVANCED).as_posix()
            text = path.read_text(encoding="utf-8")
            if name in self.OWN or name == "state/__init__.py" or name == "state/choices.py" or name == "surfaces.py":
                continue
            with self.subTest(name):
                self.assertIsNone(self.TABLES.search(text), "names an analytics table")
                self.assertIsNone(self.READERS.search(text), "imports the analytics")
        core = ac.ROOT / "src" / "codex_auto_resume"
        for path in sorted(core.rglob("*.py")):
            with self.subTest(path.relative_to(core).as_posix()):
                self.assertIsNone(self.TABLES.search(path.read_text(encoding="utf-8")))

    def test_the_handle_and_the_bridge_are_the_only_ways_in(self):
        """state/choices.py hands the handle to a capability's view; surfaces.py routes the Dashboard's two commands to
        control/analytics.py - neither reads a table itself."""
        for name in ("state/choices.py", "surfaces.py", "state/__init__.py"):
            with self.subTest(name):
                self.assertIsNone(self.TABLES.search((ADVANCED / name).read_text(encoding="utf-8")))

    def test_no_text_column_holds_anything_but_a_checked_shape(self):
        from codex_auto_resume_advanced.state import schema
        connection = sqlite3.connect(":memory:")
        for created in schema._STATEMENTS_V019:
            if any(table in created for table in ("usage_samples", "token_days", "token_files")) \
                    and created.lstrip().upper().startswith("CREATE TABLE"):
                connection.execute(created)
        for table in ("usage_samples", "token_days", "token_files"):
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
            texts = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % table) if row[2].upper() == "TEXT"]
            with self.subTest(table):
                self.assertLessEqual(set(texts), {"bucket", "day", "thread_id", "project_digest", "file_digest"})
                for column in texts:
                    self.assertRegex(sql, r"%s\b[^,]*CHECK" % column, column)


class LabelSource(FakeSource):
    """Core's reader as the card asks it: labels, lifetime totals and project keys."""
    NAMES = {T1: ("Release notes", "Example project", "example"), T2: (None, None, "example-folder"),
             T3: ("Elsewhere", None, None)}
    LIFETIME = {T1: 999, T2: 5000, T3: 7000}

    def identity(self, thread):
        name, project, base = self.NAMES.get(thread, (None, None, None))
        return {"name": name, "project": project, "cwd_basename": base}

    def task_facts(self, thread, *, fingerprint=False, tokens=False):
        return {"print": None, "tokens": self.LIFETIME.get(thread)}


class AggregationCase(AnalyticsCase):
    def setUp(self):
        super().setUp()
        from unittest import mock
        from codex_auto_resume_advanced.control import analytics as control
        self.control = control
        self.recent = []
        for name, value in (("_homes", lambda runtime: [self.codex]), ("_source", LabelSource),
                            ("_recent", lambda home, since: list(self.recent))):
            patcher = mock.patch.object(control, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def day(self, ago_days):
        return time.strftime("%Y-%m-%d", time.localtime(self.now - ago_days * 86400))

    def put(self, key, thread, day, numbers, project):
        self.rt.state.ingest_file(key, thread, size=1, offset=1, mtime_ns=1, days={day: numbers}, project_key=project)


class AggregationTests(AggregationCase):
    def test_off_the_card_is_refused_and_a_day_count_not_on_offer_too(self):
        self.assertEqual(self.control.view(self.rt)["refusal"], "not_on")
        self.on("usage_analytics")
        self.assertEqual(self.control.view(self.rt, 8)["refusal"], "invalid_request")

    def test_each_project_sums_its_conversations_over_the_days_chosen_with_labels_resolved_now(self):
        self.on("usage_analytics")
        a, b = PROJECT_A[:16], PROJECT_B[:16]
        self.put("1" * 16, T1, self.day(0), [100, 10, 20, 2, 3], a)
        self.put("2" * 16, T2, self.day(6), [50, 5, 10, 1, 1], a)
        self.put("3" * 16, T3, self.day(1), [7, 0, 7, 0, 1], b)
        self.put("4" * 16, T1, self.day(8), [1000, 0, 0, 0, 9], a)      # before the last 7 days
        found = self.control.view(self.rt)
        self.assertTrue(found["done"], found)
        self.assertEqual((found["days"], found["route"], found["choices"]), (7, "per_day", [7, 30, 90]))
        first, second = found["projects"]
        self.assertEqual((first["key"], first["label"], first["input"], first["cached"], first["output"],
                          first["reasoning"], first["turns"]), (a, "Example project", 150, 15, 30, 3, 4))
        self.assertEqual([(item["thread_id"], item["label"]) for item in first["conversations"]],
                         [(T1, "Release notes"), (T2, None)])
        self.assertEqual((second["key"], second["label"], second["input"]), (b, None, 7))
        self.assertEqual((found["total"]["input"], found["total"]["turns"], found["total"]["lifetime"]), (157, 5, None))
        thirty = self.control.view(self.rt, 30)
        self.assertEqual(thirty["projects"][0]["input"], 1150)
        # Nothing of a label is kept: the state holds digests and numbers alone.
        dump = json.dumps(self.rt.state.token_days())
        self.assertNotIn("Example", dump)

    def test_the_days_are_local_days_counted_back_from_today(self):
        utc_day = lambda at: time.gmtime(at)
        east = lambda at: time.gmtime(at + 13 * 3600)
        now = 1_800_000_000 - 1_800_000_000 % 86400 + 12 * 3600 + 1800     # 12:30 UTC
        self.assertEqual(self.control.first_day(now, 1, utc_day), time.strftime("%Y-%m-%d", time.gmtime(now)))
        self.assertEqual(self.control.first_day(now, 7, utc_day), time.strftime("%Y-%m-%d", time.gmtime(now - 6 * 86400)))
        self.assertEqual(self.control.first_day(now, 1, east), time.strftime("%Y-%m-%d", time.gmtime(now + 86400)))

    def test_a_conversation_the_rollouts_gave_nothing_for_shows_its_lifetime_total(self):
        self.on("usage_analytics")
        self.put("1" * 16, T1, self.day(0), [100, 10, 20, 2, 3], PROJECT_A[:16])
        self.recent = [T1, T3]
        found = self.control.view(self.rt)
        lifetime = [project for project in found["projects"] if project["lifetime"] is not None]
        self.assertEqual([(project["key"], project["lifetime"]) for project in lifetime], [(None, 7000)])
        self.assertEqual(lifetime[0]["conversations"][0]["label"], "Elsewhere")
        self.assertEqual(found["total"]["lifetime"], 7000)

    def test_where_mtok_failed_the_card_shows_lifetime_totals_alone(self):
        self.measured = {Measurement.MTOK: (Verdict.FAIL, ac.ENGINE)}
        self.on("usage_analytics")
        self.put("1" * 16, T1, self.day(0), [100, 10, 20, 2, 3], PROJECT_A[:16])
        self.recent = [T1, T2]
        found = self.control.view(self.rt)
        self.assertEqual((found["route"], found["measured"]), ("lifetime", "fail"))
        self.assertEqual([(project["key"], project["input"], project["lifetime"]) for project in found["projects"]],
                         [(PROJECT_A[:16], 0, 5999)])
        self.assertFalse(found["behind"])

    def test_the_pace_of_each_window_the_meter_read(self):
        self.on("usage_analytics")
        for minutes_ago, five in ((30, 50.0), (15, 55.0), (0, 60.0)):
            self.now = ac.NOW - minutes_ago * 60
            self.answer = reply(five=five, five_reset=int(ac.NOW) + 10800, week_reset=int(ac.NOW) + 86400)
            self.rt._code_of(USAGE_METER)._looked = None
            with self.rt.state._transaction() as connection:
                connection.execute("UPDATE meter SET read_at = 0")
            self.look()
        found = self.control.view(self.rt)
        paces = {item["minutes"]: item for item in found["paces"]}
        self.assertEqual(sorted(paces), [300, 10080])
        self.assertEqual(paces[300]["used"], 60.0)
        self.assertTrue(paces[300]["enough"])
        # Ten points in thirty minutes: at 60, full in two hours - before the reset in three.
        self.assertEqual(paces[300]["eta"], int(ac.NOW) + 7200)
        self.assertIsNone(paces[10080]["eta"])                 # flat: no estimate

    def test_older_conversations_still_being_read_are_said(self):
        self.on("usage_analytics")
        rollout(self.file(T1), T1, [(ac.NOW - 60, [1, 0, 0, 0])])
        from unittest import mock
        with mock.patch.object(tokens, "PASS_BYTES", 10):
            self.assertTrue(self.control.view(self.rt)["behind"])
        self.assertFalse(self.control.view(self.rt)["behind"])


if __name__ == "__main__":
    unittest.main()
