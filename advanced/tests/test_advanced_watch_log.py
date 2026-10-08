"""The watch log (v0.6.14, watchlog.py): what a watched capability would have done, read by the
Dashboard over the bridge - answer words, points, counts and minutes only, once for each recovery and
answer, the last 30 days of at most 250 lines a capability - read without writing anything, the
journal's only reader, and nothing a model can reach.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import test_advanced_surfaces  # noqa: E402
from codex_auto_resume import control, diagnostics  # noqa: E402
from codex_auto_resume.domain.plug import ALTERNATIVES, Alternative, Point, Surface  # noqa: E402
from codex_auto_resume_advanced import arming, surfaces, watchlog  # noqa: E402
from codex_auto_resume_advanced.state import WATCH_LIMIT, AdvancedState  # noqa: E402
from codex_auto_resume_advanced.vocabulary import JournalCode, McpTool, Refusal  # noqa: E402

PACKAGE = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
DAY = 86400
RECORD_A = {"interruption_id": ac.KEY, "thread_id": ac.THREAD}
RECORD_B = {"interruption_id": "b" * 64, "thread_id": ac.OTHER_THREAD}


def minute(at):
    return int(at // 60) * 60


class WatchCase(test_advanced_surfaces.SurfaceCase):
    def log(self, capability="test_wake"):
        reply = self.bridge("advanced-watch-log", {"capability": capability})
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    def holding(self, state="shadow"):
        """`test_wake` watched (or on), answering HOLD at the schedule and at the gates; asked three
        times for one recovery and once for another at the schedule, and once at the gates."""
        runtime = self.advanced.runtime
        self.assertTrue(self.arm(runtime, state=state)["done"])
        runtime.states(fresh=True)                   # as the watcher reads it at its next tick
        ac.code_of(runtime).answers = {"schedule": Alternative.HOLD, "gate": Alternative.HOLD}
        for _ in range(3):
            self.advanced.schedule(dict(RECORD_A), self.now)
        self.advanced.schedule(dict(RECORD_B), self.now)
        self.advanced.gate("x", dict(RECORD_A), {})

    def note(self, at, answer=Alternative.HOLD, point=Point.SCHEDULE):
        self.advanced.runtime.state.note(JournalCode.WOULD_HAVE, capability="test_wake", point=point,
                                         answer=answer, at=at)


class ViewTests(WatchCase):
    def test_a_watched_answer_is_counted_once_for_each_recovery_and_answer(self):
        self.holding()
        log = self.log()
        self.assertEqual(log["entries"], [{"answer": "hold", "points": ["gates", "schedule"], "count": 3,
                                           "first": minute(self.now), "last": minute(self.now)}])
        self.assertEqual((log["done"], log["capability"], log["days"], log["watched_since"], log["full"]),
                         (True, "test_wake", 30, minute(self.now), False))

    def test_what_it_did_while_on_is_not_what_it_would_have_done(self):
        self.holding(state="armed")
        log = self.log()
        self.assertTrue(log["done"])
        self.assertEqual((log["entries"], log["watched_since"], log["from"]), ([], None, None))
        codes = {line["code"] for line in self.advanced.runtime.state.journal(limit=5000)}
        self.assertIn(JournalCode.ACTED, codes, "it did act, while on")

    def test_watched_since_and_every_time_are_whole_minutes(self):
        self.now = ac.NOW + 37
        self.holding()
        self.now += 100
        self.note(self.now, Alternative.EARLY)
        log = self.log()
        self.assertEqual(log["watched_since"], ac.NOW)
        by = {entry["answer"]: entry for entry in log["entries"]}
        self.assertEqual((by["hold"]["first"], by["hold"]["last"]), (ac.NOW, ac.NOW))
        self.assertEqual((by["early"]["first"], by["early"]["last"]), (ac.NOW + 120, ac.NOW + 120))
        self.assertEqual(log["from"], ac.NOW)
        for value in (log["watched_since"], log["from"], *(entry[key] for entry in log["entries"]
                                                            for key in ("first", "last"))):
            self.assertIsInstance(value, int)
            self.assertEqual(value % 60, 0)

    def test_thirty_days_back_and_no_more(self):
        self.holding()
        self.now += 29 * DAY
        self.assertEqual(self.log()["entries"][0]["count"], 3)
        self.now += 2 * DAY
        log = self.log()
        self.assertEqual((log["entries"], log["from"], log["full"]), ([], None, False))
        self.assertEqual(log["watched_since"], minute(ac.NOW), "still watched: only the answers are older")

    def test_a_full_log_says_from_when_it_counts(self):
        self.assertTrue(self.arm(self.advanced.runtime, state="shadow")["done"])
        start = self.now - WATCH_LIMIT * 60
        for index in range(WATCH_LIMIT):
            self.note(start + index * 60)
        log = self.log()
        self.assertEqual((log["full"], log["from"]), (True, minute(start)))
        self.assertEqual(sum(entry["count"] for entry in log["entries"]), WATCH_LIMIT)

    def test_it_counts_what_the_bound_keeps_even_before_a_prune_pass_has_run(self):
        """Between two passes the journal can hold more than the bound: the log counts the newest
        WATCH_LIMIT all the same, and says from when."""
        self.assertTrue(self.arm(self.advanced.runtime, state="shadow")["done"])
        state = self.advanced.runtime.state
        connection = sqlite3.connect(state.path)
        self.addCleanup(connection.close)
        start = self.now - (WATCH_LIMIT + 30) * 60
        connection.executemany("INSERT INTO journal (at, capability, code, point, answer) "
                               "VALUES (?, 'test_wake', 'would_have', 'schedule', 'hold')",
                               [(start + index * 60,) for index in range(WATCH_LIMIT + 30)])
        connection.commit()
        log = self.log()
        self.assertEqual(log["entries"][0]["count"], WATCH_LIMIT)
        self.assertEqual((log["full"], log["from"], log["entries"][0]["first"]),
                         (True, minute(start + 30 * 60), minute(start + 30 * 60)))

    def test_a_log_at_the_bound_with_older_answers_outside_the_window_lets_none_of_the_window_go(self):
        """At the bound, but its oldest lines older than 30 days: what the window holds is all there
        was in it, so the page says nothing of answers let go."""
        self.assertTrue(self.arm(self.advanced.runtime, state="shadow")["done"])
        for index in range(WATCH_LIMIT - 10):
            self.note(self.now - 60 * DAY + index * 60)
        for index in range(10):
            self.note(self.now - 3600 + index * 60)
        log = self.log()
        self.assertEqual((log["entries"][0]["count"], log["full"], log["from"]), (10, False, minute(self.now - 3600)))

    def test_a_word_the_log_does_not_name_reads_as_null(self):
        self.assertTrue(self.arm(self.advanced.runtime, state="shadow")["done"])
        connection = sqlite3.connect(self.advanced.runtime.state.path)
        self.addCleanup(connection.close)
        connection.execute("INSERT INTO journal (at, capability, code, point, answer) "
                           "VALUES (?, 'test_wake', 'would_have', 'records', 'records')", (self.now,))
        connection.commit()
        self.note(self.now, Alternative.EARLY)
        self.assertEqual(self.log()["entries"], [
            {"answer": "early", "points": ["schedule"], "count": 1, "first": minute(self.now), "last": minute(self.now)},
            {"answer": None, "points": ["records"], "count": 1, "first": minute(self.now), "last": minute(self.now)}])

    def test_it_answers_with_no_id_and_no_word(self):
        self.holding()
        log = self.log()
        self.assertTrue(log["done"])
        self.assertTrue(log["entries"])
        written = json.dumps(log)
        for secret in (ac.KEY, ac.THREAD, "b" * 64, ac.OTHER_THREAD):
            self.assertNotIn(secret, written)
        self.assertEqual(set(log), {"done", "capability", "days", "watched_since", "entries", "from", "full"})
        for entry in log["entries"]:
            self.assertEqual(set(entry), {"answer", "points", "count", "first", "last"})

    def test_an_unknown_capability_and_an_argument_it_does_not_take_are_refused(self):
        for argument in ({"capability": "nope"}, {"capability": 5}, {}):
            with self.subTest(argument):
                self.assertEqual(self.bridge("advanced-watch-log", argument)["result"],
                                 {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY})
        self.assertEqual(self.bridge("advanced-watch-log", {"capability": "test_wake", "locale": "ko"})["result"],
                         {"done": False, "refusal": Refusal.INVALID_REQUEST})

    def test_a_state_that_cannot_be_read_is_refused_and_nothing_is_reset(self):
        self.holding()
        with patch.object(AdvancedState, "journal", side_effect=watchlog.StateError("x")):
            self.assertEqual(self.log(), {"done": False, "refusal": Refusal.STATE_UNAVAILABLE})
        self.assertEqual(self.log()["entries"][0]["count"], 3)

    def test_reading_it_makes_nothing_and_writes_nothing(self):
        before = sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*"))
        log = self.log()
        self.assertEqual((log["done"], log["entries"], log["watched_since"]), (True, [], None))
        self.assertEqual(sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*")), before)
        self.assertFalse(Path(self.paths.advanced_dir).exists())

        self.holding()
        self.advanced.runtime.state.close()
        path = Path(self.advanced.runtime.state.path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        refuse = AssertionError("a read of the watch log wrote or decided")
        with patch.object(AdvancedState, "_transaction", side_effect=refuse), \
                patch.object(arming.Arming, "read", side_effect=refuse), \
                patch.object(arming.Arming, "current", side_effect=refuse):
            log = self.log()
        self.assertEqual((log["done"], log["entries"][0]["count"]), (True, 3))
        self.advanced.runtime.state.close()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


class ExportTests(WatchCase):
    def shown(self):
        return surfaces.answer(self.advanced.runtime, Surface.DIAGNOSTICS, {})

    def test_the_export_carries_the_watch_log_only_where_there_is_one(self):
        self.assertEqual(self.shown(), {"edition": "advanced", "on": 0})
        self.holding()
        at = minute(self.now)
        self.assertEqual(self.shown()["watch"], [
            {"capability": "test_wake", "watched_since": at, "from": at, "full": False,
             "entries": [{"answer": "hold", "points": ["gates", "schedule"], "count": 3, "first": at, "last": at}]}])
        for surface in (Surface.STATUS, Surface.TRAY):
            with self.subTest(surface):
                self.assertNotIn("watch", surfaces.answer(self.advanced.runtime, surface, {}))

    def test_it_lists_the_watched_and_those_with_answers_in_the_registry_s_order_and_no_other(self):
        definitions = (ac.definition(id="test_off", journal_prefix="to"),
                       ac.definition(id="test_nap", journal_prefix="tn"), ac.definition())
        where = tempfile.TemporaryDirectory()
        self.addCleanup(where.cleanup)
        self.catalogs = ac.catalogs(where.name, *definitions)
        self.advanced = self.plug(*definitions)
        self.control = control.Control(self.paths, plug=self.advanced)
        runtime = self.advanced.runtime
        self.assertTrue(self.arm(runtime, capability="test_wake", state="shadow")["done"])
        self.assertTrue(self.arm(runtime, capability="test_nap", state="shadow")["done"])
        self.note(self.now)
        self.assertTrue(self.arm(runtime, capability="test_nap", state="armed",
                                 generation=runtime.state.meta()["generation"])["done"])
        self.advanced.runtime.state.note(JournalCode.WOULD_HAVE, capability="test_nap", point=Point.TEXT,
                                         answer=Point.TEXT, at=self.now)
        at = minute(self.now)
        self.assertEqual(self.shown()["watch"], [
            {"capability": "test_nap", "watched_since": None, "from": at, "full": False,
             "entries": [{"answer": "text", "points": ["text"], "count": 1, "first": at, "last": at}]},
            {"capability": "test_wake", "watched_since": at, "from": at, "full": False,
             "entries": [{"answer": "hold", "points": ["schedule"], "count": 1, "first": at, "last": at}]}])

    def test_the_export_s_watch_log_has_nothing_to_redact(self):
        """Core's own redactor (diagnostics.py) finds nothing in it to alias: no id, no path, no name.
        The machine's user name is pinned, since the redactor replaces it wherever it appears."""
        self.holding()
        shown = self.shown()
        self.assertTrue(shown["watch"])
        with patch.dict(os.environ, {"USERNAME": "ExampleUser"}):
            self.assertEqual(diagnostics._redacted(shown, diagnostics.Redactor()), shown)
        written = json.dumps(shown)
        for secret in (ac.KEY, ac.THREAD, "b" * 64, ac.OTHER_THREAD):
            self.assertNotIn(secret, written)
        self.assertIn('"capability": "test_wake"', written)

    def test_a_state_that_cannot_be_read_costs_the_export_nothing(self):
        self.holding()
        self.assertIn("watch", self.shown())
        with patch.object(AdvancedState, "journal", side_effect=watchlog.StateError("x")):
            self.assertEqual(self.shown(), {"edition": "advanced", "on": 0})
        with patch.object(watchlog, "exported", side_effect=RuntimeError("x")):
            self.assertEqual(self.shown(), {"edition": "advanced", "on": 0})


