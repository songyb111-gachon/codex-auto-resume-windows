"""What an update set aside and could not delete is swept when the watcher starts (v0.6.18, OPEN-ITEMS #10).

An update moves `app`, `runtime` and the Dashboard's files aside as `<name>.old-<stamp>` and deletes them once the
copy is in place - unless something still had them open. They stayed in the home until the next install, about
14 MB each. The watcher now sweeps them as it starts (runtime/setaside.py): never in a home not provably ours,
never while an install runs or its copy journal is there (the only complete tree may be under an `.old-` name),
never through a link, and never half way through a folder still in use.

Scratch homes only; the installer's lock is handed in.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from codex_auto_resume import config
from codex_auto_resume.runtime import setaside

STAMP = "20261020123456"
ROOT = Path(__file__).resolve().parents[1]


class SweepTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.paths = config.Paths(str(self.root / "home"))
        self.assertTrue(self.paths.claim_home())
        self.home = self.paths.home
        self.lines = []

    def plant_tree(self, name):
        tree = self.home / name
        (tree / "Lib").mkdir(parents=True)
        (tree / "python.exe").write_bytes(b"MZ")
        (tree / "Lib" / "os.py").write_text("x", encoding="utf-8")
        return tree

    def sweep(self, installing=lambda: False):
        return setaside.sweep(self.paths, lambda text, *values: self.lines.append(text % values),
                              installing=installing)

    def test_set_aside_copies_are_removed_and_the_rest_is_left(self):
        old_runtime = self.plant_tree("runtime.old-" + STAMP)
        old_app = self.plant_tree("app.old-" + STAMP)
        old_exe = self.home / ("CodexAutoResumeSettings.exe.old-" + STAMP)
        old_exe.write_bytes(b"MZ")
        keep = [self.plant_tree("runtime"), self.home / "notes.old-x", self.home / ("runtime.old-" + STAMP + "x")]
        keep[1].write_text("not a stamp", encoding="utf-8")
        keep[2].write_text("not one either", encoding="utf-8")
        self.assertEqual(self.sweep(), (3, 0))
        for gone in (old_runtime, old_app, old_exe):
            self.assertFalse(gone.exists(), gone.name)
        for kept in keep:
            self.assertTrue(kept.exists(), kept.name)
        self.assertEqual(self.lines, ["set-aside copies an update left: 3 removed, 0 still in use"])

    def test_a_folder_in_use_is_left_whole(self):
        tree = self.plant_tree("runtime.old-" + STAMP)
        with open(tree / "Lib" / "os.py", "rb"):
            self.assertEqual(self.sweep(), (0, 1))
            self.assertTrue((tree / "python.exe").exists(), "nothing in it deleted under the process using it")
        self.assertEqual(self.lines, ["set-aside copies an update left: 0 removed, 1 still in use"])
        self.assertEqual(self.sweep(), (1, 0), "the next start takes it")
        self.assertFalse(tree.exists())

    def test_one_whose_deletion_stopped_half_way_is_taken_next_time(self):
        tree = self.plant_tree("runtime.old-" + STAMP + ".sweep")
        self.assertEqual(self.sweep(), (1, 0))
        self.assertFalse(tree.exists())

    def test_nothing_while_the_copy_journal_is_there(self):
        """An update cut off by a power cut: the only complete tree may be the one set aside."""
        tree = self.plant_tree("runtime.old-" + STAMP)
        (self.home / setaside.JOURNAL).write_text("{}", encoding="utf-8")
        self.assertEqual(self.sweep(), (0, 0))
        self.assertTrue(tree.exists())
        self.assertEqual(self.lines, [])

    def test_nothing_while_an_install_runs_or_that_cannot_be_told(self):
        tree = self.plant_tree("runtime.old-" + STAMP)
        for answer in (True, None):
            with self.subTest(answer):
                self.assertEqual(self.sweep(installing=lambda: answer), (0, 0))
                self.assertTrue(tree.exists())

    def test_nothing_in_a_home_that_is_not_ours(self):
        (self.home / config.OWNER_MARKER).unlink()
        tree = self.plant_tree("runtime.old-" + STAMP)
        self.assertFalse(self.paths.owns_home())
        self.assertEqual(self.sweep(), (0, 0))
        self.assertTrue(tree.exists())

    def test_a_junction_named_like_one_is_never_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("keep", encoding="utf-8")
        link = self.home / ("runtime.old-" + STAMP)
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if made.returncode != 0:
            self.skipTest("no junction could be made here")
        self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        self.assertEqual(self.sweep(), (0, 0))
        self.assertTrue((outside / "precious.txt").exists())


class WatcherStartTests(unittest.TestCase):
    def test_the_watcher_sweeps_once_it_starts_for_real(self):
        """In `_loop`, under `if not once:` - never in a single tick, which tests and `run --once` ask."""
        tree = ast.parse((ROOT / "src" / "codex_auto_resume" / "runtime" / "loop.py").read_text(encoding="utf-8"))
        loop = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_loop")
        guarded = [node for node in loop.body if isinstance(node, ast.If) and ast.unparse(node.test) == "not once"]
        calls = [ast.unparse(call.func) for node in guarded for call in ast.walk(node) if isinstance(call, ast.Call)]
        self.assertIn("sweep_set_aside", calls)


if __name__ == "__main__":
    unittest.main()
