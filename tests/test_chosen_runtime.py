"""Which Python an installation runs under (v0.6.23): the one record, its two readers, and the launcher that takes it up.

The record is the advanced edition's to write (control/pythons.py); here is what both editions' code does with it. Every
fallback ends at the bundled runtime, in Python and in C#, and the launcher hands the watcher to a chosen Python only on the
plug's word and takes it back when it does not come up. No real home, registry or watcher: every home is a temporary folder
and every process a stand-in.

    PYTHONPATH="src;tests" python -m unittest test_chosen_runtime
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import chosen_runtime as chosen  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, NULL, Plug, guard  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VERSION = "3.15.2"


def launcher_module():
    spec = importlib.util.spec_from_file_location("watcher_launcher_under_test", ROOT / "scripts" / "watcher_launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_home(folder, *, version=VERSION, advanced=True, record=True, files=None) -> Path:
    """An installation in `folder`: a bundled runtime, core's package, and, as asked, a chosen runtime and its record."""
    home = Path(folder)
    (home / "runtime").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (home / "runtime" / name).write_bytes(b"bundled")
    source = home / "app" / "src"
    (source / "codex_auto_resume").mkdir(parents=True)
    (source / "codex_auto_resume" / "__init__.py").write_text("", encoding="utf-8")
    if advanced:
        (source / "second_package").mkdir()
        (source / "second_package" / "__init__.py").write_text("", encoding="utf-8")
    if version is not None:
        where = home / "runtimes" / version
        where.mkdir(parents=True)
        for name in (chosen.required(version) if files is None else files):
            (where / name).write_bytes(b"chosen")
        if record:
            (home / "runtimes" / "chosen.json").write_text(json.dumps({"version": version, "at": 1}), encoding="utf-8")
    return home


