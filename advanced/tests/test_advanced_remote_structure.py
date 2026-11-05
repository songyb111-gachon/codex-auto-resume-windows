"""Only the watcher sends (A1), and the resident courier's code is no way round it (v0.6.22, plans/v0619-design/D-remote.md).

The design asks for no import path from the courier to core's engine/dispatch or store/claims. Read literally that cannot
hold for code that goes "through the control layer", as the design also asks: core's `store` package composes its `Store`
from store/claims.py, and core's `control` opens a `Store`. And the courier's process reads the capabilities' states
through the edition's Runtime, as it has since v0.6.20, whose registry names the engine's errands. So what holds, and what
is held here, is:

* no module of the courier, nor control/remote.py, imports anything of core's `engine` or `store` itself, at any level;
* walking every import from them - inside functions too - and stopping at the seams, core's `control`, the edition's
  `runtime` and the compatibility report's read of whether recovery is paused (report/records.py, the short courier's since
  v0.6.20), reaches neither engine/dispatch nor store/claims;
* core's `control` itself reaches no engine/dispatch (and test_structural_invariants reads it for "nothing here sends");
* no name those modules call is a function of engine/dispatch or a method of store/claims or store/plugclaims;
* driven whole against core's real store, every read and action there is touches no claim and no dispatch (a spy on each
  claim method).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ROOT  # noqa: E402
from codex_auto_resume import control as core_control, store as core_store  # noqa: E402
from codex_auto_resume.store import claims as store_claims, plugclaims  # noqa: E402
from codex_auto_resume_advanced.control import remote  # noqa: E402

CORE = ROOT / "src" / "codex_auto_resume"
EDITION = ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
ROOTS = {"codex_auto_resume": CORE, "codex_auto_resume_advanced": EDITION}
# Whatever the resident runs: its own modules, the courier's others reached from them, and the layer it asks.
START = tuple("codex_auto_resume_advanced.courier." + path.stem for path in sorted((EDITION / "courier").glob("*.py"))
              if path.stem != "__init__") + ("codex_auto_resume_advanced.control.remote",)
# Where the walk stops: core's control layer, which its own test reads, and the edition's state reader.
SEAMS = ("codex_auto_resume.control", "codex_auto_resume_advanced.runtime", "codex_auto_resume_advanced.report.records")
FORBIDDEN = ("codex_auto_resume.engine.dispatch", "codex_auto_resume.store.claims")


def path_of(module):
    parts = module.split(".")
    if parts[0] not in ROOTS:
        return None
    base = ROOTS[parts[0]].joinpath(*parts[1:])
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    return base / "__init__.py" if (base / "__init__.py").is_file() else None


def imports_of(module) -> set:
    """Every first-party module `module` imports, at any level: inside functions too."""
    path = path_of(module)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[:len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            for alias in node.names:
                whole = base + "." + alias.name
                found.add(whole if path_of(whole) else base)
    return {name for name in found if path_of(name)}


def walk(start, stop=()) -> dict:
    """{module reached: the module that reached it}, not going through `stop`."""
    reached, todo = {name: None for name in start}, list(start)
    while todo:
        current = todo.pop()
        if current in stop:
            continue
        for name in imports_of(current):
            if name not in reached:
                reached[name] = current
                todo.append(name)
    return reached


def called_names(module) -> set:
    """Every name `module` calls, bare or as an attribute."""
    found = set()
    for node in ast.walk(ast.parse(path_of(module).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                found.add(target.attr)
            elif isinstance(target, ast.Name):
                found.add(target.id)
    return found


def own_functions(path) -> set:
    return {node.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("__")}


class ImportTests(unittest.TestCase):
    def test_nothing_of_the_courier_imports_core_s_engine_or_store_itself(self):
        """Fails the day a courier module takes dispatch, claims or the store directly."""
        for module in START:
            with self.subTest(module):
                self.assertEqual(sorted(name for name in imports_of(module)
                                        if name.startswith(("codex_auto_resume.engine", "codex_auto_resume.store"))), [])

    def test_up_to_the_two_seams_no_path_reaches_dispatch_or_claims(self):
        reached = walk(START, SEAMS)
        for name in FORBIDDEN:
            trail, current = [], name
            while current in reached and current is not None:
                trail.append(current)
                current = reached[current]
            self.assertNotIn(name, reached, " <- ".join(trail))

    def test_core_s_control_reaches_no_dispatch(self):
        self.assertNotIn("codex_auto_resume.engine.dispatch", walk(("codex_auto_resume.control",)))

    def test_the_seams_are_the_only_core_control_and_runtime_taken(self):
        """So the walk's stops hide nothing else: only `control.remote` asks core's control, and only the process asks
        Runtime and whether recovery is paused, as the short-lived courier always has."""
        users = {module: imports_of(module) & set(SEAMS) for module in START}
        self.assertEqual({module for module, names in users.items() if "codex_auto_resume.control" in names},
                         {"codex_auto_resume_advanced.control.remote"})
        for seam in SEAMS[1:]:
            self.assertEqual({module for module, names in users.items() if seam in names},
                             {"codex_auto_resume_advanced.courier.__main__"}, seam)


class CalledNameTests(unittest.TestCase):
    def test_nothing_it_calls_is_a_claim_or_a_dispatch(self):
        """Fails the day a courier module, or control/remote.py, calls a claim method or a dispatch step by name - on an
        object the import walk cannot see. A name shared with something harmless is listed, each with why."""
        forbidden = (own_functions(CORE / "store" / "claims.py") | own_functions(CORE / "store" / "plugclaims.py")
                     | own_functions(CORE / "engine" / "dispatch.py"))
        self.assertGreater(len(forbidden), 10)
        for module in START:
            with self.subTest(module):
                self.assertEqual(sorted((called_names(module) & forbidden) - SHARED), [])


# A name a courier module calls that also names a function of those three files, and is not that function.
SHARED = {"pending",   # control/remote's store.pending: the records' list, never a claim
          }


class DrivenTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.paths.ensure()
        self.layer = core_control.Control(self.paths)
        patcher = patch.object(core_control.Control, "watcher_running", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_read_and_action_there_is_touches_no_claim(self):
        """A spy on each method of store/claims.py and store/plugclaims.py, on core's real store: pause, list, cancel,
        status and metrics never call one. Fails where any of them starts a claim."""
        touched = []
        spies = []
        for mixin in (store_claims, plugclaims):
            for _name, cls in inspect.getmembers(mixin, inspect.isclass):
                if cls.__module__ != mixin.__name__:
                    continue
                for name, function in vars(cls).items():
                    if callable(function) and not name.startswith("__"):
                        def spy(*arguments, _name=name, _function=function, **keywords):
                            touched.append(_name)
                            return _function(*arguments, **keywords)
                        spies.append(patch.object(cls, name, spy))
        self.assertGreater(len(spies), 3, "the spies found the claim methods")
        with self.layer._open() as store:
            store.set_enabled(True, 100.0)
            store.register(dict(thread_id=ac.THREAD, turn_id=ac.OTHER_THREAD, completed_at=110.0, started_at=105.0,
                                ordinal=2, interruption_id=ac.KEY, reset_at=150.0, limit_type="codex.primary",
                                uncertain=False, category="usage_limit"), 100.0)
        for each in spies:
            each.start()
            self.addCleanup(each.stop)
        document = remote.status_document(self.layer, ac.NOW)
        remote.metrics(document)
        listed = remote.pending(self.layer)
        self.assertEqual(len(listed["pending"]), 1)
        remote.pause(self.layer)
        remote.cancel(self.layer, "task 1", listed["snapshot"])
        self.assertEqual(touched, [])
        self.assertIsNotNone(core_store.Store)


if __name__ == "__main__":
    unittest.main()
