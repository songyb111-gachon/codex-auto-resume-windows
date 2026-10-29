"""The state marked readable from a version (v0.6.18), as advanced.sqlite has been since v0.6.17.

PRAGMA application_id holds store/schema.py MARK with the schema that wrote the mark (bits 8-15) and
the oldest version whose reader may use the state (READABLE_FROM, bits 0-7). A later version that adds only what an older reader passes
over keeps the older number there, and that reader uses the state instead of refusing it as newer.
Schema 5 stays schema 5: a release before v0.6.18 reads no mark, and opens a marked state exactly as
it opens an unmarked one - which the released code itself is asked here (tests/released.py).
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume.store import (SCHEMA_VERSION, StateFromNewerVersion, Store, StoreError,  # noqa: E402
                                     downgrade_state)
from codex_auto_resume.store.schema import MARK, READABLE_FROM  # noqa: E402

import released  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"
NEWER_WORDS = "This state was written by a newer version of codex-auto-resume"


def detection(index: int, thread: str = THREAD) -> dict:
    return {"thread_id": thread, "turn_id": "0a1b2c3d-0002-7000-8000-%012d" % index, "completed_at": 110.0 + index,
            "started_at": 105.0, "ordinal": index, "interruption_id": ("%02x" % index) * 32, "reset_at": None,
            "limit_type": "x", "uncertain": False, "category": "server_5xx"}


def pragma(state_dir: Path, name: str) -> int:
    with closing(sqlite3.connect(Path(state_dir) / "state.sqlite")) as db:
        return db.execute("PRAGMA %s" % name).fetchone()[0]


def rewrite(state_dir: Path, *statements) -> None:
    with closing(sqlite3.connect(Path(state_dir) / "state.sqlite")) as db:
        for statement in statements:
            db.execute(statement)
        db.commit()


# A later version's additions an older reader passes over: a column at the end of a table, with a default, and a table.
LATER = ("ALTER TABLE interruptions ADD COLUMN later_word TEXT NOT NULL DEFAULT 'kept'",
         "ALTER TABLE notices ADD COLUMN later_count INTEGER",
         "CREATE TABLE later_things (thing_id INTEGER PRIMARY KEY, word TEXT)",
         "INSERT INTO later_things (word) VALUES ('mine')",
         "PRAGMA user_version=%d" % (SCHEMA_VERSION + 1))


def mark(readable: int, written: int = SCHEMA_VERSION) -> int:
    return MARK | written << 8 | readable


# This version's own mark: written by schema 5, readable from 5.
OURS = mark(5)


def marked(readable: int, written: int = SCHEMA_VERSION + 1) -> str:
    """A later schema's mark, as that version writes it."""
    return "PRAGMA application_id=%d" % mark(readable, written)


def snapshot(store) -> dict:
    return {"records": store.all_records(), "settings": store.settings(), "disabled": sorted(store.disabled_threads())}


class Scratch(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name) / "state"

    def filled(self) -> dict:
        """A state this version made, with a record in two conversations, one of them off, and a notice."""
        with Store(self.state, migrate=True) as store:
            store.set_enabled(True, 100.0)
            for index in (1, 2):
                store.register(detection(index), 111.0)
            store.register(detection(3, OTHER), 112.0)
            store.set_thread_enabled(OTHER, False)
            store.raise_notice(("%02x" % 1) * 32, THREAD, "terminal_auth", 113.0)
            return snapshot(store)