class ReaderTests(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.folder = Path(made.name) / "home"

    def test_a_complete_chosen_runtime_is_the_answer(self):
        home = make_home(self.folder)
        self.assertEqual(chosen.chosen(home), VERSION)
        self.assertEqual(chosen.interpreter(home), home / "runtimes" / VERSION / "python.exe")
        self.assertEqual(chosen.interpreter(home, windowless=True), home / "runtimes" / VERSION / "pythonw.exe")

    def test_no_record_is_the_bundled_runtime(self):
        self.assertIsNone(chosen.interpreter(make_home(self.folder, record=False)))

    def test_every_record_that_is_no_record(self):
        home = make_home(self.folder)
        record = home / "runtimes" / "chosen.json"
        for text in ("", "not json", "[]", '{"version": 3}', '{"version": "3.15"}', '{"version": "2.7.18"}',
                     '{"version": "../../evil"}', '{"version": "3.15.2\\\\..\\\\x"}', '{"other": "3.15.2"}',
                     '{"version": "3.15.2", "pad": "%s"}' % ("x" * 5000)):
            with self.subTest(text[:30]):
                record.write_text(text, encoding="utf-8")
                self.assertIsNone(chosen.interpreter(home))

    def test_an_incomplete_runtime_is_the_bundled_one_whichever_file_is_gone(self):
        for name in chosen.required(VERSION):
            with self.subTest(name), tempfile.TemporaryDirectory() as folder:
                home = make_home(Path(folder) / "home")
                (home / "runtimes" / VERSION / name).unlink()
                self.assertEqual(chosen.recorded(home), VERSION, "the record still names it, for the card")
                self.assertIsNone(chosen.chosen(home))

    def test_a_runtime_folder_that_is_a_link_is_the_bundled_one(self):
        home = make_home(self.folder)
        target = self.folder.parent / "elsewhere"
        (home / "runtimes" / VERSION).rename(target)
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(home / "runtimes" / VERSION), str(target)],
                              capture_output=True, creationflags=NO_WINDOW)
        self.assertEqual(made.returncode, 0, "a junction needs no privilege")
        self.addCleanup(lambda: os.rmdir(home / "runtimes" / VERSION))
        self.assertIsNone(chosen.chosen(home))

    def test_the_required_files_follow_the_line(self):
        self.assertEqual(chosen.required("3.13.18"),
                         ("python.exe", "pythonw.exe", "python313.dll", "python313._pth", "python313.zip"))
        self.assertEqual(chosen.line_of("3.14.10"), "3.14")


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class CSharpReaderTests(unittest.TestCase):
    """gui/RuntimeChoice.cs, compiled as every launcher compiles it, gives the same answers."""

    @classmethod
    def setUpClass(cls):
        cls.made = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.made.cleanup)
        folder = Path(cls.made.name)
        probe = folder / "Probe.cs"
        probe.write_text('namespace CodexAutoResume { internal static class Probe { static int Main(string[] a) { '
                         'System.Console.Write(a.Length > 1 ? RuntimeChoice.BundledPython(a[0]) : RuntimeChoice.Python(a[0])); '
                         'return 0; } } }', encoding="utf-8")
        cls.exe = folder / "probe.exe"
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/reference:System.dll", "/out:" + str(cls.exe),
                        str(probe), str(ROOT / "gui" / "RuntimeChoice.cs")],
                       check=True, capture_output=True, timeout=180, creationflags=NO_WINDOW)

    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.folder = Path(made.name) / "home"

    def answer(self, home) -> str:
        return subprocess.run([str(self.exe), str(home)], capture_output=True, text=True, encoding="locale", errors="replace", timeout=30,
                              creationflags=NO_WINDOW, check=True).stdout

    def bundled(self, home) -> str:
        return str(home / "runtime" / "python.exe")

    def test_a_complete_chosen_runtime_is_the_answer(self):
        home = make_home(self.folder)
        self.assertEqual(self.answer(home), str(home / "runtimes" / VERSION / "python.exe"))

    def test_no_record(self):
        home = make_home(self.folder, record=False)
        self.assertEqual(self.answer(home), self.bundled(home))

    def test_a_standard_installation_never_takes_a_record(self):
        """Fails with AdvancedInstalled reverted: a record left behind by an edition change would still move it."""
        home = make_home(self.folder, advanced=False)
        self.assertEqual(self.answer(home), self.bundled(home))

    def test_every_record_that_is_no_record(self):
        home = make_home(self.folder)
        record = home / "runtimes" / "chosen.json"
        for text in ("", "not json", "[]", '{"version": 3}', '{"version": "3.15"}', '{"version": "2.7.18"}',
                     '{"version": "../../evil"}', '{"other": "3.15.2"}', '{"version": "3.15.2", "pad": "%s"}' % ("x" * 5000)):
            with self.subTest(text[:30]):
                record.write_text(text, encoding="utf-8")
                self.assertEqual(self.answer(home), self.bundled(home))

    def test_an_incomplete_runtime_whichever_file_is_gone(self):
        for name in chosen.required(VERSION):
            with self.subTest(name), tempfile.TemporaryDirectory() as folder:
                home = make_home(Path(folder) / "home")
                (home / "runtimes" / VERSION / name).unlink()
                self.assertEqual(self.answer(home), self.bundled(home))

    def test_no_app_folder_at_all(self):
        home = make_home(self.folder)
        import shutil
        shutil.rmtree(home / "app")
        self.assertEqual(self.answer(home), self.bundled(home))

    def test_the_two_readers_ask_for_the_same_files(self):
        """Fails when a required file is added on one side only."""
        text = (ROOT / "gui" / "RuntimeChoice.cs").read_text(encoding="utf-8")
        self.assertIn('"python.exe", "pythonw.exe", stem + ".dll", stem + "._pth", stem + ".zip"', text)


