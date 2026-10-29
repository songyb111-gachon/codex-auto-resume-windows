"""The weekly update check says what it did in the watcher's log (v0.6.18 acceptance, 2026-10-21).

One English line per check, in logs\\auto-resume.log as the watcher's other lines are written: checked and nothing newer,
a newer version offered (which), or could not check and why - in the words the Dashboard's Check for updates uses for
the same answer. Versions only: no path, no name, nothing the check printed. Only the advanced journal said it before.
No check reaches the network or runs PowerShell: every one is a fake.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_idle_update_check as base  # noqa: E402
from codex_auto_resume import logbook  # noqa: E402
from codex_auto_resume_advanced.engine import updatecheck  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ENGLISH = json.loads((ROOT / "src" / "codex_auto_resume" / "locales" / "en.json").read_text(encoding="utf-8"))
DASHBOARD = (ROOT / "gui" / "DashboardMaintenance.cs").read_text(encoding="utf-8")


class LogCase(base.CheckCase):
    def setUp(self):
        super().setUp()
        self.lines = []
        self.code._log = self.lines.append

    def check(self, answer):
        """One check with `answer` as the fake run's, then the tick that settles it."""
        self.answer = answer
        self.look(updatecheck.WEEK)
        self.look()


class OutcomeTests(LogCase):
    def test_checked_and_nothing_newer_is_one_line(self):
        self.on()
        self.check(base.CURRENT)
        self.assertEqual(self.lines, ["weekly update check: checked, nothing newer: v0.6.18 is the newest published "
                                      "release"])
        self.lines.clear()
        self.check((11, "update: newer-local 0.6.20 0.6.19\n"))
        self.assertEqual(self.lines, ["weekly update check: checked, nothing newer: this build is ahead of the newest "
                                      "published release, v0.6.19"])

    def test_a_newer_version_offered_names_it(self):
        self.on()
        self.check(base.AVAILABLE)
        self.assertEqual(self.lines, ["weekly update check: v0.6.19 offered"])
        self.lines.clear()
        self.check(base.PRERELEASE)
        self.assertEqual(self.lines, ["weekly update check: pre-release v0.6.19-beta.2 offered"])

    def test_could_not_check_says_why_in_the_dashboards_words(self):
        self.on()
        self.check((12, "update: unavailable\n"))
        self.assertEqual(self.lines, ["weekly update check: could not check: " + ENGLISH["diag.update_could_not_ask"]])
        self.lines.clear()
        self.check((10, "update: current 0.6.18\n"))          # the code and the line disagree: no answer
        self.assertEqual(self.lines, ["weekly update check: could not check: " + ENGLISH["diag.update_failed"]])
        self.lines.clear()
        self.check(None)
        self.assertEqual(self.lines, ["weekly update check: could not check: " + ENGLISH["diag.update_failed"]])

    def test_one_line_per_check_and_none_without_one(self):
        self.on()
        self.check(base.CURRENT)
        for _ in range(3):
            self.look()
        self.assertEqual(len(self.lines), 1)
        self.assertEqual(len(self.checks), 1)

    def test_the_line_reaches_the_watchers_log_file(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        log_file = Path(folder.name) / "logs" / "auto-resume.log"
        logger = logging.getLogger(logbook.LOGGER_NAME)
        kept = (list(logger.handlers), logger.level, logger.propagate)

        def restore():
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            for handler in kept[0]:
                logger.addHandler(handler)
            logger.setLevel(kept[1])
            logger.propagate = kept[2]
        self.addCleanup(restore)
        logbook.setup_logging(log_file)
        self.code._log = updatecheck._log_line
        self.on()
        self.check(base.AVAILABLE)
        for handler in logger.handlers:
            handler.flush()
        written = log_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(written), 1, written)
        self.assertRegex(written[0], r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] weekly update check: v0\.6\.19 offered$")


