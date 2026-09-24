"""The state database has the shape it had, on every path that can produce one.

`store.py` becomes a package in v0.6.10-alpha, and a split that drops a column from a
`CREATE TABLE`, stops making an index or lands a migration one version short does not fail
anywhere else in the suite: the tests write rows through the same code that made the table, so
both sides move together and agree. This file is the outside view - `PRAGMA table_info`,
`PRAGMA index_list`, `PRAGMA user_version` - compared with what is committed.

`tests/schemagolden.py` says how each path is built, and rewrites the file with `--write`.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import schemagolden  # noqa: E402

REWRITE = ("the database's shape moved. If that is meant - a migration, a new column - rerun\n"
           "  py tests/schemagolden.py --write\nin the same commit, and read the diff.")


class SchemaGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.made = schemagolden.produce()
        cls.stored = json.loads(schemagolden.GOLDEN.read_text(encoding="utf-8"))

    def test_every_path_is_recorded(self):
        self.assertEqual(sorted(self.made), sorted(self.stored),
                         "a path was added or taken away; rewrite the golden")

    def test_each_path_has_the_shape_it_had(self):
        for name in sorted(self.made):
            with self.subTest(name):
                made = self.made[name]
                if "skipped" in made:
                    self.skipTest(made["skipped"])
                self.assertEqual(made, self.stored[name], REWRITE)

    def test_an_upgraded_database_is_indistinguishable_from_a_fresh_one(self):
        """The property the golden exists to keep, said out loud.

        Somebody upgrading from v0.5.0 and somebody installing today must end up with the same
        database, or a later migration - written against one of them - meets the other.
        """
        fresh = self.made["fresh"]
        for name in sorted(self.made):
            if not name.startswith("upgraded-from-"):
                continue
            with self.subTest(name):
                if "skipped" in self.made[name]:
                    self.skipTest(self.made[name]["skipped"])
                self.assertEqual(self.made[name], fresh,
                                 "%s does not end where a fresh installation starts" % name)

    def test_the_downgrade_leaves_a_database_an_older_release_can_open(self):
        made = self.made["downgraded-to-v2"]
        if "skipped" in made:
            self.skipTest(made["skipped"])
        self.assertEqual(made["user_version"], 2)
        self.assertNotIn("events", made["tables"], "v2 has no events table")
        self.assertNotIn("watcher_status", made["tables"], "v2 has no watcher_status table")
        self.assertIn("interruptions", made["tables"])

    def test_the_golden_names_the_version_the_code_says(self):
        from codex_auto_resume.store import SCHEMA_VERSION
        self.assertEqual(self.stored["fresh"]["user_version"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
