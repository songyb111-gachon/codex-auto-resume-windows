"""v0.6.23: Start and setup wait for a start under a chosen Python as the launcher counts it (second-round limits audit R3).

Where a choice of Python is recorded, the launcher asks the edition's plug which Python to run the watcher under before it
starts the child that takes the mutex (41 and 48 s on the owner's PC on 2026-11-11), and gives that child 45 s from the
child's own start. Start (control.Control.start_watcher) and setup (plugin_setup.start_watcher) waited 45 s from the launch,
so a healthy start there could be reported as not confirmed. Now the question's time and the interpreters' starts come on top
of the wait where, and only where, a record exists. Nothing sleeps for the real bounds: they are shortened, and no real home,
registry or watcher is touched - every home is a temporary folder and every process a stand-in.

    PYTHONPATH="src;tests" python -m unittest test_chosen_start_wait
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import plugin_setup                          # noqa: E402
from codex_auto_resume import chosen_runtime, config, control  # noqa: E402
from codex_auto_resume.control import watcher  # noqa: E402

BASE = 0.2        # stands for the 45 s
ASK = 0.6         # stands for the launcher's question before its child
STARTS = 0.1      # stands for the interpreters' starts
APPEARS = 0.5     # after the base wait, well inside the base, the question and the starts together


def record(home: Path) -> None:
    where = chosen_runtime.root(home)
    where.mkdir(parents=True, exist_ok=True)
    (where / chosen_runtime.RECORD).write_text('{"version": "3.15.2", "at": 1}', encoding="utf-8")


class Process:
    """The Popen handle of a launcher that stays alive (it is still asking, then supervising)."""

    def poll(self):
        return None


def appearing(after):
    born = time.monotonic()
    looks = []

    def probe(*_args):
        if not looks:                     # the look before the launch
            looks.append(False)
            return False
        looks.append(True)
        return time.monotonic() - born >= after
    return probe


class Shortened(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.home = Path(made.name) / "home"
        self.home.mkdir()
        for name, value in (("WATCHER_START_TIMEOUT", BASE), ("CHOSEN_ASK_SECONDS", ASK),
                            ("INTERPRETER_STARTS_SECONDS", STARTS), ("WATCHER_START_INTERVAL", 0.01)):
            patcher = mock.patch.object(watcher, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Every registry call the startup layer could make goes to a key-tree fake (test_control's ControlTestCase does
        # the same): nothing here reads or writes the real Run key.
        from test_cli import FakeWinreg
        from codex_auto_resume import startup
        registry = mock.patch.object(startup, "_winreg", return_value=FakeWinreg())
        registry.start()
        self.addCleanup(registry.stop)


class TheBound(Shortened):
    def test_with_no_record_the_wait_is_as_it_was(self):
        self.assertEqual(control.start_timeout(self.home), BASE)
        self.assertEqual(control.start_timeout(self.home, 3.0), 3.0)

    def test_with_a_record_the_question_and_the_starts_come_on_top(self):
        record(self.home)
        self.assertAlmostEqual(control.start_timeout(self.home), BASE + ASK + STARTS)
        self.assertAlmostEqual(control.start_timeout(self.home, 3.0), 3.0 + ASK + STARTS)


class Numbers(unittest.TestCase):
    def test_the_numbers_and_their_reasons(self):
        self.assertEqual(watcher.WATCHER_START_TIMEOUT, 45.0)
        self.assertGreaterEqual(watcher.CHOSEN_ASK_SECONDS, 48.0, "the longest question seen, 2026-11-11")
        self.assertEqual(control.CHOSEN_START_TIMEOUT, 45.0 + 48.0 + 15.0)
        source = (ROOT / "src" / "codex_auto_resume" / "control" / "watcher.py").read_text(encoding="utf-8")
        for said in ("41 and\n# 48 s", "2.7 to 5.9 s", "45 + 48 + 15 = 108 s"):
            self.assertIn(said, source)

    def test_the_window_s_one_shot_call_outlasts_the_longest_wait(self):
        """The Start button's call ends at LongCallMilliseconds: the longer wait, with an interpreter's start, fits."""
        settings = (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8")
        long_call = int(re.search(r"\bLongCallMilliseconds = (\d+);", settings).group(1))
        self.assertGreater(long_call, control.CHOSEN_START_TIMEOUT * 1000 + 30000)


class StartAndSetup(Shortened):
    def setup_start(self):
        probe = appearing(APPEARS)

        class App:
            def __init__(self, *arguments, **keywords):
                pass

            def watcher_running(self):
                return probe()

        with mock.patch.object(plugin_setup, "App", App), \
                mock.patch.object(plugin_setup, "python_for_watcher", return_value=self.home / "pythonw.exe"), \
                mock.patch.object(plugin_setup.subprocess, "Popen", return_value=Process()), \
                mock.patch.object(plugin_setup, "WATCHER_WAIT", BASE):
            return plugin_setup.start_watcher(self.home)

    def dashboard_start(self):
        (self.home / "watcher-launcher.py").write_text("# launcher\n", encoding="utf-8")
        paths = config.Paths(self.home)
        paths.ensure()
        layer = control.Control(paths)
        with mock.patch.object(control.Control, "watcher_running", side_effect=appearing(APPEARS)), \
                mock.patch.object(watcher.windows, "install_in_progress", return_value=False), \
                mock.patch.object(watcher.startup, "python_launcher", return_value=self.home / "pythonw.exe"), \
                mock.patch("subprocess.Popen", return_value=Process()):
            return layer.start_watcher()["state"]

    def test_setup_confirms_a_start_under_a_chosen_python_that_comes_up_after_the_question(self):
        """Fails with the old timing: unconfirmed after the 45 s, though the watcher came up within the launcher's budget."""
        record(self.home)
        self.assertEqual(self.setup_start(), "running")

    def test_setup_with_no_record_still_ends_at_its_own_wait(self):
        self.assertEqual(self.setup_start(), "unconfirmed")

    def test_start_confirms_a_start_under_a_chosen_python_that_comes_up_after_the_question(self):
        """Fails with the old timing: the Dashboard's Start said unconfirmed at the 45 s."""
        record(self.home)
        self.assertEqual(self.dashboard_start(), "running")

    def test_start_with_no_record_still_ends_at_its_own_wait(self):
        self.assertEqual(self.dashboard_start(), "unconfirmed")