class WhyTests(unittest.TestCase):
    """run_check says why it did not answer, and the line says it as the Dashboard does."""

    class Process:
        slow = False

        def __init__(self, argv, **options):
            self.argv = argv
            self.returncode = 0

        def communicate(self, timeout=None):
            if WhyTests.Process.slow and timeout is not None:
                raise subprocess.TimeoutExpired(self.argv, timeout)
            return b"update: current 0.6.18\n", b""

    def setUp(self):
        WhyTests.Process.slow = False
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.script = Path(folder.name) / "app" / "scripts" / "bootstrap.ps1"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("# not run\n", encoding="utf-8")
        for patched in (patch.object(subprocess, "Popen", self.Process),
                        patch("codex_auto_resume.pwsh.executable", lambda: r"C:\Windows\System32\psh.exe")):
            patched.start()
            self.addCleanup(patched.stop)

    def test_each_reason_on_the_list(self):
        why = []
        self.assertEqual(updatecheck.run_check(self.script, Path("C:/home"), said=why), (0, "update: current 0.6.18\n"))
        self.assertEqual(why, [])
        WhyTests.Process.slow = True
        self.assertIsNone(updatecheck.run_check(self.script, Path("C:/home"), seconds=1, said=why))
        self.assertEqual(why, [updatecheck.RUNNING])
        why = []
        self.assertIsNone(updatecheck.run_check(self.script.with_name("missing.ps1"), Path("C:/home"), said=why))
        self.assertEqual(why, [updatecheck.MISSING])
        why = []
        with patch("codex_auto_resume.pwsh.executable", lambda: None):
            self.assertIsNone(updatecheck.run_check(self.script, Path("C:/home"), said=why))
        self.assertEqual(why, [updatecheck.NOT_STARTED])

    def test_each_reason_in_the_dashboards_words(self):
        prefix = "weekly update check: could not check: "
        self.assertEqual(updatecheck.said(None, updatecheck.MISSING), prefix + ENGLISH["diag.update_incomplete"])
        running = ENGLISH["diag.update_running"]
        self.assertEqual(updatecheck.said(None, updatecheck.RUNNING), prefix + running.split(";")[0] + ".")
        self.assertTrue(running.startswith("It is taking longer than usual"))
        self.assertEqual(updatecheck.said(None, updatecheck.NOT_STARTED), prefix + ENGLISH["diag.update_failed"])
        for key, (catalog_key, english) in updatecheck.COULD_NOT.items():
            with self.subTest(key):
                self.assertEqual(ENGLISH[catalog_key], english, "the fallback is the catalog's English")
                self.assertIn('S("%s", "%s"' % (catalog_key, english), DASHBOARD, "the Dashboard's own words")

    def test_the_real_run_is_asked_why(self):
        asked = []

        def fake(script, home, seconds=updatecheck.CHECK_SECONDS, said=None):
            asked.append(said)
            said.append(updatecheck.RUNNING)
            return None
        with patch.object(updatecheck, "run_check", fake):
            code = updatecheck.IdleUpdateCheck(type("P", (), {"home": Path("C:/home")})())
            code._check()
        self.assertEqual(code._line, "weekly update check: could not check: "
                         + ENGLISH["diag.update_running"].split(";")[0] + ".")
        self.assertEqual(len(asked), 1)

    def test_the_line_names_no_path_and_nothing_printed(self):
        printed = "C:\\Users\\ExampleUser\\x\nupdate: current 0.6.18; Remove-Item x\n"
        line = updatecheck.said((0, printed))
        self.assertNotIn("ExampleUser", line)
        self.assertNotIn("Remove-Item", line)
        self.assertEqual(line, "weekly update check: checked, nothing newer: v? is the newest published release")
        line = updatecheck.said((10, "update: available 0.6.18 C:\\Users\\ExampleUser\n"))
        self.assertEqual(line, "weekly update check: could not check: " + ENGLISH["diag.update_failed"])


if __name__ == "__main__":
    unittest.main()
