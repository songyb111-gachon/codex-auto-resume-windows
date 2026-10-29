"""The launcher as the watcher's supervisor (v0.6.19, crash_restart; plans/v0619-design/D-watcher-ops.md A).

Where P13 answers SUPERVISE at the start, scripts/watcher_launcher.py runs the watcher as a child - itself again, under
pythonw.exe, with CREATE_NO_WINDOW and constant arguments - waits for it, asks P13 again once it ended, and starts it once
more only on RESTART. A child never supervises; a child that ended because the state is newer than its code has started
the installed copy itself and is not asked about; where no child can be started the watcher runs in the launcher's own
process, as with no supervisor. Every process here is a fake: nothing is started.

    PYTHONPATH="src;tests" python -m unittest test_launcher_supervisor
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import edition  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, NULL, Alternative  # noqa: E402
from test_plug_points import Asked  # noqa: E402


class Child:
    """A fake child process: the exit codes it ends with, one per start, from the list its case holds."""
    started = []
    codes = []

    def __init__(self, argv, **options):
        if Child.fail:
            raise OSError("cannot start")
        self.argv, self.options, self.pid = argv, options, 4242 + len(Child.started)
        Child.started.append(self)

    def wait(self, timeout=None):
        return Child.codes.pop(0)


class SupervisorCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Resolved, as the launcher resolves its own folder (Path(__file__).resolve()): a TEMP spelt in 8.3 form - a CI
        # runner's RUNNER~1 for runneradmin - is another spelling of the same folder.
        self.home = Path(self.temporary.name).resolve()
        copy = self.home / "watcher-launcher.py"
        shutil.copyfile(ROOT / "scripts" / "watcher_launcher.py", copy)
        (self.home / "runtime.json").write_text(json.dumps({"home": str(self.home)}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("watcher_launcher_supervisor", copy)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(self.launcher.RELAUNCH_MARK, None)
        # An interpreter folder of its own with a pythonw.exe beside python.exe, so the child's interpreter is known.
        self.bin = self.home / "python"
        self.bin.mkdir()
        for name in ("python.exe", "pythonw.exe"):
            (self.bin / name).write_bytes(b"")
        Child.started, Child.codes, Child.fail = [], [], False

    def launch(self, argv, found, codes=(), watcher_code=0, executable=None):
        """The launcher's main with `found` as the plug, children that end with `codes` in turn, and a watcher run here
        that returns `watcher_code`: (what it returned, the watcher runs here, the relaunches)."""
        Child.codes = list(codes)
        with patch.object(self.launcher, "resolve_plugin_root", return_value=ROOT), \
                patch("codex_auto_resume.cli.main", return_value=watcher_code) as watcher, \
                patch.object(self.launcher, "_relaunch_once") as relaunch, \
                patch.object(self.launcher, "_ended_cleanly", return_value=False), \
                patch.object(subprocess, "Popen", Child), \
                patch.object(sys, "executable", str(executable or self.bin / "python.exe")), \
                patch.object(edition, "plug", return_value=found):
            returned = self.launcher.main(argv)
        return returned, [call.args for call in watcher.call_args_list], [call.args for call in relaunch.call_args_list]

    @staticmethod
    def answering(*ended):
        """A plug that answers SUPERVISE at the start and, at each end in turn, the next of `ended`."""
        answers = list(ended)

        def supervise(facts):
            if facts.get("phase") == "start":
                return Alternative.SUPERVISE
            return answers.pop(0) if answers else DEFER
        return Asked(supervise=supervise)

    def child_argv(self):
        # Remote debugging off right after the interpreter (v0.6.19-beta.3, tests/test_remote_debug_off.py).
        return [str((self.bin / "pythonw.exe").resolve()), "-X", "disable-remote-debug",
                str((self.home / "watcher-launcher.py").resolve()), "run", self.launcher.CHILD_ARGUMENT]


class SuperviseTests(SupervisorCase):
    def test_supervise_runs_the_watcher_as_a_child_with_no_window_and_returns_its_code(self):
        """Fails with the supervisor reverted: the watcher runs here and no child is started."""
        plug = self.answering()
        returned, runs, relaunches = self.launch([], plug, codes=[0])
        self.assertEqual((returned, runs, relaunches), (0, [], []))
        (child,) = Child.started
        self.assertEqual(child.argv, self.child_argv())
        self.assertEqual(child.options["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(child.options[stream], subprocess.DEVNULL)
        self.assertEqual(plug.asked, [("supervise", ({"phase": "start"},)),
                                      ("supervise", ({"phase": "ended", "exit_code": 0, "clean": False},))])

    def test_restart_starts_it_once_more_and_defer_returns_the_last_code(self):
        plug = self.answering(Alternative.RESTART, Alternative.RESTART, DEFER)
        returned, runs, _ = self.launch([], plug, codes=[1, 7, 1])
        self.assertEqual((returned, runs), (1, []))
        self.assertEqual(len(Child.started), 3)
        self.assertEqual([facts for _, (facts,) in plug.asked[1:]],
                         [{"phase": "ended", "exit_code": code, "clean": False} for code in (1, 7, 1)])
        for child in Child.started:
            self.assertEqual(child.argv, self.child_argv())

    def test_a_child_that_found_the_state_newer_is_not_asked_about(self):
        """It started the installed copy once itself (_relaunch_once): its code is returned, nothing more asked."""
        plug = self.answering(Alternative.RESTART)
        returned, runs, relaunches = self.launch([], plug, codes=[self.launcher.EXIT_SCHEMA_NEWER])
        self.assertEqual((returned, runs, relaunches), (4, [], []))
        self.assertEqual(len(plug.asked), 1)

    def test_with_no_pythonw_or_no_child_started_the_watcher_runs_here_and_nothing_more_is_asked(self):
        lone = self.home / "lone"
        lone.mkdir()
        (lone / "python.exe").write_bytes(b"")
        plug = self.answering(Alternative.RESTART)
        returned, runs, _ = self.launch([], plug, watcher_code=1, executable=lone / "python.exe")
        self.assertEqual((returned, runs), (1, [(["--home", str(self.home), "--quiet", "run"],)]))
        self.assertEqual((Child.started, len(plug.asked)), ([], 1))
        Child.fail = True
        plug = self.answering(Alternative.RESTART)
        returned, runs, _ = self.launch([], plug, watcher_code=1)
        self.assertEqual((returned, len(runs), len(plug.asked)), (1, 1, 1))

    def test_a_restart_that_cannot_start_ends_with_an_error(self):
        plug = self.answering(Alternative.RESTART)
        Child.codes = [1]
        original = Child.__init__

        def once(child, argv, **options):
            if Child.started:
                raise OSError("cannot start")
            original(child, argv, **options)
        with patch.object(Child, "__init__", once):
            returned, runs, _ = self.launch([], plug, codes=[1])
        self.assertEqual((returned, runs), (self.launcher.EXIT_ERROR, []))


class ChildTests(SupervisorCase):
    def test_a_child_runs_the_watcher_here_and_asks_nothing(self):
        """No grandchildren: the child's own launcher never supervises, whatever the plug would say."""
        for code in (0, 1, 5):
            with self.subTest(code=code):
                plug = self.answering(Alternative.RESTART)
                returned, runs, relaunches = self.launch(["run", self.launcher.CHILD_ARGUMENT], plug, watcher_code=code)
                self.assertEqual((returned, runs, relaunches),
                                 (code, [(["--home", str(self.home), "--quiet", "run"],)], []))
                self.assertEqual((plug.asked, Child.started), ([], []))

    def test_a_child_that_finds_the_state_newer_relaunches_once_as_today(self):
        plug = self.answering()
        returned, runs, relaunches = self.launch(["run", self.launcher.CHILD_ARGUMENT], plug,
                                                 watcher_code=self.launcher.EXIT_SCHEMA_NEWER)
        self.assertEqual((returned, relaunches), (4, [(self.home, ["run"])]))
        self.assertEqual(plug.asked, [])


