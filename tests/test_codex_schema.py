"""What this product needs of Codex's own databases, written down.

The watcher reads Codex's state, history and queue read-only, and it refuses a database whose
schema has moved rather than guessing (`LocalSource.resolve`). Which columns it needs is
therefore a promise in two directions: to Codex, that we read only these; and to the test
suite, whose synthetic Codex home (`tests/codexsim.py`) must build exactly them, or the tests
pass against a Codex that does not exist.

v0.6.10-alpha moves `source.py` into `codex/`, so both are pinned here first: the required
columns as a table, and the rule that every SQL statement in the package lives in one module,
so "what we ask of Codex" stays something a reader can find in one file.
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import codexsim  # noqa: E402
import srcscan  # noqa: E402
from codex_auto_resume import source  # noqa: E402

# Every column the product reads, per database, as `LocalSource.DB_KINDS` requires them. A
# column added here is a new thing asked of Codex; a column taken away is one we stop needing.
REQUIRED = {
    "state": {
        "threads": {"archived", "history_mode", "id", "rollout_path", "source", "thread_source"},
    },
    "history": {
        "thread_turns": {"completed_at", "error_json", "first_user_item_id", "rollout_end_byte_offset",
                         "rollout_ordinal", "started_at", "status", "thread_id", "turn_id"},
        "thread_items": {"item_id", "item_json", "item_type", "thread_id", "turn_id"},
    },
    "queue": {
        "queued_items": {"id", "payload_json", "thread_id"},
    },
}

# A statement, not a word: `SELECT name FROM ...` and not the string "select" in a sentence.
SQL = re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE|PRAGMA)\b")


class RequiredColumnTests(unittest.TestCase):
    def test_the_product_asks_for_exactly_these_columns(self):
        found = {kind: {table: set(columns) for table, columns in tables.items()}
                 for kind, (_pattern, tables) in source.DB_KINDS.items()}
        self.assertEqual(found, REQUIRED,
                         "what the watcher needs of Codex moved; say so here in the same commit")

    def test_the_synthetic_codex_home_builds_every_column_the_product_needs(self):
        """Otherwise the suite passes against a Codex nobody has."""
        with tempfile.TemporaryDirectory() as folder:
            home = codexsim.CodexHome(Path(folder))
            for kind, tables in REQUIRED.items():
                # `resolve` answers with the file's name, not its path: the reader joins it to
                # the Codex home itself, and so does this.
                name = source.LocalSource(home.root).resolve(kind)
                connection = sqlite3.connect(home.root / name)
                try:
                    for table, columns in tables.items():
                        found = {row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)}
                        with self.subTest(kind=kind, table=table):
                            self.assertLessEqual(columns, found,
                                                 "codexsim builds %s without %s"
                                                 % (table, sorted(columns - found)))
                finally:
                    connection.close()

    def test_a_database_missing_a_required_column_is_refused(self):
        """The reason the table above is a promise and not a preference."""
        with tempfile.TemporaryDirectory() as folder:
            home = codexsim.CodexHome(Path(folder))
            path = home.root / source.LocalSource(home.root).resolve("queue")
            connection = sqlite3.connect(path)
            try:
                connection.execute("ALTER TABLE queued_items RENAME COLUMN payload_json TO payload")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(source.SourceError):
                source.LocalSource(home.root).resolve("queue")


class OneHomeForTheSqlTests(unittest.TestCase):
    """Every statement this product sends to Codex sits in one module.

    It is the only way a reader can answer "what does this thing read of mine?" by opening one
    file - and v0.6.10-alpha moves that file into `codex/`, where the rule has to survive.
    """

    def modules_with_sql(self) -> dict:
        found = {}
        for path in srcscan.package_files():
            name = srcscan.relative(path)
            count = len([line for line in srcscan.read(path).splitlines()
                         if SQL.search(line) and "PRAGMA" not in line])
            if count:
                found[name] = count
        return found

    # The modules that may hold a statement, and why. The store owns the state's own SQL; the
    # reader below owns everything asked of Codex; and the registry's probe asks Codex's schema
    # one question of its own - it belongs with the reader, and goes there when `compat/` is
    # built (step 11 of the plan), not before.
    ALLOWED = {"codex_auto_resume/source.py": "everything asked of Codex",
               "codex_auto_resume/codex/history.py": "everything asked of Codex, once moved",
               "codex_auto_resume/compatio.py": "the registry's probe of Codex's own schema"}

    def test_only_the_modules_that_own_a_database_hold_sql(self):
        found = self.modules_with_sql()
        stray = {name: count for name, count in found.items()
                 if name not in self.ALLOWED and not name.startswith("codex_auto_resume/store/")}
        self.assertEqual(stray, {}, "a statement moved out of the module that owns it")

    def test_every_module_allowed_a_statement_still_makes_one(self):
        """An exception nobody needs is an exception that should go."""
        found = self.modules_with_sql()
        idle = [name for name in self.ALLOWED
                if name not in found and Path("src", name).exists()]
        self.assertEqual(idle, [], "these are allowed SQL and have none; take them off the list")

    def test_what_codex_is_asked_lives_in_one_module(self):
        found = self.modules_with_sql()
        reading_codex = {name: count for name, count in found.items()
                         if name in ("codex_auto_resume/source.py",
                                     "codex_auto_resume/codex/history.py")}
        self.assertEqual(len(reading_codex), 1,
                         "the statements sent to Codex are split across %s" % sorted(reading_codex))


if __name__ == "__main__":
    unittest.main()
