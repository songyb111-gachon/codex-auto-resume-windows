"""The advanced state's version 6 (v0.6.16-beta.4, the owner's additions to issue #29): the wrap-up's switches and
numbers in `options`, the continuation after the reset in `continuations`, and a person's own wording in `wordings` -
a version-5 file brought to it with every row kept, and on through stage 4's version 7 (test_advanced_state_v7), and
the way down as every earlier version has it.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState, StateError, session  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402

KEY = "%064x" % 4343


class VersionSixTests(StateCase):
    def version_five(self):
        """A file exactly as v0.6.16-beta.3 made it - version 5, its `options` and `continuations` CHECKs without the
        words version 6 added, no `wordings` - holding a choice, a continuation and a meter row."""
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        statements = (schema_module._STATEMENTS_V2 + schema_module._STATEMENTS_V3 + schema_module._STATEMENTS_V4
                      + schema_module._STATEMENTS_V5 + ("PRAGMA user_version=5",))
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in statements:
                if statement.lstrip().startswith(("CREATE TABLE options", "CREATE TABLE continuations")):
                    for word in schema_module.V6_OPTION_WORDS + schema_module.V6_CONTINUATION_WORDS:
                        statement = statement.replace(", '%s'" % word, "")
                connection.execute(statement)
            connection.execute("INSERT INTO arming VALUES ('test_wake','shadow',?,'dashboard',NULL,1,NULL,NULL)",
                               (self.now,))
            connection.execute("INSERT INTO options VALUES ('usage_wrap_up', 'wrap_five_hour', 90)")
            connection.execute("INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, created_at) "
                               "VALUES (?, 'usage_wrap_up', 'wrap_up', ?, 1, 1.0)", (KEY, ac.THREAD))
            connection.execute("INSERT INTO meter VALUES ('codex', 300, 91.0, 1800003600, 1.0, NULL, NULL, NULL)")
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError, msg="version 5's options CHECK"):
                connection.execute("INSERT INTO options VALUES ('usage_wrap_up', 'wrap_after_reset', 1)")
            with self.assertRaises(sqlite3.IntegrityError, msg="version 5's continuations CHECK"):
                connection.execute("INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, "
                                   "created_at) VALUES (?, 'usage_wrap_up', 'after_reset', ?, 1, 1.0)",
                                   ("%064x" % 1, ac.THREAD))
        return path

    def test_a_version_five_file_is_brought_to_six_and_keeps_every_row(self):
        """A beta.3 file takes version 6's step and then stage 4's (7), both in one opening."""
        path = self.version_five()
        state = self.state()
        self.assertEqual(state.arming()["test_wake"]["state"], "shadow")
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], schema_module.SCHEMA_VERSION)
            self.assertEqual(schema_module.SCHEMA_VERSION, 8)            # and every later step after it (v0.6.19)
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
            for name in schema_module.STAGE4_TABLES:
                self.assertEqual(connection.execute("SELECT count(*) FROM %s" % name).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT * FROM options").fetchall(),
                             [("usage_wrap_up", "wrap_five_hour", 90)])
            self.assertEqual(connection.execute("SELECT answer_id FROM continuations").fetchall(), [(KEY,)])
            self.assertEqual(connection.execute("SELECT count(*) FROM meter").fetchone()[0], 1)
            # The new CHECKs, and the wordings' own.
            connection.execute("INSERT INTO options VALUES ('usage_wrap_up', 'wrap_after_reset', 1)")
            connection.execute("INSERT INTO continuations (answer_id, capability, kind, thread_id, chain, created_at) "
                               "VALUES (?, 'usage_wrap_up', 'after_reset', ?, 1, 1.0)", ("%064x" % 1, ac.THREAD))
            connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'wrap_custom_weekly', 'Stop soon.', 1.0)")
            for words in ("", "x" * (schema_module.WORDING_LIMIT + 1)):
                with self.assertRaises(sqlite3.IntegrityError, msg=repr(words)[:20]):
                    connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'wrap_custom_five_hour', ?, 1.0)",
                                       (words,))
            # Since version 8 (v0.6.19) a wording's key is the code's to check, as an option's name is: the file takes
            # one no version knows, and the code passes it over (test_advanced_schema_v8).
            connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'anything', 'words', 1.0)")

    def test_the_way_down_is_every_capability_off_and_nothing_written(self):
        """A build that knows only version 5 (v0.6.16-beta.3) refuses this version's file as newer - every capability
        off - and writes nothing to it, a wording kept there included."""
        state = self.state()
        state.move("test_wake", "shadow", actor="dashboard", revision=1)
        state.close()
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], schema_module.SCHEMA_VERSION)
            connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'wrap_custom_weekly', 'Stop soon.', 1.0)")
            connection.commit()
        before = path.read_bytes()
        with patch.object(session, "SCHEMA_VERSION", 5):
            older = AdvancedState(self.paths, registry=ac.Registry((ac.definition(),)), clock=lambda: self.now)
            self.addCleanup(older.close)
            with self.assertRaises(StateError):
                older.arming()
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