class MarkTests(Scratch):
    def test_a_new_state_is_marked_readable_from_its_own_schema_which_stays_5(self):
        self.assertEqual((SCHEMA_VERSION, READABLE_FROM), (5, 5))
        with Store(self.state) as store:
            self.assertEqual((store.schema_version(), store.readable_from()), (5, 5))
        self.assertEqual(pragma(self.state, "application_id"), OURS)
        self.assertEqual(pragma(self.state, "user_version"), 5)

    def test_the_owner_marks_a_state_once_and_a_reader_writes_nothing(self):
        self.filled()
        rewrite(self.state, "PRAGMA application_id=0")       # a state as v0.6.17 and earlier wrote it
        with Store(self.state) as store:
            self.assertEqual(store.readable_from(), 5, "unmarked: readable from its own version")
        self.assertEqual(pragma(self.state, "application_id"), 0, "an open without the mutex writes nothing")
        with Store(self.state, migrate=True, check=True):
            pass
        self.assertEqual(pragma(self.state, "application_id"), OURS)
        # Once marked, the owner's open is a read again: no write lock taken, so none waited for.
        with patch.object(Store, "_transaction", side_effect=AssertionError("a write at open")):
            with Store(self.state, migrate=True, check=True) as store:
                self.assertEqual(store.readable_from(), 5)

    def test_a_mark_that_is_not_this_versions_is_made_this_versions(self):
        self.filled()
        for found in (mark(3), mark(9), mark(5, 4), MARK | 5, 0x12340505):
            with self.subTest(found=hex(found)):
                rewrite(self.state, "PRAGMA application_id=%d" % found)
                with Store(self.state, migrate=True):
                    pass
                self.assertEqual(pragma(self.state, "application_id"), OURS)

    def test_a_state_brought_forward_is_marked_and_one_put_back_is_not(self):
        before = self.filled()
        result = downgrade_state(self.state, 4)
        self.assertTrue(result["changed"])
        self.assertEqual((pragma(self.state, "user_version"), pragma(self.state, "application_id")), (4, 0),
                         "a state put back for an older release is readable from its own version alone")
        with Store(self.state, migrate=True, check=True) as store:
            self.assertEqual(store.schema_version(), 5)
            self.assertEqual(len(store.all_records()), len(before["records"]))
        self.assertEqual(pragma(self.state, "application_id"), OURS)

    def test_a_mark_written_in_a_transaction_goes_with_it(self):
        """The mark is written inside the opening's transaction, so an opening that fails leaves none."""
        self.filled()
        rewrite(self.state, "PRAGMA application_id=0")
        with patch.object(Store, "_read_settings", side_effect=StoreError("Invalid settings")):
            with self.assertRaises(StoreError):
                Store(self.state, migrate=True)
        self.assertEqual(pragma(self.state, "application_id"), 0)


class LaterStateTests(Scratch):
    def test_a_later_state_marked_readable_from_this_one_is_used_as_it_is(self):
        before = self.filled()
        rewrite(self.state, *LATER, marked(5))
        with Store(self.state, migrate=True, check=True) as store:
            self.assertEqual((store.schema_version(), store.readable_from()), (6, 5))
            self.assertEqual(snapshot(store), before, "the same rows, what the later version added passed over")
            # And written as this version writes: a record registered, changed, cancelled.
            store.register(detection(4), 120.0)
            store.cancel_interruption(("%02x" % 2) * 32, 121.0)
            self.assertTrue(store.get(("%02x" % 2) * 32)["cancel_requested"])
            self.assertEqual(len(store.all_records()), 4)
            self.assertEqual(set(store.get(("%02x" % 4) * 32)), set(before["records"][0]))
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            self.assertEqual({row[0] for row in db.execute("SELECT later_word FROM interruptions")}, {"kept"},
                             "the later column keeps its value, and a new row its default")
            self.assertEqual(db.execute("SELECT word FROM later_things").fetchall(), [("mine",)])
        self.assertEqual((pragma(self.state, "user_version"), pragma(self.state, "application_id")), (6, mark(5, 6)),
                         "nothing upgraded: the version and the mark are the later version's")

    def test_a_later_state_without_the_mark_or_marked_later_is_refused_as_today(self):
        self.filled()
        rewrite(self.state, *LATER)
        # No mark, one readable from a later version only, a foreign id - and this version's own mark under a later
        # schema: a later version that moved the schema without writing a mark of its own fails closed.
        for found in (0, mark(6, 6), mark(7, 6), 0x12340605, OURS, MARK | 5):
            with self.subTest(found=hex(found)):
                rewrite(self.state, "PRAGMA application_id=%d" % found)
                for migrate in (False, True):
                    with self.assertRaises(StateFromNewerVersion) as refused:
                        Store(self.state, migrate=migrate)
                    self.assertEqual(str(refused.exception), NEWER_WORDS)
                self.assertEqual(pragma(self.state, "application_id"), found, "and nothing written to it")

    def test_a_later_state_without_what_this_version_knows_is_malformed(self):
        """Marked readable or not, a state this version cannot read as its own is not used: a table it knows gone,
        a column it knows gone, or one of its columns no longer before what a later version added."""
        shapes = {"a table gone": ("DROP TABLE notices",),
                  "a column gone": ("ALTER TABLE notices DROP COLUMN seen_at",),
                  "a column moved after a later one": ("ALTER TABLE notices DROP COLUMN seen_at",
                                                       "ALTER TABLE notices ADD COLUMN later_count INTEGER",
                                                       "ALTER TABLE notices ADD COLUMN seen_at REAL"),
                  "a trigger": ("CREATE TRIGGER later AFTER INSERT ON later_things BEGIN SELECT 1; END",)}
        for name, statements in shapes.items():
            with self.subTest(name):
                Scratch.setUp(self)
                self.filled()
                rewrite(self.state, *LATER[2:], *statements, marked(5))
                with self.assertRaises(StoreError) as refused:
                    Store(self.state)
                self.assertNotIsInstance(refused.exception, StateFromNewerVersion)

    def test_a_record_a_later_version_changed_under_this_one_still_hands_it_over(self):
        """Opened as this version's own state, rows are read whole: a column given to them under a running store is
        met as a later version's rows (RecordSchemaMismatch), as before - only a state opened as a later version's
        reads by name."""
        from codex_auto_resume.store import RecordSchemaMismatch
        self.filled()
        with Store(self.state) as store:
            rewrite(self.state, LATER[0])
            with self.assertRaises(RecordSchemaMismatch):
                store.all_records()