class GuardTests(WatchCase):
    def test_only_the_watch_log_reads_the_journal(self):
        """D4: the journal is shown, and never read to decide anything."""
        readers, importers = set(), set()
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "journal":
                    readers.add(path.relative_to(PACKAGE).as_posix())
                if isinstance(node, ast.ImportFrom) and (
                        (node.module or "").endswith("watchlog")
                        or any(alias.name == "watchlog" for alias in node.names)):
                    importers.add(path.relative_to(PACKAGE).as_posix())
                if isinstance(node, ast.Import) and any(alias.name.endswith("watchlog") for alias in node.names):
                    importers.add(path.relative_to(PACKAGE).as_posix())
        self.assertEqual(readers, {"watchlog.py"})
        self.assertEqual(importers, {"surfaces.py"})

    def test_a_model_reaches_none_of_it(self):
        self.holding()
        self.assertEqual(self.log()["entries"][0]["count"], 3, "the Dashboard reads it")
        (reply,) = self.converse({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = [tool["name"] for tool in reply["result"]["tools"]]
        self.assertEqual(names[len(test_advanced_surfaces.CORE_TOOLS):], [str(tool) for tool in McpTool])
        with patch.object(watchlog, "view", side_effect=AssertionError("a model read the watch log")) as viewed:
            for name, arguments in (("advanced-watch-log", {"capability": "test_wake"}),
                                    ("list_advanced_capabilities", {"capability": "test_wake"})):
                with self.subTest(name):
                    refused = self.call(name, arguments)
                    self.assertTrue("error" in refused or refused["result"].get("isError"), refused)
            listing = self.call("list_advanced_capabilities")["result"]
            self.assertFalse(listing.get("isError"))
            (item,) = listing["structuredContent"]["capabilities"]
            self.assertEqual(item["state"], "shadow")
            self.assertFalse({"entries", "watch", "watched_since", "full"} & set(item))
            self.call("disarm_advanced_capability", {"capability": "test_wake"})
            self.call("disarm_all_advanced")
            viewed.assert_not_called()
        named = {node.id for node in ast.walk(ast.parse(inspect.getsource(surfaces.mcp)))
                 if isinstance(node, ast.Name)}
        named |= {node.attr for node in ast.walk(ast.parse(inspect.getsource(surfaces.mcp)))
                  if isinstance(node, ast.Attribute)}
        self.assertFalse({"watchlog", "view"} & named)

    def test_every_answer_a_watched_capability_can_give_is_a_word_the_log_names(self):
        """The points the plug asks the runtime at, and the tick, less those that answer with an
        alternative, are the points whose answer is a value: the journal writes their names. A new
        point that answers with a value fails here until the log has a word for it."""
        tree = ast.parse((PACKAGE / "plug.py").read_text(encoding="utf-8"))
        asked = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "ask" \
                    and node.args and isinstance(node.args[0], ast.Attribute) \
                    and isinstance(node.args[0].value, ast.Name) and node.args[0].value.id == "Point":
                asked.add(Point[node.args[0].attr])
        self.assertIn(Point.GATES, asked)
        self.assertEqual((asked | {Point.TICK}) - set(ALTERNATIVES), set(watchlog.VALUE_POINTS))
        self.assertEqual(set(watchlog.WORDS), set(Alternative) | set(watchlog.VALUE_POINTS))
        self.assertEqual(len(watchlog.WORDS), len(set(watchlog.WORDS)))


if __name__ == "__main__":
    unittest.main()