def launcher_module():
    spec = importlib.util.spec_from_file_location("watcher_launcher_start_wait", ROOT / "scripts" / "watcher_launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheLauncherStartedAgain(Shortened):
    def test_a_launcher_started_again_under_the_bundled_runtime_is_waited_for_with_its_question(self):
        """Fails with the old timing: the first launcher ended at 45 s while the second still asked, and Start read
        that end as a failed start."""
        launcher = launcher_module()
        record(self.home)
        with mock.patch("codex_auto_resume.control.watcher.await_watcher", return_value={"state": "running"}) as waited, \
                mock.patch("codex_auto_resume.runtime.app.App"):
            self.assertTrue(launcher._came_up(self.home, Process(), asks_first=True))
            self.assertAlmostEqual(waited.call_args[1]["timeout"], launcher.WATCHER_WAIT + ASK + STARTS)
            self.assertTrue(launcher._came_up(self.home, Process()))
            self.assertEqual(waited.call_args[1]["timeout"], launcher.WATCHER_WAIT, "a chosen child keeps its own 45 s")

    def test_the_relaunch_asks_for_the_longer_wait(self):
        source = (ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8")
        body = source[source.index("def _again_under_bundled"):source.index("def _came_up")]
        self.assertIn("_came_up(home, process, asks_first=True)", body)


if __name__ == "__main__":
    unittest.main()
