"""A chosen Python's runtime is taken away whole once nothing runs from it, never file by file (v0.6.23 final, M1 of the
second round's advanced audit).

The sweep deleted a runtime with rmtree, which takes every file not held open: under the Dashboard's bridges, Codex's MCP
server or the watcher still on it, the ._pth and every module not loaded yet went, and what was left sat under the
version's name. Now one a program runs from (a program file Windows will not open for writing) stays whole for a later
sweep, one that does not is renamed aside first and deleted there, and the launcher's question at the next start sweeps
what was left. Temporary homes only; the one real process, in InUseProbeTests, is a copy of this interpreter in a temporary
folder, started with no window.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_python_retire.py
"""
from __future__ import annotations

import builtins
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume import chosen_runtime as chosen  # noqa: E402
from codex_auto_resume_advanced.control import pythons  # noqa: E402
from test_advanced_python_choice import FakeRuntime  # noqa: E402

OLD, NEW = "3.14.9", "3.15.2"
REAL_OPEN = builtins.open


class Case(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.home = Path(made.name) / "home"
        (self.home / "runtime").mkdir(parents=True)
        self.runtime = FakeRuntime(self.home)

    def runtime_folder(self, version, extra=("_socket.pyd", "python3.dll")):
        where = chosen.folder(self.home, version)
        where.mkdir(parents=True)
        for name in chosen.required(version) + tuple(extra):
            (where / name).write_bytes(b"x")
        return where

    def held(self, *names):
        """Windows' answer for a program file a running process has mapped: it will not be opened for writing."""
        def opened(path, mode="r", *args, **kwargs):
            if Path(path).name in names and "+" in mode:
                raise PermissionError(13, "in use")
            return REAL_OPEN(path, mode, *args, **kwargs)
        return patch("builtins.open", opened)

    def names(self):
        return sorted(entry.name for entry in chosen.root(self.home).iterdir())


class RetireTests(Case):
    def test_a_runtime_a_program_runs_from_is_left_whole(self):
        """Fails with M1 reverted: rmtree takes the ._pth, the zip and the modules not loaded, and leaves the rest."""
        where = self.runtime_folder(OLD)
        before = sorted(entry.name for entry in where.iterdir())
        with self.held("pythonw.exe", "python314.dll"):
            pythons._sweep(self.home, None)
        self.assertEqual(sorted(entry.name for entry in where.iterdir()), before, "not one file taken")
        self.assertTrue(chosen.complete(self.home, OLD))

    def test_one_nothing_runs_from_goes_whole_and_leaves_no_name_behind(self):
        self.runtime_folder(OLD)
        self.runtime_folder(NEW)
        pythons._sweep(self.home, NEW)
        self.assertEqual(self.names(), [NEW])

    def test_what_cannot_be_deleted_now_is_never_under_a_version_s_name_and_goes_at_the_next_sweep(self):
        self.runtime_folder(OLD)
        with patch.object(pythons, "_remove", lambda folder: None):       # a file that would not go, this time
            pythons._sweep(self.home, None)
        (left,) = self.names()
        self.assertTrue(left.startswith(pythons.GONE), left)
        self.assertFalse(chosen.shaped(left))
        self.assertIsNone(chosen.chosen(self.home))
        pythons._sweep(self.home, None)
        self.assertEqual(self.names(), [])

    def test_a_folder_that_cannot_be_listed_is_taken_as_in_use(self):
        where = self.runtime_folder(OLD)
        with patch.object(Path, "iterdir", side_effect=OSError("busy")):
            self.assertTrue(pythons._in_use(where))

    def test_choosing_again_a_version_still_in_use_never_half_deletes_it(self):
        """`use` clears its target first: one a program runs from is refused at unpack, whole."""
        where = self.runtime_folder(NEW)
        incoming = chosen.root(self.home) / (pythons.INCOMING + NEW + ".zip")
        with self.held("python.exe"), self.assertRaises(pythons._Failed) as failed:
            pythons._prepared(incoming, where)
        self.assertEqual(failed.exception.step, pythons.UNPACK)
        self.assertTrue(chosen.complete(self.home, NEW))

    def test_the_next_start_sweeps_what_was_left_but_never_the_runtime_it_runs_on(self):
        self.runtime_folder(OLD)
        self.runtime_folder(NEW)
        pythons._write(chosen.root(self.home) / chosen.RECORD, {"version": NEW})
        self.assertIs(pythons.supervised(self.runtime, {"phase": pythons.PHASE_RUNTIME}), pythons.USE_CHOSEN)
        self.assertEqual(self.names(), [NEW, chosen.RECORD])

    def test_with_no_record_the_start_reads_nothing(self):
        self.runtime_folder(OLD)
        with patch.object(pythons, "_sweep") as swept:
            pythons.supervised(self.runtime, {"phase": pythons.PHASE_RUNTIME})
        swept.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows maps a running program's files")
class InUseProbeTests(Case):
    def test_a_running_interpreter_s_folder_is_seen_in_use_and_free_once_it_ended(self):
        """The probe against Windows itself: a copy of this interpreter, run from a runtime folder, with no window."""
        base = Path(sys.base_prefix)
        stem = "python3%d" % sys.version_info[1]
        names = ("pythonw.exe", stem + ".dll", "python3.dll", "vcruntime140.dll")
        if not all((base / name).is_file() for name in names):
            self.skipTest("this interpreter's folder is not laid out as python.org's")
        where = chosen.folder(self.home, OLD)
        where.mkdir(parents=True)
        for name in names:
            shutil.copy2(base / name, where / name)
        self.assertFalse(pythons._in_use(where))
        process = subprocess.Popen([str(where / "pythonw.exe"), "-I", "-c", "import time; time.sleep(30)"],
                                   env=dict(os.environ, PYTHONHOME=str(base)), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 20
            while not pythons._in_use(where) and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.1)
            self.assertTrue(pythons._in_use(where))
            pythons._sweep(self.home, None)
            self.assertEqual(sorted(entry.name for entry in where.iterdir()), sorted(names), "left whole while it runs")
        finally:
            process.kill()
            process.wait(timeout=10)
        deadline = time.monotonic() + 10
        while pythons._in_use(where) and time.monotonic() < deadline:
            time.sleep(0.1)
        pythons._sweep(self.home, None)
        self.assertFalse(where.exists())


if __name__ == "__main__":
    unittest.main()
