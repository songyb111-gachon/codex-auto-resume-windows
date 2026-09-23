"""A module that became a package still gives every name it gave.

v0.6.10-alpha turns large modules into packages behind the name they already had, so that no
call site changes: `tray_popup.<name>` and `mcpserver.<name>` read as they always did, and the
code lives in files beside them. The one way that goes wrong is a name left out of the
re-export - and it goes wrong quietly, because nothing fails until the line that needs it runs.

It has happened twice, on the two fronts there are:

* `tray_popup._icon_from_pixels`, which the notification-area icon calls for every frame it
  draws. The icon caught the `AttributeError`, logged one line and drew itself the way it did
  before v0.6.5 for the rest of its life.
* `mcpserver.USER_GROUPS` and `mcpserver.PANEL_APPEARANCE`, which say which settings a model
  may change. Only the suite reads them - so the split would have left three tests failing,
  which is the good case, and is the reason this test reads the suite too.

So the rule, over the product, its build scripts and the suite alike: a name read off a front
has to be a name the front gives. The list of fronts below grows as the remaining steps land.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import srcscan  # noqa: E402
from codex_auto_resume import mcpserver, tray_popup  # noqa: E402

ROOT = Path(_HERE).parent

# The modules whose code moved into a package of the same name. Each keeps its own file, which
# holds a docstring and the re-exports and nothing else.
FRONTS = {"mcpserver": mcpserver, "tray_popup": tray_popup}

# Words that are not attribute reads: `tray_popup.py` in prose, `mcpserver.py` in a path.
NOT_A_NAME = {"py"}


def readers():
    """Every file that could name a front: the package, the build scripts, and the suite.

    `build/stage/` and `build/cache/` are copies of a release being made and hold the code as
    it was, so they are not read - they would fail this for a version that is already out."""
    files = list(srcscan.package_files())
    files += sorted((ROOT / "build").glob("*.py"))
    files += sorted((ROOT / "tests").glob("*.py"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    return files


def reads(front: str) -> dict:
    """{name: [the files that read `front`.name]}, over every file above."""
    pattern = re.compile(r"\b%s\.([A-Za-z_][A-Za-z0-9_]*)" % re.escape(front))
    found: dict[str, list[str]] = {}
    for path in readers():
        if path.name == "test_reexports.py":
            continue                                  # its own prose names them
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if name not in NOT_A_NAME:
                found.setdefault(name, []).append(path.name)
    return found


class ReExportTests(unittest.TestCase):
    def test_every_name_read_off_a_front_is_one_it_gives(self):
        missing = {}
        for front, module in FRONTS.items():
            for name, where in reads(front).items():
                if not hasattr(module, name):
                    missing["%s.%s" % (front, name)] = sorted(set(where))
        self.assertEqual(missing, {}, "re-export it, or stop reading it there")

    def test_the_scan_finds_something_to_check(self):
        """Not vacuous: each front is really read by name, in numbers."""
        for front in FRONTS:
            with self.subTest(front):
                self.assertGreater(len(reads(front)), 10)
        self.assertIn("USER_GROUPS", reads("mcpserver"))
        self.assertIn("_icon_from_pixels", reads("tray_popup"))

    def test_a_front_holds_no_code_of_its_own(self):
        """It is a name other programs hold and a list of re-exports. Anything else in it is
        code that escaped the package it was supposed to move into."""
        for front in FRONTS:
            with self.subTest(front):
                tree = srcscan.package_asts()[srcscan.modules()["codex_auto_resume." + front]]
                kinds = [type(node).__name__ for node in tree.body
                         if not isinstance(node, (ast.Import, ast.ImportFrom))]
                # A docstring, and `if __name__ == "__main__":` where the module is run.
                self.assertLessEqual(set(kinds), {"Expr", "If"}, kinds)

    def test_a_front_names_the_package_that_holds_its_code(self):
        for front in FRONTS:
            with self.subTest(front):
                targets = {entry.target for entry in
                           srcscan.imports(srcscan.modules()["codex_auto_resume." + front])}
                inside = {name for name in targets if name.startswith("codex_auto_resume.")}
                self.assertTrue(inside, "it should import from the package it became")


def product_reads(front: str) -> dict:
    """`front`.name as the product and its build scripts spell it - not the suite."""
    pattern = re.compile(r"\b%s\.([A-Za-z_][A-Za-z0-9_]*)" % re.escape(front))
    found: dict[str, list[str]] = {}
    inside = "codex_auto_resume/%s/" % front
    for path in list(srcscan.package_files()) + sorted((ROOT / "build").glob("*.py")):
        if inside in path.as_posix():
            continue                                   # the package's own files
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if name not in NOT_A_NAME:
                found.setdefault(name, []).append(path.name)
    return found


def aliases(tree, front: str) -> set:
    """The names a test module binds to `front` itself."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == srcscan.PACKAGE:
            names |= {alias.asname or alias.name for alias in node.names if alias.name == front}
        elif isinstance(node, ast.Import):
            names |= {alias.asname or alias.name for alias in node.names
                      if alias.name == srcscan.PACKAGE + "." + front}
    return names


class PatchPointTests(unittest.TestCase):
    """A patch on a front reaches only what reads the front.

    This is the other half of the same trap, and the worse half: the name is there, the patch
    succeeds, and it changes nothing - because the module that actually calls it holds its own
    reference now. The test goes on passing, having replaced the machine it meant to replace.

    Seven patches on `tray_popup` had stopped working that way, and `patch.object(mcpserver,
    "Control")` in `test_bridge_encoding.py` would have. So: a name may be patched on a front
    only if something outside the front's package really reads it there; otherwise the test
    names the module that holds the caller.
    """

    def patches(self):
        """(file, line, front, name) for every patch aimed at a front, however it is written."""
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            if path.name == "test_reexports.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for front in FRONTS:
                names = aliases(tree, front)
                if not names:
                    continue
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "object" and len(node.args) >= 2
                            and isinstance(node.args[0], ast.Name) and node.args[0].id in names
                            and isinstance(node.args[1], ast.Constant)):
                        yield path.name, node.lineno, front, node.args[1].value
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if (isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Name)
                                    and target.value.id in names):
                                yield path.name, target.lineno, front, target.attr

    def test_a_patch_on_a_front_reaches_something(self):
        read = {front: product_reads(front) for front in FRONTS}
        stray = ["%s:%d patches %s.%s, which only that package itself reads" % site
                 for site in self.patches() if site[3] not in read[site[2]]]
        self.assertEqual(stray, [])

    def test_the_rule_is_not_vacuous(self):
        patched = {(front, name) for _, _, front, name in self.patches()}
        # The icon asks the package for this one, so patching the package is right.
        self.assertIn(("tray_popup", "high_contrast"), patched)
        self.assertNotIn(("tray_popup", "message_face"), patched, "only fonts.py calls it")
        self.assertNotIn(("mcpserver", "Control"), patched, "only mcp/server.py calls it")


if __name__ == "__main__":
    unittest.main()
