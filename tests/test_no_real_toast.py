"""No test raises a real Windows toast, and nothing in src/ binds a function of its own at import.

Two halves of one fix (2026-10-22, plans/notif-check.md section 3): test runs raised real "automatic
recovery cancelled" toasts under the product's identity for twelve days, because a test patched
notify.show_content while the notifier had bound the real one as a default argument at import.

* The guard (tests/no_real_toast.py) refuses a real toast and fails the test that was running; every run
  loads it - tests/sitecustomize.py where tests/ is on the path, scripts/test_parts.py in a lane's run.
* The structural rule: a default argument in src/ never names a function of another module of the product
  (`show=notify.show_content`), which a test's patch of that function would never reach.

Every guard test here runs a command whose program does not exist, so a broken guard is a failed
assertion and never a real toast.
"""
from __future__ import annotations

import ast
import base64
import os
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import no_real_toast  # noqa: E402
import srcscan  # noqa: E402

ROOT = HERE.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NOWHERE = str(ROOT / "no-such-folder" / "powershell.exe")


def toast_command():
    from codex_auto_resume import notify
    encoded = base64.b64encode(notify._SCRIPT.encode("utf-16-le")).decode("ascii")
    return [NOWHERE, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def child(code: str, pythonpath: str) -> subprocess.CompletedProcess:
    environment = dict(os.environ, PYTHONPATH=pythonpath, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=environment, capture_output=True,
                          text=True, encoding="utf-8", timeout=120, creationflags=NO_WINDOW)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(no_real_toast.install())

    def test_the_toast_script_is_what_it_looks_for(self):
        from codex_auto_resume import notify
        self.assertIn(no_real_toast.TOAST_MARK, notify._SCRIPT)
        self.assertTrue(no_real_toast.is_toast(toast_command()))
        self.assertFalse(no_real_toast.is_toast([sys.executable, "-c", "pass"]))
        self.assertFalse(no_real_toast.is_toast([NOWHERE, "-EncodedCommand", "bm90IGEgdG9hc3Q="]))

    def test_a_real_toast_is_refused_before_anything_starts(self):
        inner = self.swallowing(lambda: subprocess.run(toast_command(), capture_output=True,
                                                       creationflags=NO_WINDOW))
        result = unittest.TestResult()
        before = no_real_toast.attempts()
        inner.run(result)
        self.assertEqual(no_real_toast.attempts(), before + 1)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1, "the refusal fails the test that made it")
        self.assertIn(no_real_toast.MESSAGE, result.failures[0][1])
        self.assertEqual(inner.raised, [AssertionError], "refused at subprocess.run: no PowerShell started")

    def test_the_product_s_own_toast_is_refused_through_every_layer(self):
        """notify.show -> pwsh.run -> subprocess.run, with PowerShell found: refused, and its failure is the
        test's although notify.show answered False and nothing raised out of it."""
        from unittest import mock
        from codex_auto_resume import notify, pwsh

        def toast():
            with mock.patch.object(pwsh, "executable", return_value=NOWHERE):
                return notify.show("title", "body")

        inner = self.swallowing(toast)
        result = unittest.TestResult()
        inner.run(result)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(inner.raised, [AssertionError])

    def test_a_test_that_patches_the_toast_is_left_alone(self):
        from unittest import mock
        from codex_auto_resume import notify
        inner = self.swallowing(lambda: notify.show_content({"title": "t", "body": "b"}))
        result = unittest.TestResult()
        before = no_real_toast.attempts()
        with mock.patch.object(notify, "show", return_value=True):
            inner.run(result)
        self.assertEqual((no_real_toast.attempts(), result.failures, inner.raised), (before, [], []))

    def test_any_other_command_runs(self):
        done = subprocess.run([sys.executable, "-c", "print('ran')"], capture_output=True, text=True,
                              creationflags=NO_WINDOW, timeout=60)
        self.assertEqual(done.stdout.strip(), "ran")

    @staticmethod
    def swallowing(action):
        """A test that does `action` and swallows whatever it raises, as the engine's announce does."""

        class Inner(unittest.TestCase):
            raised = []

            def runTest(self):
                try:
                    action()
                except Exception as error:      # noqa: BLE001 - swallowed on purpose
                    Inner.raised.append(type(error))

        Inner.raised = []
        return Inner()