class WhoAsksTests(unittest.TestCase):
    def read(self, name) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_the_bridges_and_launchers_go_through_the_reader(self):
        """Fails with any of them put back on the fixed path."""
        for name in ("gui/McpLauncher.cs", "gui/HookLauncher.cs"):
            with self.subTest(name):
                self.assertIn("RuntimeChoice.Python(home)", self.read(name))
                self.assertNotIn('"runtime", "python.exe"', self.read(name))
        for name in ("gui/Dashboard.cs", "gui/SettingsApp.cs"):
            with self.subTest(name):
                self.assertIn("RuntimeChoice.Python(root)", self.read(name))

    def test_what_must_outlive_a_broken_choice_stays_on_the_bundled_runtime(self):
        """Repair and the setup window's own step run on the bundled runtime, so a broken choice cannot stop them."""
        self.assertIn('Path.Combine(root, "runtime", "python.exe")', self.read("gui/DashboardMaintenance.cs"))
        self.assertIn('Path.Combine(Path.Combine(home, "runtime"), "python.exe")', self.read("gui/InstallerFlow.cs"))

    def test_the_mcp_launcher_is_built_with_the_reader(self):
        self.assertIn("gui\\RuntimeChoice.cs", self.read("build/make_gui.ps1"))

    def test_the_long_lived_bridge_leaves_a_broken_choice(self):
        """Fails with FailedLocked reverted: a broken chosen Python would keep the page, and its Back, out of reach."""
        text = self.read("gui/Dashboard.cs")
        self.assertEqual(text.count("FailedLocked();"), 2, "both calls that can fail")
        self.assertIn("python = bundled;", text)
        self.assertIn("once.UseBundled();", text)

    def test_the_installer_knows_the_folder(self):
        """The watcher under a chosen Python is stopped for an update, uninstall removes the folder, the standard edition drops it."""
        text = self.read("build/install/install.ps1")
        self.assertIn("(Test-PathInside $exe $ChosenRuntimes)", text)
        self.assertIn("@((Join-Path (Split-Path -Parent $RunDir) 'runtimes'), $AppDir, $RunDir)", text)
        self.assertIn("$editionChange -and $edition -eq 'standard' -and (Test-Path -LiteralPath $ChosenRuntimes)", text)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.home = make_home(Path(made.name) / "home")
        self.launcher = launcher_module()
        self.asked = []
        self.answers = {self.launcher.PHASE_RUNTIME: self.launcher.SUPERVISE}
        patcher = patch.object(self.launcher, "_supervise", self.supervise)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("_note", "_complain"):
            patcher = patch.object(self.launcher, name, lambda *_a: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("codex_auto_resume.runtime.app.App")
        self.app = patcher.start()
        self.addCleanup(patcher.stop)
        self.app.return_value.watcher_running.return_value = False

    def supervise(self, _home, facts):
        self.asked.append(facts["phase"])
        return self.answers.get(facts["phase"], DEFER)

    def child(self, code=0):
        process = MagicMock()
        process.pid = 4242
        process.wait.return_value = code
        return process

    def test_it_waits_as_long_as_setup_does(self):
        """Fails when either moves alone: setup waits for control's start timeout, and the launcher keeps its own copy of the number."""
        from codex_auto_resume import control
        spec = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
        self.assertIn("WATCHER_WAIT = control.WATCHER_START_TIMEOUT", spec)
        self.assertEqual(self.launcher.WATCHER_WAIT, control.WATCHER_START_TIMEOUT)

    def test_the_answer_passes_the_guard_every_plug_is_asked_through(self):
        """Fails with another word: the guard turns anything outside the point's closed set into DEFER, and no choice is taken up."""
        class Answers(Plug):
            __slots__ = ()

            def supervise(self, facts):
                return "supervise"
        self.assertEqual(guard(Answers()).supervise({"phase": self.launcher.PHASE_RUNTIME}), self.launcher.SUPERVISE)

    def test_with_no_record_the_plug_is_not_even_asked(self):
        """Fails with the record's look reverted: every launch of every installation would ask one more question."""
        (self.home / "runtimes" / "chosen.json").unlink()
        self.assertIsNone(self.launcher._on_chosen(self.home, self.home))
        self.assertEqual(self.asked, [])

    def test_the_standard_edition_answers_nothing_and_nothing_is_started(self):
        """NULL defers: fails if the launcher took a record on its own."""
        self.assertIs(NULL.supervise({"phase": self.launcher.PHASE_RUNTIME}), DEFER)
        self.answers = {}
        with patch("subprocess.Popen") as started:
            self.assertIsNone(self.launcher._on_chosen(self.home, self.home))
        started.assert_not_called()

    def test_the_watcher_runs_under_the_chosen_python(self):
        made = self.child(3)
        with patch("subprocess.Popen", return_value=made) as started, patch.object(self.launcher, "_came_up", return_value=True):
            self.assertEqual(self.launcher._on_chosen(self.home, self.home), 3)
        argv = started.call_args[0][0]
        self.assertEqual(argv[0], str(self.home / "runtimes" / VERSION / "pythonw.exe"))
        self.assertEqual(argv[1:3], list(self.launcher.NO_REMOTE_DEBUG))
        self.assertEqual(argv[-2:], ["run", self.launcher.CHILD_ARGUMENT])
        self.assertTrue(started.call_args[1]["creationflags"] & NO_WINDOW)
        self.assertNotIn(self.launcher.PHASE_RUNTIME_FAILED, self.asked)

    def test_one_that_does_not_come_up_is_ended_and_taken_back(self):
        """Fails with the check reverted: a chosen Python that never starts leaves no watcher at all."""
        made = self.child()
        with patch("subprocess.Popen", return_value=made), patch.object(self.launcher, "_came_up", return_value=False):
            self.assertIsNone(self.launcher._on_chosen(self.home, self.home), "the watcher goes on here, on the bundled runtime")
        made.kill.assert_called_once()
        self.assertEqual(self.asked, [self.launcher.PHASE_RUNTIME, self.launcher.PHASE_RUNTIME_FAILED])

    def test_one_windows_refuses_to_start_is_taken_back(self):
        with patch("subprocess.Popen", side_effect=OSError("no")):
            self.assertIsNone(self.launcher._on_chosen(self.home, self.home))
        self.assertIn(self.launcher.PHASE_RUNTIME_FAILED, self.asked)

    def test_a_watcher_already_running_is_left_alone(self):
        self.app.return_value.watcher_running.return_value = True
        with patch("subprocess.Popen") as started:
            self.assertIsNone(self.launcher._on_chosen(self.home, self.home))
        started.assert_not_called()

    def test_a_chosen_runtime_gone_since_the_plug_answered_is_the_bundled_one(self):
        (self.home / "runtimes" / "chosen.json").unlink()
        with patch("subprocess.Popen") as started:
            self.assertIsNone(self.launcher._on_chosen(self.home, self.home))
        started.assert_not_called()

    def test_a_launcher_started_under_a_chosen_python_starts_again_under_the_bundled_one(self):
        """Fails with it reverted: Back from a Dashboard on the chosen Python would leave the watcher on it."""
        inside = self.home / "runtimes" / VERSION / "pythonw.exe"
        with patch.object(self.launcher.sys, "executable", str(inside)), patch("subprocess.Popen") as started:
            self.assertEqual(self.launcher._on_chosen(self.home, self.home), 0)
        self.assertEqual(started.call_args[0][0][0], str(self.home / "runtime" / "pythonw.exe"))
        self.assertEqual(self.asked, [], "the plug is asked by the launcher that stays")

    def test_the_log_says_how_long_each_step_of_a_chosen_start_took(self):
        """Fails without the times (v0.6.23-beta.2): 41-48 s from the launcher to its child on the owner's PC, and nothing in
        launcher.log to say which step took them. The question, the child's start and its coming up each say when."""
        said = []
        with patch.object(self.launcher, "_note", lambda _here, text: said.append(text)), \
                patch("subprocess.Popen", return_value=self.child(0)), patch.object(self.launcher, "_came_up", return_value=True):
            self.assertEqual(self.launcher._on_chosen(self.home, self.home), 0)
        timed = [line for line in said if re.search(r"[0-9]+\.[0-9] s since the launcher started", line)]
        self.assertEqual(len(timed), 3, said)
        self.assertIn("asked which Python", timed[0])
        self.assertIn("supervised child (pid 4242) under the chosen Python", timed[1])
        self.assertIn("came up under the chosen Python", timed[2])

    def test_the_wait_is_counted_from_the_child_s_start(self):
        """The 45 s the statement names are the chosen Python's own: the wait begins once its child exists, however long the
        question before it took. Fails with the wait begun before the child was started."""
        order = []

        def started(*_a, **_k):
            order.append("child")
            return self.child(0)

        def waited(_home, child):
            order.append("wait")
            return True
        with patch("subprocess.Popen", side_effect=started), patch.object(self.launcher, "_came_up", side_effect=waited):
            self.launcher._on_chosen(self.home, self.home)
        self.assertEqual(order, ["child", "wait"])

    def test_came_up_is_the_mutex_within_the_wait_and_one_more_look(self):
        probe = self.app.return_value.watcher_running
        with patch("codex_auto_resume.control.watcher.await_watcher", return_value={"state": "running"}) as waited:
            self.assertTrue(self.launcher._came_up(self.home, self.child()))
        self.assertEqual(waited.call_args[1]["timeout"], self.launcher.WATCHER_WAIT)
        with patch("codex_auto_resume.control.watcher.await_watcher", return_value={"state": "exited"}):
            self.assertFalse(self.launcher._came_up(self.home, self.child()))
        probe.return_value = True
        with patch("codex_auto_resume.control.watcher.await_watcher", return_value={"state": "unconfirmed"}):
            self.assertTrue(self.launcher._came_up(self.home, self.child()))
        probe.return_value = False
        with patch("codex_auto_resume.control.watcher.await_watcher", return_value={"state": "unconfirmed"}):
            self.assertFalse(self.launcher._came_up(self.home, self.child()))


class StandardEditionTests(unittest.TestCase):
    def test_the_standard_tree_holds_none_of_the_feature(self):
        """Only the record's reader is core's: the fetch, the verification, the card and the words are the advanced edition's."""
        for pattern in ("src/**/*.py", "scripts/*.py", "gui/*.cs"):
            for path in ROOT.glob(pattern):
                text = path.read_text(encoding="utf-8", errors="replace")
                with self.subTest(str(path.relative_to(ROOT))):
                    for word in ("python_choice", "pythonorg", "embed-amd64.zip" if "bootstrap" not in path.name else "python_choice",
                                 "Python Software Foundation"):
                        self.assertNotIn(word, text)

    def test_the_record_is_never_written_by_core(self):
        text = (ROOT / "src" / "codex_auto_resume" / "chosen_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("write_text", text)
        self.assertNotIn("os.replace", text)


if __name__ == "__main__":
    unittest.main()
