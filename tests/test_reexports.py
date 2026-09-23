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
has to be a name the front gives. The fronts are found by their shape rather than listed, so
the next step that moves a module out from under its name joins them by moving it.
"""
from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import srcscan  # noqa: E402

ROOT = Path(_HERE).parent


def fronts() -> dict:
    """{name: (the module, the package its code lives in)}, found rather than listed.

    A front has a shape: its body is a docstring and imports and nothing else, and everything
    it imports from inside this package comes from one subpackage. That is what a module looks
    like once its code has moved out from under it and it is holding the name.

    Found rather than listed on purpose. A hand-written list is a thing to forget, and the
    day it is forgotten is the day a front stops being checked - which is the failure this
    whole file exists to catch. The next step that moves a module joins these by moving it.
    """
    found = {}
    for name, path in srcscan.modules().items():
        if not name.startswith(srcscan.PACKAGE + "."):
            continue
        body = [node for node in srcscan.package_asts()[path].body
                if not isinstance(node, (ast.Import, ast.ImportFrom))]
        if not {type(node).__name__ for node in body} <= {"Expr", "If"}:
            continue                                   # it holds code of its own
        inside = {entry.target for entry in srcscan.imports(path)
                  if entry.internal and not entry.implied and entry.target != name}
        if not inside:
            continue                                   # it re-exports nothing
        package = one_package(inside)
        if package is None:
            continue                                   # what it imports is not one subpackage
        found[name[len(srcscan.PACKAGE) + 1:]] = (import_module(name), package)
    return found


def one_package(targets: set):
    """The one subpackage every target lives in, or None if there is not one.

    The modules' own parents, not the targets - with a single target the two differ, and it is
    the parent that is the package. `codex_auto_resume` itself does not count: a front's code
    has to have moved somewhere, and everything is inside the package already.
    """
    parts = [target.rsplit(".", 1)[0].split(".") for target in targets]
    shared = []
    for index in range(min(len(part) for part in parts)):
        here = {part[index] for part in parts}
        if len(here) != 1:
            break
        shared.append(here.pop())
    package = ".".join(shared)
    if not package.startswith(srcscan.PACKAGE + "."):
        return None
    return package if any(other.startswith(package + ".") for other in srcscan.modules()) else None


FRONTS = {name: module for name, (module, _package) in fronts().items()}
PACKAGE_OF = {name: package for name, (_module, package) in fronts().items()}


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
        """Not vacuous: fronts are found, and some of them are read in numbers.

        Not every front is. `ui` and `win` are re-export files too - the shape is the same -
        and almost nothing reaches them by name, because what is inside them is imported
        directly. They are held to the rule anyway, which costs nothing and means the rule
        arrives before the reads do.
        """
        self.assertGreaterEqual(len(FRONTS), 2, "the shape found no front at all")
        busy = [front for front in FRONTS if len(reads(front)) > 10]
        self.assertGreaterEqual(len(busy), 2, sorted(FRONTS))
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
    # The package a front's code lives in is not always named after it: `mcpserver`'s is
    # `mcp/`. Asking the front which one it re-exports from is the only way that stays true.
    own = PACKAGE_OF[front].replace(".", "/") + "/"
    for path in list(srcscan.package_files()) + sorted((ROOT / "build").glob("*.py")):
        if own in path.as_posix():
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