class LoadedByEveryRunTests(unittest.TestCase):
    """Each way the suite is run installs the guard."""

    def test_an_interpreter_with_tests_on_its_path_has_it(self):
        done = child("import sys; print(sys.modules['no_real_toast'].active())",
                     os.pathsep.join([str(ROOT / "src"), str(HERE)]))
        self.assertEqual(done.stdout.strip(), "True", done.stderr)

    def test_and_imports_nothing_it_guards_before_it_is_imported(self):
        done = child("import sys; print('subprocess' in sys.modules, 'unittest' in sys.modules)",
                     os.pathsep.join([str(ROOT / "src"), str(HERE)]))
        self.assertEqual(done.stdout.strip(), "False False", done.stderr)

    def test_a_child_that_tries_a_toast_and_swallows_it_exits_with_1(self):
        code = ("import subprocess, sys\n"
                "sys.path.insert(0, %r)\n"
                "from test_no_real_toast import toast_command\n"
                "try:\n    subprocess.run(toast_command())\nexcept AssertionError:\n    pass\n"
                "print('swallowed')\n" % str(HERE))
        done = child(code, os.pathsep.join([str(ROOT / "src"), str(HERE)]))
        self.assertEqual(done.stdout.strip(), "swallowed")
        self.assertEqual(done.returncode, 1)
        self.assertIn(no_real_toast.MESSAGE, done.stderr)

    def test_the_lane_runner_installs_it_with_only_src_on_the_path(self):
        code = ("import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('test_parts', %r)\n"
                "parts = importlib.util.module_from_spec(spec); spec.loader.exec_module(parts)\n"
                "print('no_real_toast' in sys.modules, parts.no_real_toast(), "
                "sys.modules['no_real_toast'].active())\n" % str(ROOT / "scripts" / "test_parts.py"))
        done = child(code, str(ROOT / "src"))
        self.assertEqual(done.stdout.strip(), "False True True", done.stderr)


class NoImportTimeBindingTests(unittest.TestCase):
    """A default argument in src/ never names a function of another of the product's modules."""

    def product_names(self, path, tree):
        """Names bound in this file to the product's modules (`notify`), and to what was imported from
        them that is not a module (`show_content`), each -> where it came from."""
        known = srcscan.modules()
        module = srcscan.module_name(path)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        modules, members = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
                    target = ".".join(part for part in (".".join(base), node.module) if part)
                else:
                    target = node.module or ""
                if not (target == srcscan.PACKAGE or target.startswith(srcscan.PACKAGE + ".")):
                    continue
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if target + "." + alias.name in known:
                        modules[bound] = target + "." + alias.name
                    else:
                        members[bound] = target + "." + alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(srcscan.PACKAGE) and alias.asname:
                        modules[alias.asname] = alias.name
        return modules, members

    def test_no_default_argument_binds_a_product_function_at_import(self):
        found = []
        for path in srcscan.package_files():
            tree = ast.parse(srcscan.read(path))
            modules, members = self.product_names(path, tree)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                for value in list(node.args.defaults) + [item for item in node.args.kw_defaults if item]:
                    if (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                            and value.value.id in modules and not value.attr.isupper()):
                        found.append("%s:%d %s" % (srcscan.relative(path), value.lineno, ast.unparse(value)))
                    elif isinstance(value, ast.Name) and value.id in members and not value.id.isupper():
                        found.append("%s:%d %s" % (srcscan.relative(path), value.lineno, value.id))
        self.assertEqual(found, [], "default None and look it up when called: a default bound at import "
                                    "is out of reach of a test's patch")

    def test_the_rule_sees_the_binding_it_forbids(self):
        tree = ast.parse("from . import notify\n"
                         "from .notify import show_content\n"
                         "def deliver(notice, *, show=notify.show_content, other=show_content, "
                         "lines=notify.MAX_TOAST_LINES):\n    pass\n")
        path = srcscan.modules()["codex_auto_resume.notifier"]
        modules, members = self.product_names(path, tree)
        self.assertEqual(modules, {"notify": "codex_auto_resume.notify"})
        self.assertEqual(members, {"show_content": "codex_auto_resume.notify.show_content"})


if __name__ == "__main__":
    unittest.main()