class WatcherTests(Scratch):
    """The watcher's look at the schema before every tick (runtime/loop.py): a later schema marked readable from this
    one is ticked on; one that is not hands the watcher over, as before."""

    def run_two_ticks(self, later):
        from codex_auto_resume import config
        from codex_auto_resume.app import App
        from codex_auto_resume.windows import AdapterError
        from test_cli import _reset_logging
        home = self.state.parent / "home"
        self.addCleanup(_reset_logging)
        scratch = {"LOCALAPPDATA": str(home / "none"), "CODEX_HOME": str(home / "codex")}
        with patch.dict(os.environ, scratch):
            app = App(config.Paths(home), console=False)
        ticks = []

        def tick(store):
            ticks.append(store.schema_version())
            if len(ticks) == 1:
                rewrite(app.paths.state_dir, *later)

        def engine(store, **kwargs):
            return type("Engine", (), {"tick": lambda self_inner: tick(store)})()

        stops = iter([False, True])
        with patch.dict(os.environ, scratch), \
             patch.object(App, "engine", side_effect=engine), \
             patch.object(App, "wake_event", side_effect=AdapterError("unavailable")), \
             patch.object(App, "_start_tray", return_value=None), \
             patch.object(App, "mutex"), patch.object(App, "stop_event") as stop_event:
            stop_event.return_value.__enter__.return_value.wait.side_effect = lambda seconds: next(stops)
            code = app.run(once=False, poll=5)
        return code, ticks

    def test_a_later_schema_marked_readable_is_ticked_on(self):
        from codex_auto_resume.app import EXIT_OK
        code, ticks = self.run_two_ticks(LATER[2:] + (marked(5),))
        self.assertEqual((code, ticks), (EXIT_OK, [5, 6]))

    def test_a_later_schema_not_marked_readable_hands_the_watcher_over(self):
        from codex_auto_resume.app import EXIT_SCHEMA_NEWER
        code, ticks = self.run_two_ticks(LATER[2:] + (marked(6),))
        self.assertEqual((code, ticks), (EXIT_SCHEMA_NEWER, [5]))


# What a released store makes of a state: opened as its watcher opens it, every row, the switches - and then one record
# of its own registered, and a conversation switched on, so the next version finds the older one's writes.
_OPEN_AND_WRITE = r'''
import json, sys
from pathlib import Path
from codex_auto_resume.store import Store
root, thread, other = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
with Store(root, migrate=True, check=True) as store:
    answer = {"version": store.schema_version(), "records": store.all_records(), "settings": store.settings(),
              "disabled": sorted(store.disabled_threads())}
    store.register({"thread_id": thread, "turn_id": "0a1b2c3d-0002-7000-8000-000000000009", "completed_at": 130.0,
                    "started_at": 125.0, "ordinal": 9, "interruption_id": "09" * 32, "reset_at": None,
                    "limit_type": "x", "uncertain": False, "category": "server_5xx"}, 131.0)
    store.set_thread_enabled(other, True)
print(json.dumps(answer))
'''


class ReleasedTests(Scratch):
    """v0.6.17 and v0.6.16 know no mark: each opens a marked state exactly as its own, reads the same rows, and writes
    to it - and this version reads what they wrote, the mark still there."""

    def test_the_released_stores_open_a_marked_state_as_their_own(self):
        for tag in ("v0.6.17", "v0.6.16"):
            with self.subTest(tag=tag):
                Scratch.setUp(self)
                before = self.filled()
                self.assertEqual(pragma(self.state, "application_id"), OURS)
                found = released.run(tag, _OPEN_AND_WRITE, self.state, THREAD, OTHER)
                self.assertEqual(found["version"], 5)
                self.assertEqual({name: found[name] for name in before}, json.loads(json.dumps(before)))
                with Store(self.state, migrate=True, check=True) as store:
                    self.assertEqual(store.get("09" * 32)["state"], "waiting_reset")
                    self.assertTrue(store.thread_enabled(OTHER))
                    self.assertEqual(len(store.all_records()), len(before["records"]) + 1)
                self.assertEqual((pragma(self.state, "user_version"), pragma(self.state, "application_id")),
                                 (5, OURS))


if __name__ == "__main__":
    unittest.main()
