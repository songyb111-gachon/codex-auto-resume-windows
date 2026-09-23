"""Every name a module uses is one that module gives it.

Python only says a name is missing when the line that uses it runs, so an import left behind
by a move waits for the first person to take that path. v0.6.10-alpha moves a great deal of
code between files, and it found this the hard way: `tray_popup/renderer.py` came out of the
split with `class Renderer` and its method `def layout`, but not the `from .layout import
layout` the method's body needs - and the method's own name hid it, because a class body's
names look like the module's until you remember they are not in scope inside its methods.
The popup raised NameError on the first frame it drew.

So the resolution below has to be Python's, not an approximation of it: a name is visible if
this scope binds it, or a *function* scope around it does, or the module does, or it is a
builtin. A class body's names stop at its methods. Get that wrong in the lenient direction
and this test passes on the very code it exists to catch.
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import srcscan  # noqa: E402

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__class__", "WindowsError"}
FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _binds(node) -> set:
    """The names one statement binds in its own scope, not looking inside a nested one."""
    names, stack = set(), [node]
    while stack:
        item = stack.pop()
        if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
            names.add(item.id)
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(item.name)
            continue                                   # its body is a scope of its own
        elif isinstance(item, ast.Import):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in item.names}
        elif isinstance(item, ast.ImportFrom):
            names |= {alias.asname or alias.name for alias in item.names}
        elif isinstance(item, ast.ExceptHandler) and item.name:
            names.add(item.name)
        elif isinstance(item, (ast.Global, ast.Nonlocal)):
            names |= set(item.names)
        stack.extend(ast.iter_child_nodes(item))
    return names


def unresolved(tree: ast.AST) -> list:
    """(line, name) for every name loaded in this module that nothing in it gives."""
    missing = []

    def scope(body, enclosing, args=(), is_class=False):
        here = set(args)
        for statement in body:
            here |= _binds(statement)
        visible = enclosing | here
        inherited = enclosing if is_class else visible   # a class body's names stop at its methods
        for statement in body:
            stack = [statement]
            while stack:
                item = stack.pop()
                if isinstance(item, FUNCTION):
                    inner = [arg.arg for arg in ast.walk(item.args) if isinstance(arg, ast.arg)]
                    inside = [ast.Expr(item.body)] if isinstance(item, ast.Lambda) else item.body
                    scope(inside, inherited, inner)
                    stack.extend(getattr(item, "decorator_list", []) + list(item.args.defaults))
                    continue
                if isinstance(item, ast.ClassDef):
                    scope(item.body, visible, is_class=True)
                    stack.extend(item.decorator_list + list(item.bases))
                    continue
                if (isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
                        and item.id not in visible and item.id not in BUILTINS):
                    missing.append((item.lineno, item.id))
                stack.extend(ast.iter_child_nodes(item))

    scope(tree.body, set())
    return sorted(set(missing))


class NameTests(unittest.TestCase):
    def test_no_module_uses_a_name_nothing_gives_it(self):
        offenders = []
        for path, tree in srcscan.package_asts().items():
            for line, name in unresolved(tree):
                offenders.append("%s:%d %s" % (srcscan.relative(path), line, name))
        self.assertEqual(offenders, [], "an import was left behind by a move")

    def test_the_scan_reads_the_whole_package(self):
        """Through srcscan, so a module in a subpackage is read like any other."""
        read = {srcscan.relative(path) for path in srcscan.package_asts()}
        self.assertIn("codex_auto_resume/tray_popup/renderer.py", read)
        self.assertIn("codex_auto_resume/engine/dispatch.py", read)
        self.assertGreater(len(read), 60)


class ResolutionTests(unittest.TestCase):
    """The rules this leans on, each shown to be the rule Python uses."""

    def names(self, source):
        return [name for _line, name in unresolved(ast.parse(source))]

    def test_a_method_named_like_a_function_does_not_stand_in_for_it(self):
        """The popup's own failure, in six lines. `layout` is bound in the class body, which
        is not a scope its methods see - so the module-level import is the only thing that
        could give it, and there isn't one."""
        self.assertEqual(self.names("class R:\n"
                                    "    def layout(self, vm):\n"
                                    "        return layout(vm)\n"), ["layout"])
        self.assertEqual(self.names("from .layout import layout\n"
                                    "class R:\n"
                                    "    def layout(self, vm):\n"
                                    "        return layout(vm)\n"), [])

    def test_a_function_around_one_does_give_it(self):
        self.assertEqual(self.names("def outer():\n"
                                    "    thing = 1\n"
                                    "    def inner():\n"
                                    "        return thing\n"
                                    "    return inner\n"), [])

    def test_what_a_scope_binds_any_way_it_can(self):
        for source in ("import os\nos.getcwd()\n",
                       "from os import getcwd\ngetcwd()\n",
                       "import os.path as p\np.join('a')\n",
                       "for row in ():\n    print(row)\n",
                       "with open('f') as handle:\n    handle.read()\n",
                       "try:\n    pass\nexcept OSError as error:\n    print(error)\n",
                       "rows = [x for x in () if x]\nprint(rows)\n",
                       "def f(a, *rest, key=None, **extra):\n    return a, rest, key, extra\n",
                       "def f():\n    global seen\n    seen = 1\n"):
            with self.subTest(source.splitlines()[0]):
                self.assertEqual(self.names(source), [])

    def test_a_name_no_one_gives_is_reported_once_with_its_line(self):
        self.assertEqual(unresolved(ast.parse("def f():\n    return missing\n")), [(2, "missing")])


if __name__ == "__main__":
    unittest.main()
