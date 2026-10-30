"""A run from source uses the newest Python installed (the owner, 2026-10-30).

`python src/auto_resume.py` ran under whichever `python` came first on PATH, and `install --startup` registered the
pythonw.exe beside it, so installing a newer Python changed nothing. src/codex_auto_resume/startup.py now reads PEP
514's registration (HKCU and HKLM Software\\Python\\PythonCore, read only) and picks the newest final, 64-bit, standard
CPython of at least MIN_PYTHON with a pythonw.exe beside it; the entry points start themselves again under it when a
person or Windows started them under another, and each start of a registered value resolves the newest again. The
installation's runtime is never left; CODEX_AUTO_RESUME_PYTHON pins one (`current` keeps the one running); `doctor` says
which and why. Every registry here is a fake list and every interpreter an empty file in a scratch folder: this
machine's Pythons and its Run key are never read or written.

    PYTHONPATH="src;tests" python -m unittest test_newest_python
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT / "src"), str(ROOT / "tests")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from codex_auto_resume import startup  # noqa: E402


class Scratch(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="car-newest-python-")))

    def interpreter(self, name, windowed=True):
        folder = self.folder / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "python.exe").write_bytes(b"")
        if windowed:
            (folder / "pythonw.exe").write_bytes(b"")
        return folder / "python.exe"

    def entry(self, tag, version, folder, architecture="64bit", paths=True):
        entry = {"tag": tag, "Version": version, "SysArchitecture": architecture, "InstallPath:": str(folder.parent)}
        if paths:
            entry["InstallPath:ExecutablePath"] = str(folder)
            entry["InstallPath:WindowedExecutablePath"] = str(folder.with_name("pythonw.exe"))
        return entry

    def registry(self, *entries):
        return lambda: list(entries)


class InstalledTests(Scratch):
    def test_only_final_64_bit_standard_builds_of_the_floor_or_newer_count(self):
        fine = self.interpreter("Python314")
        found = startup.installed_pythons(self.registry(
            self.entry("3.14", "3.14.10", fine),
            self.entry("3.15", "3.15.0rc1", self.interpreter("Python315rc")),       # a candidate
            self.entry("3.15-32", "3.15.2", self.interpreter("Python315-32"), architecture="32bit"),
            self.entry("3.15t", "3.15.2", self.interpreter("Python315t")),          # free-threaded
            self.entry("3.12", "3.12.10", self.interpreter("Python312")),           # below the floor
            self.entry("3.16", "3.16.0", self.interpreter("Python316", windowed=False)),   # no pythonw.exe
            self.entry("3.16-64", "3.16.1", self.folder / "gone" / "python.exe"),   # not there any more
            {"tag": "3.11", "InstallPath:": str(self.folder)},                    # no version at all (conda)
        ))
        self.assertEqual(found, [((3, 14, 10), fine)])

    def test_an_entry_without_executable_paths_is_read_from_its_folder(self):
        python = self.interpreter("Python315")
        found = startup.installed_pythons(self.registry(self.entry("3.15-64", "3.15.2", python, paths=False)))
        self.assertEqual(found, [((3, 15, 2), python.parent / "python.exe")])

    def test_the_registry_is_only_read(self):
        source = (ROOT / "src" / "codex_auto_resume" / "startup.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "_registered_pythons")
        text = ast.unparse(function)
        for write in ("SetValue", "CreateKey", "DeleteKey", "DeleteValue", "KEY_WRITE", "KEY_ALL_ACCESS",
                      "KEY_SET_VALUE"):
            self.assertNotIn(write, text)
        self.assertIn("KEY_READ | winreg.KEY_WOW64_64KEY", text)
        self.assertIn("HKEY_LOCAL_MACHINE", text)
        self.assertIn("HKEY_CURRENT_USER", text)


class ChoiceTests(Scratch):
    def choose(self, *entries, environ=None, running=((3, 13, 15), True), executable=None):
        executable = executable or self.interpreter("Running")
        return startup.choose_python(environ or {}, self.registry(*entries), executable, running)

    def test_the_newest_installed_is_chosen_over_an_older_one_running(self):
        newer = self.interpreter("Python314")
        older = self.interpreter("Python313")
        chosen = self.choose(self.entry("3.13", "3.13.15", older), self.entry("3.14", "3.14.10", newer))
        self.assertEqual(chosen, (newer, "3.14.10", "newest"))

    def test_the_one_running_stays_when_it_is_as_new_as_any_installed(self):
        running = self.interpreter("venv/Scripts")
        installed = self.interpreter("Python314")
        chosen = self.choose(self.entry("3.14", "3.14.10", installed), running=((3, 14, 10), True), executable=running)
        self.assertEqual(chosen, (running, "3.14.10", "running"))

    def test_one_running_that_cannot_run_the_watcher_gives_way_even_to_the_same_version(self):
        installed = self.interpreter("Python314")
        chosen = self.choose(self.entry("3.14", "3.14.10", installed), running=((3, 14, 10), False))
        self.assertEqual(chosen[2], "newest")

    def test_nothing_installed_falls_back_to_the_one_running(self):
        running = self.interpreter("Running")
        self.assertEqual(self.choose(executable=running), (running, "3.13.15", "running"))

    def test_the_installation_s_runtime_is_never_left(self):
        runtime = self.interpreter("home/runtime")
        (runtime.parent / "python314._pth").write_text("python314.zip\n.\n", encoding="utf-8")
        newer = self.interpreter("Python315")
        chosen = self.choose(self.entry("3.15", "3.15.2", newer), executable=runtime,
                             environ={startup.PYTHON_VARIABLE: str(newer)})
        self.assertEqual(chosen, (runtime, None, "bundled"))

    def test_the_variable_pins_a_python_a_pythonw_or_a_folder(self):
        pinned = self.interpreter("Pinned")
        newer = self.interpreter("Python315")
        for value in (pinned, pinned.with_name("pythonw.exe"), pinned.parent):
            with self.subTest(value=value):
                chosen = self.choose(self.entry("3.15", "3.15.2", newer), environ={startup.PYTHON_VARIABLE: str(value)})
                self.assertEqual(chosen, (pinned, None, "pinned"))

    def test_current_keeps_the_one_running_and_a_wrong_pin_is_said(self):
        running = self.interpreter("Running")
        newer = self.interpreter("Python315")
        self.assertEqual(self.choose(self.entry("3.15", "3.15.2", newer), executable=running,
                                     environ={startup.PYTHON_VARIABLE: "current"}), (running, None, "current"))
        self.assertEqual(self.choose(self.entry("3.15", "3.15.2", newer), executable=running,
                                     environ={startup.PYTHON_VARIABLE: str(self.folder / "nowhere")}),
                         (running, None, "pinned-missing"))

    def test_doctor_says_which_and_why(self):
        newer = self.interpreter("Python315")
        line = startup.describe_python({}, self.registry(self.entry("3.15", "3.15.2", newer)))
        if startup._same_path(newer, sys.executable):
            self.skipTest("the scratch interpreter is this one")
        self.assertIn(sys.executable, line)
        self.assertIn("a run from source starts %s 3.15.2 (the newest Python installed)" % newer, line)
        line = startup.describe_python({startup.PYTHON_VARIABLE: "current"}, self.registry())
        self.assertTrue(line.endswith("(kept by CODEX_AUTO_RESUME_PYTHON=current)"), line)

    def test_doctor_prints_the_line(self):
        source = (ROOT / "src" / "codex_auto_resume" / "commands" / "status.py").read_text(encoding="utf-8")
        body = source[source.index("def cmd_doctor"):source.index("backend = app.backend()", source.index("def cmd_doctor"))]
        self.assertIn('_print("python           : %s" % startup.describe_python())', body)


class Stream:
    def __init__(self, tty, number):
        self._tty, self._number = tty, number

    def isatty(self):
        return self._tty

    def fileno(self):
        return self._number

    def flush(self):
        pass


class RestartTests(Scratch):
    """again_under_chosen_python, with the process it would start stood in for."""

    def setUp(self):
        super().setUp()
        self.newer = self.interpreter("Python315")
        self.running = self.interpreter("Python313")
        self.reader = self.registry(self.entry("3.15", "3.15.2", self.newer))
        self.enterContext(mock.patch.object(startup.sys, "executable", str(self.running)))
        self.enterContext(mock.patch.object(startup.sys, "argv", ["auto_resume.py", "status"]))
        self.enterContext(mock.patch.object(startup.sys, "_xoptions", {}, create=True))
        self.enterContext(mock.patch.object(startup, "_running", return_value=((3, 13, 15), True)))
        self.enterContext(mock.patch.object(startup, "again_without_remote_debug", return_value=None))

    def streams(self, tty):
        if tty is None:
            return [mock.patch.object(startup.sys, name, None) for name in ("stdin", "stdout", "stderr")]
        return [mock.patch.object(startup.sys, name, Stream(tty, number))
                for number, name in enumerate(("stdin", "stdout", "stderr"))]

    def again(self, tty, environ=None):
        for patch in self.streams(tty):
            self.enterContext(patch)
        with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
            run.return_value.returncode = 7
            code = startup.again_under_chosen_python("auto_resume.py", environ or {}, self.reader)
        return code, run, popen

    def test_a_person_at_a_console_goes_on_under_the_newest_with_remote_debugging_off(self):
        code, run, popen = self.again(tty=True)
        self.assertEqual(code, 7)
        self.assertEqual(run.call_args.args[0], [str(self.newer), "-X", "disable-remote-debug", "auto_resume.py",
                                                 "status"])
        self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
        popen.assert_not_called()

    def test_a_start_by_windows_goes_on_detached_under_the_newest_pythonw(self):
        code, run, popen = self.again(tty=None)
        self.assertEqual(code, 0)
        self.assertEqual(popen.call_args.args[0], [str(self.newer.with_name("pythonw.exe")), "-X",
                                                   "disable-remote-debug", "auto_resume.py", "status"])
        run.assert_not_called()

    def test_a_run_a_program_started_keeps_its_interpreter(self):
        """A test, a script, the product itself with the option: pipes, not a terminal."""
        code, run, popen = self.again(tty=False)
        self.assertIsNone(code)
        run.assert_not_called()
        popen.assert_not_called()

    def test_a_process_the_product_started_never_chooses_again(self):
        startup.sys._xoptions["disable-remote-debug"] = True
        reader = mock.Mock(side_effect=AssertionError("the registry was read"))
        for patch in self.streams(True):
            self.enterContext(patch)
        with mock.patch("subprocess.run") as run:
            self.assertIsNone(startup.again_under_chosen_python("auto_resume.py", {}, reader))
        run.assert_not_called()

    def test_current_keeps_it_here(self):
        code, run, popen = self.again(tty=True, environ={startup.PYTHON_VARIABLE: "current"})
        self.assertIsNone(code)
        run.assert_not_called()


class EntryTests(unittest.TestCase):
    def test_the_two_entry_points_ask_before_their_main(self):
        for path, call in ((ROOT / "src" / "auto_resume.py", "again_under_chosen_python(__file__)"),
                           (ROOT / "scripts" / "plugin_setup.py", "startup.again_under_chosen_python(__file__)")):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("again = " + call, text[text.index('if __name__ == "__main__":'):])

    def test_one_floor(self):
        import re
        setup = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
        floor = tuple(int(part) for part in re.search(r"MIN_PYTHON = \((\d+), (\d+)\)", setup).groups())
        policy = json.loads((ROOT / "scripts" / "python_support.json").read_text(encoding="utf-8"))["minimum"]
        self.assertEqual(startup.MIN_PYTHON, floor)
        self.assertEqual("%d.%d" % startup.MIN_PYTHON, policy)


if __name__ == "__main__":
    unittest.main()
