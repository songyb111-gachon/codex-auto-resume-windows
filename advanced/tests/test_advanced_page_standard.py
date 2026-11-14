"""The standard window holds nothing of the Dashboard's Advanced features page.

Built as a release builds each (build/make_gui.ps1), the standard executable holds none of the overlay's names or
literals, which the advanced one holds - the release audit's own check (d), with the repository's real advanced
tree; and the standard window from a tree without advanced/gui at all is the same file, byte for byte.

GUI test module: compiles real executables, so it runs on its own.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_page_standard.py
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from advancedcase import ROOT  # noqa: E402

if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

import edition_audit  # noqa: E402
from pagecase import CSC, POWERSHELL, WINDOW  # noqa: E402


class StandardWindowTests(unittest.TestCase):
    """The standard window holds nothing of the page: built as a release builds each (build/make_gui.ps1), the
    standard executable holds none of the overlay's names or literals, which the advanced one holds - the release
    audit's own check (d), with the repository's real advanced tree."""

    @classmethod
    def setUpClass(cls):
        if not (CSC.is_file() and POWERSHELL.is_file()):
            raise unittest.SkipTest("needs the in-box compiler and PowerShell")
        cls.work = Path(tempfile.mkdtemp(prefix="advanced-page-"))
        root = cls.work / "root"
        shutil.copytree(ROOT / "gui", root / "gui")
        shutil.copytree(ROOT / "advanced" / "gui", root / "advanced" / "gui")
        for name in (".codex-plugin/plugin.json", "assets/codex-auto-resume.ico", "build/make_gui.ps1",
                     "build/normalize_pe.py", "build/gui_stamp.py"):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, root / name)
        cls.runs = [subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                    "-File", str(root / "build" / "make_gui.ps1"), "-Root", str(root), *arguments],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
                    for arguments in ((), ("-Edition", "advanced"))]
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        for run in self.runs:
            if run.returncode != 0:
                self.fail("build/make_gui.ps1 failed:\n" + (run.stderr or run.stdout)[-2000:])
        self.standard = (self.root / "build" / WINDOW).read_bytes()
        self.advanced = (self.root / "build" / "advanced" / WINDOW).read_bytes()
        self.launcher = (self.root / "build" / "codex-auto-resume-mcp.exe").read_bytes()

    def test_the_standard_window_holds_no_name_and_no_literal_of_the_page(self):
        tree = edition_audit.inventory(ROOT)
        for name in ("AdvancedPageRun", "AdvancedLayoutAudit", "ArmAdvanced", "advancedList"):
            self.assertIn(name, tree.window)
        for literal in ("advanced-words", "advanced-arm", "advanced-disarm-all", "page.confirm.changed"):
            self.assertIn(literal, tree.literals)
        executables = dict(zip(edition_audit.EXECUTABLES, (self.standard, self.launcher)))
        self.assertEqual(edition_audit.check_executables(executables, tree), [])
        found = edition_audit.check_executables(dict(executables, **{edition_audit.WINDOW: self.advanced}), tree)
        self.assertIn("(d) %s holds ArmAdvanced" % edition_audit.WINDOW, found)
        self.assertIn("(d) %s holds the literal 'advanced-arm'" % edition_audit.WINDOW, found)

    def test_the_standard_window_is_the_one_its_own_sources_make(self):
        """Its build never reads the overlay: the standard window from a tree without advanced/gui at all is the same
        file, byte for byte."""
        bare = self.work / "bare"
        shutil.copytree(self.root, bare, ignore=shutil.ignore_patterns("build"))
        shutil.rmtree(bare / "advanced")
        (bare / "build").mkdir()
        for name in ("make_gui.ps1", "normalize_pe.py", "gui_stamp.py"):
            shutil.copyfile(self.root / "build" / name, bare / "build" / name)
        run = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(bare / "build" / "make_gui.ps1"), "-Root", str(bare)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        self.assertEqual(run.returncode, 0, (run.stderr or run.stdout)[-2000:])
        self.assertEqual((bare / "build" / WINDOW).read_bytes(), self.standard)
        self.assertNotEqual(self.advanced, self.standard)


if __name__ == "__main__":
    unittest.main()
