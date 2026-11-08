"""The courier starts whatever the interpreter makes of the environment (v0.6.22, courier/launch.py BOOTSTRAP).

An installed copy runs the bundled embeddable runtime, whose python3XX._pth makes it ignore the environment
(sys.flags.ignore_environment): v0.6.22-beta.2 handed the courier its import roots in PYTHONPATH alone, and every start
from an installation - push notices, the status feed, Telegram and the loopback API - failed on its first import, while
these tests, under a system Python that honours PYTHONPATH, saw nothing (the live acceptance's F7). So the courier's real
command line is run here the way that runtime runs it: `-I` after the interpreter, no PYTHONPATH, from another directory,
in `--check` mode against a scratch home - it imports what a round needs and exits 0, reading, writing and sending nothing.

python.exe stands in for pythonw.exe beside it, started with CREATE_NO_WINDOW, so the exit code and any traceback are
seen. build/make_release.py's check_courier_starts runs the same command under the real bundled runtime
(tests/test_courier_start_build.py).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_courier_start.py
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced.courier import __main__ as courier, launch  # noqa: E402


def console_python() -> Path:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe" and executable.with_name("python.exe").is_file():
        return executable.with_name("python.exe")
    return executable


class CheckModeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.scratch = Path(folder.name)
        self.home = self.scratch / "home"
        self.home.mkdir()

    def test_check_is_a_mode_of_its_own(self):
        self.assertEqual(courier.parse(["--home", "H", "--check"])["mode"], "check")
        self.assertIsNone(courier.parse(["--home", "H", "--check", "--feed"]))
        self.assertIsNone(courier.parse(["--check"]))

    def test_check_imports_and_exits_zero_leaving_the_home_as_it_was(self):
        def no_mutex(paths):
            raise AssertionError("--check takes no mutex")
        self.assertEqual(courier.main(["--home", str(self.home), "--check"], mutex=no_mutex), courier.EXIT_DONE)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_the_real_command_starts_with_the_environment_ignored(self):
        with patch("codex_auto_resume.startup.python_launcher", console_python):
            command = launch.argv(config.Paths(self.home), "--check")
        self.assertNotIn("-m", command, "a module run needs its package on the path before any of our code runs")
        command.insert(1, "-I")                   # as the embeddable runtime's ._pth: no PYTHONPATH, no cwd on the path
        environment = {name: value for name, value in os.environ.items() if name.upper() != "PYTHONPATH"}
        done = subprocess.run(command, cwd=str(self.scratch), env=environment, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(done.stdout, "")
        self.assertEqual(list(self.home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
