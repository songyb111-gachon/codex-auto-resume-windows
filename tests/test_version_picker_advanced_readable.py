"""Install another version... and advanced state version 8 (v0.6.19), which stays marked readable from 7: the picker
says every advanced feature is off in a version picked only where that version cannot use the file - one older than
the readable-from mark ($AdvancedMarkSince, v0.6.17), or on a form older than the one the file is marked readable from
($AdvancedReadableFrom, the advanced state's schema.READABLE_FROM). v0.6.17 and v0.6.18 read a version-8 file as it is
(advanced/tests/test_advanced_schema_v8.py runs their own code on one); v0.6.16 refuses it.

The bootstrap's functions are lifted and run as tests/test_version_picker.py runs them (LIFT), with nothing but these
rows; nothing is fetched and nothing installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_version_picker import BOOTSTRAP, LIFT, POWERSHELL, RELEASE, row  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INSTALLED = "0.6.19-alpha"
CASES = [
    # The readers of the mark, on form 7: the file is theirs to use as it is.
    row("0.6.18", "offered older,release,kept,latest", edition="advanced", installed=INSTALLED,
        installed_edition="advanced", latest="0.6.18"),
    row("0.6.17", "offered older,release,kept", edition="advanced", installed=INSTALLED, installed_edition="advanced",
        latest="0.6.18"),
    # On form 7 too, but before the mark: every advanced feature off there.
    row("0.6.16", "offered older,release,kept,advanced-off", edition="advanced", installed=INSTALLED,
        installed_edition="advanced", latest="0.6.18"),
    row("0.6.16-beta.4", "offered older,prerelease,kept,advanced-off", edition="advanced", installed=INSTALLED,
        installed_edition="advanced", latest="0.6.18", older=True),
    # The standard edition has no advanced settings to lose.
    row("0.6.16", "offered older,release,kept,edition", installed=INSTALLED, installed_edition="advanced",
        latest="0.6.18"),
]


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ReadableFromTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.folder = folder
        work = Path(folder.name)
        (work / "release.json").write_text(json.dumps(RELEASE), encoding="utf-8")
        cases = {"chosen": [], "pages": [], "policy": [], "verdicts": [case for case, _ in CASES], "tables": []}
        (work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        cls.done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", LIFT],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                                  env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_CASES=str(work / "cases.json"),
                                           CAR_RELEASE=str(work / "release.json"), CAR_WORK=str(work)),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        cls.answer = json.loads(cls.done.stdout) if cls.done.returncode == 0 and cls.done.stdout.strip() else None

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.answer is None:
            self.fail("the probe did not run: " + (self.done.stderr or self.done.stdout)[-3000:])

    def test_a_version_that_reads_the_mark_keeps_its_advanced_features(self):
        """Fails with the readable-from rule reverted: v0.6.17 and v0.6.18 are said to have every advanced feature
        off, which their own code disproves."""
        for (case, expected), answer in zip(CASES, self.answer["verdicts"]):
            with self.subTest(version=case["entry"]["version"], edition=case["edition"]):
                self.assertEqual(answer, expected)

    def test_the_constants_are_the_advanced_states(self):
        c = self.answer["constants"]
        text =(ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "state" / "schema.py").read_text(
            encoding="utf-8")
        readable = int(re.search(r"^READABLE_FROM = (\d+)$", text, re.M).group(1))
        self.assertEqual(c["AdvancedReadableFrom"], readable)
        self.assertEqual(c["AdvancedMarkSince"], "0.6.17", "the first release whose reader honours the mark")
        self.assertEqual(c["AdvancedStateSince"][0], ["0.6.19-alpha", 8])


if __name__ == "__main__":
    unittest.main()
