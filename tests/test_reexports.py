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


def readers():
    """Every file that could name a front: the package, the build scripts, and the suite.

    `build/stage/` and `build/cache/` are copies of a release being made and hold the code as
    it was, so they are not read - they would fail this for a version that is already out."""
    files = list(srcscan.package_files())
    files += sorted((ROOT / "build").glob("*.py"))
    files += sorted((ROOT / "tests").glob("*.py"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    return files


def one_dot(path: Path) -> str | None:
    """What a single leading dot means in this file, or None if it is not the package's."""
    if not path.as_posix().endswith(".py") or srcscan.PACKAGE not in path.parts:
        return None
    module = srcscan.module_name(path)
    return module if path.name == "__init__.py" else module.rsplit(".", 1)[0]


def bound_to(tree, front: str, dot: str | None = None) -> set:
    """The names this file binds to the front module itself, however it imports it.

    `dot` is what a single leading dot means here, because the package's own files reach a
    front relatively - `from . import tray_popup` from beside it, `from .. import tray_popup`
    from inside a subpackage - and those are most of the reads there are. Resolving the dots
    is the difference between this scan seeing the product and seeing only the suite.
    """
    target = srcscan.PACKAGE + "." + front
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.asname or alias.name for alias in node.names
                      if alias.name == target}
        elif isinstance(node, ast.ImportFrom):
            if node.level and dot is None:
                continue                              # a relative import outside the package
            if node.level:
                here = dot
                for _ in range(node.level - 1):
                    here = here.rsplit(".", 1)[0]
                base = here + "." + node.module if node.module else here
            else:
                base = node.module or ""
            if base == srcscan.PACKAGE:
                names |= {alias.asname or alias.name for alias in node.names
                          if alias.name == front}
    return names


def attributes_of(tree, names: set):
    """`x.name` for every `x` in `names`, and only where `x` is the module.

    Read from the tree rather than the text, which matters more than it sounds. `tray.` opens
    half the interface catalogue's keys - `say(strings, "tray.title")` - and `control.` opens
    every use of the control layer through an instance, `self.control.get_status()`. Both are
    text that looks exactly like a read of a front and is not one; only the shape tells them
    apart. It also means `tray_popup.py` in a sentence is a string, not the name `py`.
    """
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in names):
            yield node.attr


def reads(front: str) -> dict:
    """{name: [the files that read `front`.name]}, over every file above."""
    found: dict[str, list[str]] = {}
    for path in readers():
        if path.name == "test_reexports.py":
            continue                                  # its own prose names them
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = bound_to(tree, front, one_dot(path))
        if not names:
            continue
        for name in attributes_of(tree, names):
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
        """Not vacuous: each front is really read by name, in numbers, and the reads it finds
        include the ones made relatively from inside the package."""
        for front in FRONTS:
            with self.subTest(front):
                self.assertGreater(len(reads(front)), 10)
        self.assertIn("USER_GROUPS", reads("mcpserver"))
        popup = reads("tray_popup")
        self.assertIn("_icon_from_pixels", popup)
        # tray.py reaches it with `from . import tray_popup`, inside a method; resolving that
        # dot is what makes this scan read the product rather than only the suite.
        self.assertIn("tray.py", popup["_icon_from_pixels"])

    def test_the_scan_reads_the_tree_and_not_the_text(self):
        """The two shapes that look like a read of a front and are not.

        `say(strings, "tray.title")` is a catalogue key - half the interface's keys begin with
        a module's name - and `self.control.get_status()` is the control layer through an
        instance. A scan over the text counts both; this one counts neither, which is why a
        front may be named after something the vocabulary also talks about.
        """
        source = ("from codex_auto_resume import tray\n"
                  "def f(self, strings):\n"
                  "    say(strings, 'tray.title')\n"
                  "    other = self.tray.stop\n"
                  "    return tray.Tray, other\n")
        tree = ast.parse(source)
        names = bound_to(tree, "tray")
        self.assertEqual(names, {"tray"})
        self.assertEqual(sorted(attributes_of(tree, names)), ["Tray"])

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
    found: dict[str, list[str]] = {}
    inside = "codex_auto_resume/%s/" % front
    for path in list(srcscan.package_files()) + sorted((ROOT / "build").glob("*.py")):
        if inside in path.as_posix():
            continue                                   # the package's own files
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = bound_to(tree, front, one_dot(path))
        if not names:
            continue
        for name in attributes_of(tree, names):
            found.setdefault(name, []).append(path.name)
    return found


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
                names = bound_to(tree, front)
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
