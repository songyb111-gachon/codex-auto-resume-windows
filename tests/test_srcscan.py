"""The scanner every structural test reads the product's source through (`tests/srcscan.py`).

The structural tests assert absences - no second sender, no automation, no network, nothing
in the popup that can submit - and an absence is only as good as the list of files it was
looked for in. These hold that list to the package as it is on disk: every module, at any
depth, tracked; and they keep the suite from growing a new test that names one file again.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import pkgutil
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402
import codex_auto_resume  # noqa: E402
from codex_auto_resume import engine, tray, tray_popup, windows  # noqa: E402


class ListingTests(unittest.TestCase):
    def test_every_python_file_under_src_is_tracked(self):
        """The scans list the package with `git ls-files`, so a module that exists but was
        never added is invisible to every one of them - to the privacy scan, the
        no-automation scan and the popup's envelope alike - while the suite, which imports
        from disk, runs it as if nothing were wrong. `git add` it, or delete it."""
        tracked = {path.resolve() for path in srcscan.package_files()}
        untracked = [srcscan.relative(path) for path in srcscan.on_disk() if path.resolve() not in tracked]
        self.assertEqual(untracked, [], "on disk under src/ but not tracked, so no structural test reads it")

    def test_the_listing_is_every_file_at_every_depth(self):
        listed = {srcscan.relative(path) for path in srcscan.package_files()}
        self.assertEqual(listed, {srcscan.relative(path) for path in srcscan.on_disk()})
        self.assertIn("auto_resume.py", listed)
        self.assertIn("codex_auto_resume/__init__.py", listed)
        self.assertGreater(len(listed), 30, "the listing itself looks wrong")

    def test_every_module_python_can_import_is_listed(self):
        importable = {srcscan.PACKAGE} | {
            info.name for info in pkgutil.walk_packages(codex_auto_resume.__path__, srcscan.PACKAGE + ".")}
        self.assertEqual(importable - set(srcscan.modules()), set())

    def test_the_listing_is_the_one_python_imports(self):
        """The scans read the tree the tests import, not some other copy on the path."""
        self.assertEqual(Path(codex_auto_resume.__file__).resolve(),
                         srcscan.modules()[srcscan.PACKAGE].resolve())
        self.assertEqual(srcscan.module_name(srcscan.SRC / "codex_auto_resume" / "cli.py"), "codex_auto_resume.cli")
        self.assertEqual(srcscan.files_of("codex_auto_resume.tray_popup"),
                         [srcscan.modules()["codex_auto_resume.tray_popup"]])


class TreeTests(unittest.TestCase):
    def test_qualified_names_are_the_ones_python_gives(self):
        for module in (engine, windows, tray_popup):
            with self.subTest(module.__name__):
                tree = srcscan.package_asts()[srcscan.modules()[module.__name__]]
                found = {name for node, name in srcscan.qualnames(tree).items()
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                defined = set()
                for _, value in inspect.getmembers(module):
                    if getattr(value, "__module__", None) != module.__name__:
                        continue
                    if inspect.isfunction(value):
                        defined.add(value.__qualname__)
                    elif inspect.isclass(value):
                        defined.add(value.__qualname__)
                        defined.update(member.__qualname__ for _, member in inspect.getmembers(value, inspect.isfunction)
                                       if member.__module__ == module.__name__)
                self.assertTrue(defined)
                self.assertLessEqual(defined, found)
                if module is engine:
                    self.assertIn("Engine.dispatch", found)

    def test_a_node_belongs_to_the_function_around_it(self):
        tree = ast.parse("def outer():\n    def inner():\n        call()\n    return inner\n"
                         "class C:\n    def m(self):\n        other()\n")
        names = srcscan.qualnames(tree)
        calls = {node.func.id: names[node] for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertEqual(calls, {"call": "outer.<locals>.inner", "other": "C.m"})

    def test_imports_resolve_to_modules_and_say_when_they_run(self):
        popup = {(entry.target, entry.lazy) for entry in srcscan.imports(srcscan.modules()[tray_popup.__name__])}
        self.assertIn(("codex_auto_resume.tray", False), popup)          # from .tray import countdown
        self.assertIn(("codex_auto_resume.brand", False), popup)         # from . import brand, ...
        self.assertIn(("ctypes", False), popup)
        icon = {(entry.target, entry.lazy) for entry in srcscan.imports(srcscan.modules()[tray.__name__])}
        self.assertIn(("codex_auto_resume.tray_popup", True), icon)      # inside a function
        self.assertNotIn(("codex_auto_resume", False), icon, "`from . import x` names x, not the package")
        self.assertIn("codex_auto_resume.cli", srcscan.import_graph()["auto_resume"])
        self.assertIn("codex_auto_resume.tray_popup", srcscan.closure("codex_auto_resume.tray"))
        self.assertNotIn("codex_auto_resume.tray_popup", srcscan.closure("codex_auto_resume.tray", lazy=False))

    def test_an_import_loads_the_packages_above_what_it_names(self):
        """Importing `ui.popup.layout` runs `ui/__init__.py` first, whatever the statement
        spells, so what that file imports is reached as well - except by a module already
        inside `ui/`, for which it has run before."""
        known = {"p", "p.tray_popup", "p.ui", "p.ui.popup", "p.ui.popup.layout", "p.ui.card", "p.ui.card.view"}
        for importer, loaded in (("p.tray_popup", ["p.ui", "p.ui.popup"]),
                                 ("p.ui.card.view", ["p.ui.popup"]),
                                 ("p.ui", ["p.ui.popup"]),
                                 ("p.ui.popup", []),
                                 ("outside", ["p", "p.ui", "p.ui.popup"])):
            with self.subTest(importer):
                self.assertEqual(srcscan.implied_packages("p.ui.popup.layout", importer, known), loaded)
        self.assertEqual(srcscan.implied_packages("p.tray_popup", "p.ui.card.view", known), [])
        self.assertEqual(srcscan.ancestors("p.ui.popup.layout", {"p", "p.ui.popup"}), ["p", "p.ui.popup"])
        # On the tree as it is: the entry script is the one module outside the package, and
        # the package's own __init__.py is what it loads without naming it.
        implied = [(entry.target, entry.lazy, entry.internal)
                   for path in srcscan.package_files() for entry in srcscan.imports(path) if entry.implied]
        self.assertEqual(implied, [(srcscan.PACKAGE, False, True)])
        self.assertIn(srcscan.PACKAGE, srcscan.import_graph()["auto_resume"])


class NoOneFileScanTests(unittest.TestCase):
    """A structural test that names one file stops checking the day the code in it moves, and
    passes while it does. New ones go through srcscan."""

    def suite_modules(self):
        """Every test module beside this one, parsed. Not named test*, so it is not collected."""
        for path in sorted(Path(_HERE).glob("test_*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"))

    def test_no_test_reads_a_package_module_through_its_file(self):
        """`Path(control.__file__).read_text()` is the shape that reads an `__init__.py` holding
        nothing once `control` is a package. Comparing a module's path is fine; reading one
        module's text, or its whole source, to assert something about the code is not."""
        offenders = []
        for path, tree in self.suite_modules():
            modules = set()          # names bound to a module of the package
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == srcscan.PACKAGE:
                    modules.update(alias.asname or alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    modules.update(alias.asname for alias in node.names
                                   if alias.asname and alias.name.startswith(srcscan.PACKAGE + "."))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                reader = getattr(node.func, "attr", getattr(node.func, "id", None))
                if reader in ("read_text", "read_bytes", "open"):
                    inside = list(ast.walk(node.func)) + [part for arg in node.args for part in ast.walk(arg)]
                    if any(isinstance(part, ast.Attribute) and part.attr == "__file__"
                           and isinstance(part.value, ast.Name) and part.value.id in modules for part in inside):
                        offenders.append("%s:%d reads a module by its __file__" % (path.name, node.lineno))
                elif reader in ("getsource", "getsourcelines") and node.args \
                        and isinstance(node.args[0], ast.Name) and node.args[0].id in modules:
                    offenders.append("%s:%d reads %s's whole source" % (path.name, node.lineno, node.args[0].id))
        self.assertEqual(offenders, [], "read the package through srcscan instead")

    def test_no_test_globs_the_package_one_directory_deep(self):
        offenders = []
        for path, tree in self.suite_modules():
            text = path.read_text(encoding="utf-8")
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("glob", "iterdir", "listdir")
                        and srcscan.PACKAGE in (ast.get_source_segment(text, node.func.value) or "")):
                    offenders.append("%s:%d" % (path.name, node.lineno))
        self.assertEqual(offenders, [], "a module in a subpackage would escape this scan without failing it")


if __name__ == "__main__":
    unittest.main()