class NullTests(SupervisorCase):
    def test_with_null_no_child_is_ever_started(self):
        for code in (0, 1, 3, 4, 5):
            with self.subTest(code=code):
                returned, runs, _ = self.launch([], NULL, watcher_code=code)
                self.assertEqual((returned, len(runs), Child.started), (code, 1, []))


class ClosedWordTests(SupervisorCase):
    def test_the_child_s_arguments_are_constants_whatever_the_plug_answers(self):
        """A plug's answer is a closed word compared with the launcher's own; nothing of it is passed to the child."""
        for start in (Alternative.SUPERVISE, "supervise"):
            with self.subTest(start=start):
                plug = Asked(supervise=lambda facts, start=start: start if facts["phase"] == "start" else DEFER)
                Child.started = []
                self.launch([], plug, codes=[2])
                (child,) = Child.started
                self.assertEqual(child.argv, self.child_argv())

    def test_the_popen_in_the_supervisor_takes_no_name_but_its_own_constants(self):
        """The one Popen of `_supervised` is handed `arguments`, built from the interpreter, this file and two
        constants - never from a value `_supervise` returned."""
        tree = ast.parse((ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_supervised")
        built = next(node for node in ast.walk(function) if isinstance(node, ast.Assign)
                     and getattr(node.targets[0], "id", None) == "arguments")
        names = {node.id for node in ast.walk(built.value) if isinstance(node, ast.Name)}
        self.assertEqual(names, {"str", "interpreter", "NO_REMOTE_DEBUG", "Path", "__file__", "CHILD_ARGUMENT"})
        popen = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and getattr(node.func, "attr", None) == "Popen"]
        self.assertEqual(len(popen), 1)
        self.assertEqual(getattr(popen[0].args[0], "id", None), "arguments")


if __name__ == "__main__":
    unittest.main()
