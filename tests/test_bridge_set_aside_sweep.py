"""The Dashboard's bridge sweeps what an update set aside and could not delete (v0.6.24, the owner 2026-11-15).

An in-app update renames the running CodexAutoResumeSettings.exe - the window that runs the update - to
`.old-<stamp>`. The watcher's sweep (runtime/setaside.py) runs as the watcher starts, while that window is still open,
so the v0.6.23 final's live acceptance found the previous exe in the installation after the in-app update, until the
next install; an update over a stopped watcher starts no watcher at all. The long-lived bridge of the Dashboard that
opens after it (controlcli serve) now runs the same sweep, with every gate it has, soon after it starts and again
while anything is still in use (controlcli.sweep_soon, SWEEP_AFTER).

Scratch homes only; the installer's lock is answered here, never asked of this PC.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_auto_resume import config, controlcli, windows
from codex_auto_resume.control import Control
from codex_auto_resume import setaside

STAMP = "20261115022653"


class SweepSoonTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(str(Path(folder.name) / "home"))
        self.assertTrue(self.paths.claim_home())
        self.home = self.paths.home
        self.control = Control(self.paths)
        self.waited = []
        guard = patch.object(windows, "install_in_progress", return_value=False)
        guard.start()
        self.addCleanup(guard.stop)

    def run_soon(self, wait=None):
        worker = controlcli.sweep_soon(self.control, wait=wait or self.waited.append)
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertTrue(worker.daemon, "never keeps the bridge alive")

    def test_an_old_window_still_open_is_left_and_taken_once_it_has_gone(self):
        old = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old.write_bytes(b"MZ" * 1000)
        handle = open(old, "rb")             # as a running program holds its file: no delete while open
        self.addCleanup(lambda: handle.closed or handle.close())

        def wait(seconds):
            self.waited.append(seconds)
            if len(self.waited) == 3:
                handle.close()               # the old window closed between two looks

        self.run_soon(wait)
        self.assertFalse(old.exists())
        self.assertEqual(self.waited, list(controlcli.SWEEP_AFTER[:3]), "looked again while it was in use, then stopped")

    def test_it_stops_after_a_look_that_leaves_nothing(self):
        old = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old.write_bytes(b"MZ")
        keep = self.home / "CodexAutoResumeSettings.exe"
        keep.write_bytes(b"MZ")
        self.run_soon()
        self.assertFalse(old.exists())
        self.assertTrue(keep.exists(), "the program itself is never one")
        self.assertEqual(self.waited, [controlcli.SWEEP_AFTER[0]], "the first look waits for the window's reads")
        self.assertGreater(controlcli.SWEEP_AFTER[0], 0)

    def test_a_copy_in_use_to_the_end_is_left_for_the_next_start(self):
        old = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old.write_bytes(b"MZ")
        with open(old, "rb"):
            self.run_soon()
            self.assertTrue(old.exists())
        self.assertEqual(self.waited, list(controlcli.SWEEP_AFTER))

    def test_the_watchers_gates_hold_and_it_looks_again_while_they_are_closed(self):
        """It is the watcher's own sweep: nothing while an install runs, or its copy journal is there - and a closed
        gate is a reason to look again later, not an end (the v0.6.24 review: a Dashboard opened during an update or a
        Repair looked once and never again)."""
        old = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old.write_bytes(b"MZ")
        with patch.object(windows, "install_in_progress", return_value=True):
            self.run_soon()
        self.assertTrue(old.exists())
        self.assertEqual(self.waited, list(controlcli.SWEEP_AFTER), "every look of the window, the gate closed")
        self.waited.clear()
        (self.home / setaside.JOURNAL).write_text("{}", encoding="utf-8")
        self.run_soon()
        self.assertTrue(old.exists())
        self.assertEqual(self.waited, list(controlcli.SWEEP_AFTER))

    def test_an_install_that_ends_between_two_looks_is_swept_after_it(self):
        old = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old.write_bytes(b"MZ")
        with patch.object(windows, "install_in_progress", side_effect=[True, False]):
            self.run_soon()
        self.assertFalse(old.exists())
        self.assertEqual(self.waited, list(controlcli.SWEEP_AFTER[:2]))

    def test_a_failure_ends_the_sweep_and_nothing_else(self):
        with patch.object(setaside, "sweep", side_effect=OSError("no")) as sweep:
            self.run_soon()
        self.assertEqual(sweep.call_count, 1)


class RunningProgramTests(unittest.TestCase):
    """A folder a running program's file lies in is never deleted (the v0.6.24 review): Windows renames a folder while
    a program runs from it, so the rename alone did not keep the sweep away from it."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(str(Path(folder.name) / "home"))
        self.assertTrue(self.paths.claim_home())
        self.home = self.paths.home

    def sweep(self, **given):
        return setaside.sweep(self.paths, installing=lambda: False, **given)

    def plant(self, name="runtime.old-" + STAMP) -> Path:
        tree = self.home / name
        (tree / "Lib").mkdir(parents=True)
        (tree / "lib.py").write_text("x", encoding="utf-8")
        (tree / "Lib" / "json.py").write_text("x", encoding="utf-8")
        return tree

    @unittest.skipUnless(os.name == "nt" and Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                                  "PING.EXE").is_file(), "needs Windows' PING.EXE")
    def test_nothing_is_deleted_while_a_program_runs_from_it_and_all_once_it_has_ended(self):
        tree = self.plant()
        program = tree / "PING.EXE"
        shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE"), program)
        running = subprocess.Popen([str(program), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=0x08000000)
        self.addCleanup(lambda: running.poll() is None and (running.kill(), running.wait()))
        try:
            for _ in range(50):                          # until Windows lists it
                if str(program).lower() in (os.path.normcase(image) for image in windows.running_images() or ()):
                    break
                time.sleep(0.1)
            self.assertEqual(self.sweep(), (0, 1))
            self.assertTrue(all(path.exists() for path in (program, tree / "lib.py", tree / "Lib" / "json.py")),
                            "nothing around the running program deleted")
            self.assertEqual(running.poll(), None)
        finally:
            running.kill()
            running.wait()
        self.assertEqual(self.sweep(), (1, 0), "taken once it has ended")
        self.assertFalse(tree.exists())

    def test_where_the_list_cannot_be_made_every_folder_is_left(self):
        tree = self.plant()
        old = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old.write_bytes(b"MZ")
        self.assertEqual(self.sweep(running=lambda: None), (1, 1))
        self.assertTrue(tree.exists())
        self.assertFalse(old.exists(), "a file is its own proof: Windows refuses to delete a running program")
        self.assertEqual(self.sweep(running=self.fail_to_list), (0, 1))
        self.assertTrue(tree.exists())

    @staticmethod
    def fail_to_list():
        raise OSError("no snapshot")

    def test_a_program_elsewhere_or_in_a_folder_of_a_like_name_holds_nothing(self):
        tree = self.plant()
        beside = str(tree) + "x" + os.sep + "python.exe"
        self.assertEqual(self.sweep(running=lambda: [beside.lower(), r"c:\windows\system32\ping.exe"]), (1, 0))
        self.assertFalse(tree.exists())

    def test_the_list_holds_this_process(self):
        images = windows.running_images()
        self.assertIsInstance(images, list)
        self.assertIn(os.path.normcase(str(Path(sys.executable).resolve())), [os.path.normcase(i) for i in images])


class ServeTests(unittest.TestCase):
    def test_the_long_lived_bridge_starts_it_and_the_one_shot_form_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            home = str(Path(folder) / "home")
            with patch.object(controlcli, "sweep_soon") as soon, \
                    patch.object(controlcli, "serve", return_value=0) as served, \
                    patch.object(controlcli.sys, "stdin", io.StringIO("")):
                self.assertEqual(controlcli.main(["--home", home, "serve"]), 0)
            soon.assert_called_once()
            served.assert_called_once()
            self.assertEqual(soon.call_args.args[0].paths.home, served.call_args.args[0].paths.home)
            with patch.object(controlcli, "sweep_soon") as soon, \
                    patch.object(controlcli, "_emit", return_value=0), \
                    patch.object(controlcli, "dispatch", return_value={"ok": True}):
                controlcli.main(["--home", home, "status"])
            soon.assert_not_called()

    def test_the_window_starts_its_bridge_through_main_with_serve(self):
        """v0.6.27: through the core's bridge role, `codex-auto-resume.exe bridge serve` - controlcli.main(["serve"]) in
        car-bin (`roles::bridge`), whose serve the sweep is the watcher's beside (S5.2)."""
        source = (Path(__file__).resolve().parents[1] / "gui" / "Dashboard.cs").read_text(encoding="utf-8")
        self.assertIn("info.FileName = once.Core;", source)
        self.assertIn('info.Arguments = "bridge serve";', source)


if __name__ == "__main__":
    unittest.main()
