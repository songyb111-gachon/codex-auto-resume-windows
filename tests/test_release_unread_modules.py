"""A module of the product that nothing reads at run time stays out of both archives, and nothing that ships reads it.

src/codex_auto_resume/control/wire.py writes the replies' shapes down as types for tests/test_wire_types.py and a port;
no program of an installation imports it. build/make_release.py names it in NOT_SHIPPED. These hold that list:

  (a) neither edition's payload carries a file of NOT_SHIPPED, and each is still in the repository for the tests;
  (b) no module the payload does carry imports one of them, by an import statement or by a name in importlib;
  (c) the exclusion is what keeps the file out (the build with an empty list brings it back), so (a) can fail.

Nothing here reaches the network, an installation or the registry; the build step writes into a temporary directory.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_release_size import builder, staged_app  # noqa: E402


def module_of(relative: str) -> str:
    """`src/a/b/c.py` as an import names it: `a.b.c`."""
    parts = list(Path(relative).relative_to("src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_names(source: str, own: str) -> set:
    """Every dotted name `source` (the module `own`) imports, relative imports resolved, plus each `from x import y`
    as x.y, since y may be a module."""
    package = own.rsplit(".", 1)[0] if "." in own else ""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")[: len(package.split(".")) - (node.level - 1)] if package else []
                base = ".".join(up + ([base] if base else []))
            found.add(base)
            found.update("%s.%s" % (base, alias.name) for alias in node.names)
    return found


class UnreadModulesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.make = builder()
        cls.standard = staged_app(cls.make, False)
        cls.advanced = staged_app(cls.make, True)

    def test_the_list_names_wire_and_every_name_on_it_is_a_file_of_the_repository(self):
        self.assertIn("src/codex_auto_resume/control/wire.py", self.make.NOT_SHIPPED)
        for name in self.make.NOT_SHIPPED:
            with self.subTest(name):
                self.assertTrue((ROOT / name).is_file(), "the tests read it from the tree")

    def test_neither_payload_carries_a_file_that_is_not_shipped(self):
        for label, app in (("standard", self.standard), ("advanced", self.advanced)):
            for name in self.make.NOT_SHIPPED:
                with self.subTest(label, name=name):
                    self.assertNotIn(name, app)
        self.assertIn("src/codex_auto_resume/control/__init__.py", self.standard, "the package around it ships")

    def test_no_shipped_module_imports_one_that_is_not_shipped(self):
        left_out = {module_of(name): name for name in self.make.NOT_SHIPPED if name.startswith("src/")}
        for label, app in (("standard", self.standard), ("advanced", self.advanced)):
            for name, data in sorted(app.items()):
                if not (name.startswith("src/") and name.endswith(".py")):
                    continue
                names = imported_names(data.decode("utf-8-sig"), module_of(name))
                for module, path in left_out.items():
                    with self.subTest(label, importer=name, imports=module):
                        self.assertNotIn(module, names, "%s ships and imports %s, which does not" % (name, path))

    def test_no_shipped_file_names_one_for_importlib(self):
        """A module reached by a string (importlib, __import__) would not show in the import statements."""
        for name in self.make.NOT_SHIPPED:
            module = module_of(name)
            last = module.rsplit(".", 1)[-1]
            for label, app in (("standard", self.standard), ("advanced", self.advanced)):
                for shipped, data in sorted(app.items()):
                    if not (shipped.startswith("src/") and shipped.endswith(".py")):
                        continue
                    text = data.decode("utf-8-sig")
                    if "import_module" in text or "__import__" in text:
                        for node in ast.walk(ast.parse(text)):
                            if isinstance(node, ast.Constant) and node.value in (module, last):
                                self.fail("%s (%s) holds the string %r beside a dynamic import" % (shipped, label, node.value))

    def test_with_an_empty_list_the_file_is_back_in_the_payload(self):
        make = builder()
        make.NOT_SHIPPED = ()
        back = staged_app(make, False)
        self.assertIn("src/codex_auto_resume/control/wire.py", back)
        self.assertEqual(sorted(set(back) - set(self.standard)), ["src/codex_auto_resume/control/wire.py"])


if __name__ == "__main__":
    unittest.main()
