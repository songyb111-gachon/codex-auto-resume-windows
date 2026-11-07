"""What the edition reads of Codex's turn history and spawn edges (v0.6.15-beta, codex/turns.py and codex/lineage.py):
kinds and counts, statuses and category words - never a word anyone wrote - from synthetic databases.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from codex_auto_resume import failures
from codex_auto_resume_advanced.codex import lineage, turns
from codex_auto_resume_advanced.codex.lineage import Lineage
from codex_auto_resume_advanced.codex.turns import Turns, TurnsUnavailable

PARENT = "0a1b2c3d-0001-7000-8000-000000000001"
CHILD = "0a1b2c3d-0002-7000-8000-000000000002"
OTHER = "0a1b2c3d-0003-7000-8000-000000000003"
TURN = "0a1b2c3d-00aa-7000-8000-0000000000aa"
LATER = "0a1b2c3d-00bb-7000-8000-0000000000bb"
SENTINEL = "PRIVATE-WORDS-7f3a"
# Columns that hold what a person or Codex wrote.
CONTENT = ("item_json", "error_json", "title", "first_user_message", "preview", "objective", "name", "text")


@contextlib.contextmanager
def opened(path):
    """A connection to one synthetic database, committed and closed - so the folder can be removed."""
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


class CodexHome:
    def __init__(self, root: Path, *, final_column=True):
        self.root = root
        turns_columns = ("thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT, error_json TEXT, "
                         "started_at INTEGER, completed_at INTEGER%s" % (", final_agent_item_id TEXT"
                                                                          if final_column else ""))
        with opened(root / "thread_history_2.sqlite") as db:
            db.execute("CREATE TABLE thread_turns (%s)" % turns_columns)
            db.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal "
                       "INTEGER, item_json TEXT, item_type TEXT)")
        with opened(root / "state_6.sqlite") as db:
            db.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
        self.ordinal = 0

    def turn(self, thread, turn, status="completed", *, error=None, completed=1_790_000_000, final=None, kinds=()):
        self.ordinal += 1
        with opened(self.root / "thread_history_2.sqlite") as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(thread_turns)")]
            values = {"thread_id": thread, "turn_id": turn, "rollout_ordinal": self.ordinal, "status": status,
                      "error_json": None if error is None else json.dumps(error), "started_at": completed - 30,
                      "completed_at": completed, "final_agent_item_id": final}
            db.execute("INSERT INTO thread_turns (%s) VALUES (%s)" % (", ".join(columns), ", ".join("?" for _ in columns)),
                       [values[name] for name in columns])
            for n, kind in enumerate(kinds):
                self.item(db, thread, turn, kind, {"type": kind, "text": SENTINEL})

    def item(self, db, thread, turn, kind, payload):
        self.ordinal += 1
        db.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?)",
                   (thread, turn, "item-%d" % self.ordinal, self.ordinal, json.dumps(payload), kind))

    def plan(self, thread, statuses):
        with opened(self.root / "thread_history_2.sqlite") as db:
            self.item(db, thread, TURN, "plan", {"type": "plan", "steps": [{"step": SENTINEL, "status": status}
                                                                           for status in statuses]})

    def spawned(self, parent, child, status="open"):
        with opened(self.root / "state_6.sqlite") as db:
            db.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (parent, child, status))

    def digest(self):
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.iterdir()}


class ReadsCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = CodexHome(self.root)


class TurnTests(ReadsCase):
    def test_the_latest_turn_says_its_kinds_and_counts_and_nothing_written(self):
        self.home.turn(PARENT, TURN, kinds=("userMessage", "agentMessage"))
        self.home.turn(PARENT, LATER, kinds=("userMessage", "reasoning", "reasoning", "weird-kind!"))
        before = self.home.digest()
        found = Turns(self.root).latest(PARENT)
        self.assertEqual((found.turn_id, found.status, found.errored, found.final_agent),
                         (LATER, "completed", False, False))
        self.assertEqual(found.kinds, {"userMessage": 1, "reasoning": 2, "other": 1})
        self.assertNotIn(SENTINEL, repr(found))
        self.assertEqual(self.home.digest(), before, "read-only")
        self.assertIsNone(Turns(self.root).latest(OTHER))

    def test_the_latest_turn_says_when_it_began(self):
        """v0.6.23 audit seatB:B-R3: steer_send steers only a turn begun before the steer was asked."""
        self.home.turn(PARENT, TURN)
        found = Turns(self.root).latest(PARENT)
        self.assertEqual(found.started_at, found.completed_at - 30)

    def test_an_error_is_only_that_there_was_one(self):
        self.home.turn(PARENT, TURN, "failed", error={"message": SENTINEL})
        found = Turns(self.root).latest(PARENT)
        self.assertTrue(found.errored)
        self.assertNotIn(SENTINEL, repr(found))

    def test_recent_names_only_conversations_that_finished_lately(self):
        self.home.turn(PARENT, TURN, completed=1_790_000_000)
        self.home.turn(CHILD, TURN, completed=1_780_000_000)
        self.home.turn(OTHER, TURN, "failed", completed=1_790_000_100)
        self.assertEqual(Turns(self.root).recent(1_789_999_000), [PARENT])

    def test_a_missing_column_or_a_missing_file_is_unavailable(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        bare = Path(temp.name)
        CodexHome(bare, final_column=False).turn(PARENT, TURN)
        with self.assertRaises(TurnsUnavailable):
            Turns(bare).latest(PARENT)
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with self.assertRaises(TurnsUnavailable):
            Turns(empty.name).latest(PARENT)

    def test_a_linked_database_is_never_opened(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        linked = Path(temp.name)
        try:
            os.symlink(self.root / "thread_history_2.sqlite", linked / "thread_history_9.sqlite")
        except (OSError, NotImplementedError):
            self.skipTest("this account may not make a symbolic link")
        with self.assertRaises(TurnsUnavailable):
            Turns(linked).latest(PARENT)


class PlanTests(ReadsCase):
    def test_statuses_only_and_a_word_of_no_shape_reads_unknown(self):
        self.home.plan(PARENT, ["completed", "in_progress"])
        self.home.plan(PARENT, ["completed", "pending", "skipped", SENTINEL])
        found = Turns(self.root).plan_statuses(PARENT)
        self.assertEqual(found, ("completed", "pending", "unknown", "unknown"), "the newest plan item")
        self.assertIsNone(Turns(self.root).plan_statuses(OTHER), "no plan item")

    def test_a_plan_item_whose_steps_cannot_be_read_is_unavailable(self):
        with opened(self.root / "thread_history_2.sqlite") as db:
            self.home.item(db, PARENT, TURN, "plan", {"type": "plan", "text": SENTINEL})
        with self.assertRaises(TurnsUnavailable):
            Turns(self.root).plan_statuses(PARENT)


class LineageTests(ReadsCase):
    def test_a_child_s_latest_turn_is_its_status_and_category_word(self):
        self.home.spawned(PARENT, CHILD)
        self.home.spawned(PARENT, OTHER)
        self.home.turn(CHILD, TURN, "failed", error={"codexErrorInfo": "usageLimitExceeded", "message": SENTINEL})
        found = Lineage(self.root).children(PARENT)
        self.assertEqual([(child.thread_id, child.status) for child in found], [(CHILD, "failed"), (OTHER, None)])
        self.assertIn(found[0].category, failures.CATEGORIES)
        self.assertNotIn(SENTINEL, repr(found))
        self.assertEqual(Lineage(self.root).children(CHILD), [], "a child's own children are not asked for")

    def test_the_spawn_edges_moved_on_is_unavailable(self):
        with opened(self.root / "state_6.sqlite") as db:
            db.execute("DROP TABLE thread_spawn_edges")
            db.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT)")
        with self.assertRaises(TurnsUnavailable):
            Lineage(self.root).children(PARENT)


class StatementTests(unittest.TestCase):
    """Every statement either module runs selects no content column - but for the plan steps' statuses and a child's
    error, which core's classify drops to a category word at once."""

    @staticmethod
    def selected(statement):
        return re.match(r"SELECT (.*?) FROM ", statement).group(1)

    def test_no_statement_selects_what_anyone_wrote(self):
        for module in (turns, lineage):
            for statement in module.STATEMENTS:
                with self.subTest(statement[:60]):
                    columns = self.selected(statement)
                    allowed = {turns.PLAN: "json_extract(step.value, '$.status')",
                               lineage.CHILD_TURN: None}.get(statement, "")
                    if allowed:
                        self.assertEqual(columns, allowed)
                        continue
                    for name in CONTENT:
                        if statement is lineage.CHILD_TURN and name == "error_json":
                            continue
                        # v0.6.16-beta.4: a failed turn's error, dropped to Codex's code at once (Turns.turn_code).
                        if statement is turns.ERROR and name == "error_json":
                            self.assertEqual(columns, "error_json")
                            continue
                        if statement is turns.LATEST and name == "error_json":
                            self.assertIn("error_json IS NOT NULL", columns, "only whether there is one")
                            continue
                        self.assertNotIn(name, columns)

    def test_item_json_is_read_only_through_the_plan_steps(self):
        for module in (turns, lineage):
            for statement in module.STATEMENTS:
                if "item_json" in statement:
                    self.assertIs(statement, turns.PLAN)

    def test_every_statement_run_is_one_named(self):
        """The modules' SQL is their STATEMENTS: a new read goes there, where these tests see it."""
        for module in (turns, lineage):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for found in re.findall(r"\.execute\((\w+)", source):
                with self.subTest(module=module.__name__, statement=found):
                    self.assertIn(getattr(module, found, None), module.STATEMENTS, found)


if __name__ == "__main__":
    unittest.main()
