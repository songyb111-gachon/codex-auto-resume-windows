"""Lazy imports (PEP 810, Python 3.15): the one switch, off in this version, and what would have to hold with it on.

With every import lazy a module nobody touches is never imported, so a module whose import registers something would
silently register nothing. Two ways to look: by reading (no module of ours writes into another module's table as it is
imported) and, on 3.15, by asking: the same process with and without PYTHON_LAZY_IMPORTS=all has to give the same answers
and the same tables. Each run is a process of its own, with a scratch home and a scratch profile.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ADVANCED = os.environ.get("CODEX_AR_EDITION") == "advanced"
PACKAGES = ("codex_auto_resume", "codex_auto_resume_advanced") if ADVANCED else ("codex_auto_resume",)
PATHS = [str(ROOT / "src")] + ([str(ROOT / "advanced" / "src")] if ADVANCED else [])

# What a person's click asks of the bridge, with nothing else imported first.
ANSWERS = r'''
import json, sys
sys.path[:0] = sys.argv[1].split(";")
from codex_auto_resume import controlcli, notice_kinds, config
control = controlcli.Control(sys.argv[2])
out = {command: controlcli.dispatch(control, command, {}) for command in ("describe", "defaults", "strings", "settings")}
out["kinds_before"] = list(notice_kinds.ids())
if sys.argv[3] == "advanced":
    from codex_auto_resume_advanced import plug
    made = plug.create(config.Paths(sys.argv[2]))
    out["plug"] = type(made).__name__
out["kinds_after"] = list(notice_kinds.ids())
from codex_auto_resume.mcp import tools
out["tools"] = [tool["name"] for tool in tools.TOOLS]
print(json.dumps(out, sort_keys=True, default=str))
'''

# Every module imported, every plain table each one holds.
TABLES = r'''
import importlib, json, pkgutil, re, sys
sys.path[:0] = sys.argv[1].split(";")
packages = sys.argv[3].split(",")
for package in packages:
    root = importlib.import_module(package)
    for info in pkgutil.walk_packages(root.__path__, package + "."):
        if not info.name.endswith("__main__"):
            importlib.import_module(info.name)
out = {}
def later(value):
    return sorted(map(repr, value)) if isinstance(value, (set, frozenset)) else repr(value)
for name, module in sorted(sys.modules.items()):
    if any(name == package or name.startswith(package + ".") for package in packages):
        table = {}
        for key in dir(module):
            if not key.startswith("__"):
                value = getattr(module, key)
                if isinstance(value, (dict, list, tuple, set, frozenset, str, int, float, bool, type(None))):
                    try:
                        text = json.dumps(value, sort_keys=True, default=later)
                    except TypeError:       # keys that are not strings
                        text = repr(value)
                    table[key] = re.sub(r"0x[0-9a-fA-F]+|\b\d{10,}\b", "#", text)
        out[name] = table
print(json.dumps(out, sort_keys=True))
'''


def _ask(code, *arguments, lazy):
    with tempfile.TemporaryDirectory(prefix="car-lazy-") as scratch:
        profile = Path(scratch)
        for folder in ("home", "codex", "AppData/Local", "AppData/Roaming"):
            (profile / folder).mkdir(parents=True)
        environment = {name: value for name, value in os.environ.items()
                       if name not in ("PYTHONPATH", "PYTHON_LAZY_IMPORTS", "CODEX_AR_EDITION")}
        environment.update(USERPROFILE=str(profile), HOME=str(profile), LOCALAPPDATA=str(profile / "AppData" / "Local"),
                           APPDATA=str(profile / "AppData" / "Roaming"), CODEX_HOME=str(profile / "codex"), PYTHONHASHSEED="0")
        if lazy:
            environment["PYTHON_LAZY_IMPORTS"] = "all"
        done = subprocess.run([sys.executable, "-c", code, ";".join(PATHS), str(profile / "home"), *arguments], env=environment,
                              capture_output=True, encoding="utf-8", errors="replace", timeout=300, creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise AssertionError("lazy=%s exit %s:\n%s" % (lazy, done.returncode, done.stderr[-3000:]))
    return json.loads(done.stdout)


class TheSwitchTests(unittest.TestCase):
    def setUp(self):
        import codex_auto_resume
        self.package = codex_auto_resume
        self.asked = []

    def interpreter(self, executable=r"C:\home\runtime\python.exe"):
        return types.SimpleNamespace(executable=executable, set_lazy_imports=self.asked.append)

    def test_it_is_off_in_this_version(self):
        self.assertIs(self.package.LAZY_IMPORTS, False, "the switch is the day's: docs/DEVELOPMENT.md")

    def test_off_sets_nothing(self):
        self.package._lazy_imports(False, self.interpreter())
        self.assertEqual(self.asked, [])

    def test_on_sets_every_import_lazy_on_the_bundled_interpreter(self):
        self.package._lazy_imports(True, self.interpreter())
        self.assertEqual(self.asked, ["all"])

    def test_a_source_run_is_left_as_it_is(self):
        self.package._lazy_imports(True, self.interpreter(r"C:\Python315\python.exe"))
        self.assertEqual(self.asked, [])

    def test_before_3_15_there_is_nothing_to_set(self):
        self.package._lazy_imports(True, types.SimpleNamespace(executable=r"C:\home\runtime\python.exe"))

    def test_the_build_check_imports_for_real_with_the_switch_on(self):
        """build/runtime_check.py says whether every module imports under the trimmed runtime; a lazy import would pass
        for a module that is not there. Its filter refuses every lazy import, in main, before the first of the product."""
        tree = ast.parse((ROOT / "build" / "runtime_check.py").read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        names = [node.value for node in ast.walk(main) if isinstance(node, ast.Constant)]
        self.assertIn("set_lazy_imports_filter", names)


class NothingRegistersAcrossModulesTests(unittest.TestCase):
    def top_level_writes(self, tree) -> list:
        """Statements at a module's top level that call or assign through a name the module imported from this product."""
        ours = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("codex_auto_resume")):
                ours.update(item.asname or item.name for item in node.names)
            elif isinstance(node, ast.Import):
                ours.update((item.asname or item.name).split(".")[0] for item in node.names if item.name.startswith("codex_auto_resume"))
        written = []
        for node in tree.body:
            target = None
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                target = node.value.func
            elif isinstance(node, (ast.Assign, ast.AugAssign)):
                for each in getattr(node, "targets", [getattr(node, "target", None)]):
                    if isinstance(each, (ast.Subscript, ast.Attribute)):
                        target = each
            while isinstance(target, (ast.Attribute, ast.Subscript)):
                target = target.value
            if isinstance(target, ast.Name) and target.id in ours:
                written.append((node.lineno, target.id))
        return written

    def test_no_module_writes_into_another_as_it_is_imported(self):
        found = []
        for tree_name in ("src", "advanced/src"):
            for path in sorted((ROOT / tree_name).rglob("*.py")):
                for line, name in self.top_level_writes(ast.parse(path.read_bytes())):
                    found.append("%s:%d through %s" % (path.relative_to(ROOT).as_posix(), line, name))
        self.assertEqual(found, [], "with every import lazy this runs only if something else happens to touch the module")

    def test_the_reading_sees_one(self):
        source = "from .tables import KINDS\nfrom . import registry\nKINDS['x'] = 1\nregistry.add('y')\nOWN = {}\nOWN['z'] = 2\n"
        self.assertEqual(self.top_level_writes(ast.parse(source)), [(3, "KINDS"), (4, "registry")])


@unittest.skipUnless(sys.version_info >= (3, 15), "lazy imports exist from Python 3.15")
class SameWithAndWithoutTests(unittest.TestCase):
    def test_the_answers_are_the_same(self):
        lane = "advanced" if ADVANCED else "standard"
        plain, lazy = (_ask(ANSWERS, lane, lazy=each) for each in (False, True))
        self.assertEqual({key for key in plain if plain[key] != lazy.get(key)}, set())

    def test_every_table_of_every_module_is_the_same(self):
        plain, lazy = (_ask(TABLES, ",".join(PACKAGES), lazy=each) for each in (False, True))
        self.assertEqual(set(plain), set(lazy))
        self.assertEqual([(module, key) for module in plain for key in plain[module] if plain[module][key] != lazy[module].get(key)], [])


if __name__ == "__main__":
    unittest.main()
