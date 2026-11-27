"""The surface ledger (P6-DESIGN 3.4, seat S6.4): every test file that imports the Python UI has a row, and no row lies.

`tests/rustdiff/surface_ledger.json` sorts the test files that import `codex_auto_resume.ui`, `notice_window` or
`tray_place` into four kinds - pure, drawn, window behaviour, source scan - and says, for each, where it also runs on the
C# host (`status: host`), or why it does not yet (`pending`, with `why` and `needs`), or why it stays on the Python
product (`python-only`). Like the divergence ledger (tests/rustdiff/LEDGER) it only ever shrinks: this test holds the
number of pending rows to a ceiling, and a new test file that imports the UI fails here until it has a row.

Pure Python, stdlib only; it reads files and runs nothing of the product.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
LEDGER = TESTS / "rustdiff" / "surface_ledger.json"

PACKAGE = "codex_auto_resume"
SHORT = ("ui", "notice_window", "tray_place")
UI = tuple(PACKAGE + "." + name for name in SHORT)       # built, so this file's own strings are not a match
KINDS = ("pure", "drawn", "window", "scan")
STATUSES = ("host", "pending", "python-only")
# The ceiling for rows that are not yet on the host. Lower it when a row moves to `host`; never raise it.
PENDING_CEILING = 54


def imports_the_ui(path: Path) -> bool:
    """The rule P6-DESIGN 3.4 counts by: the file imports a module of the UI, or names one as a string a test opens."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(UI):
                return True
            if module == PACKAGE and any(alias.name in SHORT for alias in node.names):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name.startswith(UI) for alias in node.names):
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(UI) and " " not in node.value and len(node.value) < 80:
                return True
    return False


# The files that are the host's side of the ledger and read the Python UI only to hold the host to it (they name a Python
# module to compare a constant or a rule with it): they are the twins the rows name, not rows.
HOST_SIDE = ("test_host_shape.py", "test_host_tray_place.py", "test_surface_askback.py", "test_surface_opener.py")


def test_files() -> set[str]:
    return {path.name for path in TESTS.glob("test_*.py") if path.name not in HOST_SIDE and imports_the_ui(path)}


def test_names(path: Path) -> set[tuple[str, str]]:
    """(class, test) of every test the file defines."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {(node.name, member.name) for node in tree.body if isinstance(node, ast.ClassDef)
            for member in node.body if isinstance(member, ast.FunctionDef) and member.name.startswith("test_")}


def test_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


class SurfaceLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.rows = cls.ledger["files"]

    def test_every_file_that_imports_the_ui_has_a_row_and_no_other_does(self):
        found = test_files()
        listed = set(self.rows)
        self.assertEqual(sorted(found - listed), [], "a test file imports the UI and has no row: add one")
        self.assertEqual(sorted(listed - found), [], "a row names a file that no longer imports the UI: take it out")

    def test_the_four_kinds_and_the_three_states_are_the_only_words(self):
        self.assertEqual(tuple(self.ledger["kinds"]), KINDS)
        for name, row in self.rows.items():
            self.assertIn(row["kind"], KINDS, name)
            self.assertIn(row["status"], STATUSES, name)
            self.assertIn(row["route"], {"pure": "shim", "drawn": "plan", "window": "probe", "scan": "scan"}[row["kind"]], name)
            for kind, classes in row["parts"].items():
                self.assertIn(kind, KINDS, name)
                self.assertTrue(classes, name)

    def test_the_classes_a_row_names_are_in_its_file(self):
        for name, row in self.rows.items():
            present = test_classes(TESTS / name)
            for kind, classes in row["parts"].items():
                for cls in classes:
                    self.assertIn(cls, present, "%s: %s (%s) is not a class of the file" % (name, cls, kind))

    def test_a_row_that_is_not_on_the_host_says_why_and_what_would_make_it_pass(self):
        for name, row in self.rows.items():
            if row["status"] == "host":
                self.assertTrue(row.get("port"), "%s is on the host: name the file that runs it there" % name)
                for port in row["port"]:
                    self.assertTrue((ROOT / port).is_file(), "%s: %s is not a file" % (name, port))
            else:
                self.assertTrue(row.get("why", "").strip(), "%s: say why it is not on the host" % name)
                if row["status"] == "pending":
                    self.assertTrue(row.get("needs", "").strip(), "%s: say what would make it pass" % name)

    def test_what_a_row_says_runs_on_the_host_is_there(self):
        """host_tests are tests of the row's own file that run through the shim or the host; twins name a test of a port file
        that holds the same rule of the host's C#; no_twin says why a test has no host to run on."""
        for name, row in self.rows.items():
            own = test_names(TESTS / name)
            for ident in row.get("host_tests", []) + list(row.get("twins", {})) + list(row.get("no_twin", {})):
                cls, test = ident.split(".", 1)
                self.assertIn((cls, test), own, "%s: %s is not a test of the file" % (name, ident))
            for ident, twin in row.get("twins", {}).items():
                port, where = twin.split("::")
                cls, test = where.split(".", 1)
                self.assertIn((cls, test), test_names(TESTS / port), "%s: twin %s of %s is not there" % (name, twin, ident))
            for ident, why in row.get("no_twin", {}).items():
                self.assertTrue(why.strip(), "%s: say why %s has no host to run on" % (name, ident))
            self.assertLessEqual(len(row.get("host_tests", [])) + len(row.get("twins", {})) + len(row.get("no_twin", {})),
                                 row["ui_tests"] + 1, name)

    def test_the_ledger_only_shrinks(self):
        pending = [name for name, row in self.rows.items() if row["status"] == "pending"]
        self.assertLessEqual(len(pending), PENDING_CEILING,
                             "more rows are pending than the ceiling allows; port one, never raise the ceiling")

    def test_the_counts_add_up(self):
        for name, row in self.rows.items():
            self.assertEqual(row["ui_tests"] + row["unaffected"], row["tests"], name)
            self.assertEqual(sum(row["by_kind"].values()), row["ui_tests"], name)
            counted = sum(count for classes in row["parts"].values() for count in classes.values())
            self.assertEqual(counted, row["ui_tests"], name)


if __name__ == "__main__":
    unittest.main()
