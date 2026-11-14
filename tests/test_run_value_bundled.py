"""The sign-in Run value names the installation's bundled pythonw.exe, whoever writes it (v0.6.23 final, R1 of the second
round's reachability audit).

With a Python chosen (the advanced edition), the bridge that answers the Dashboard's Start at sign-in runs under
<home>/runtimes/<version>/python.exe. The switch used to write the Run value with the pythonw.exe beside the interpreter
running it - the chosen one, which Back or another version deletes - so the next sign-in started nothing while the switch
still read On. Setup and Repair always wrote the bundled one. Now all of them ask one function, startup.watcher_python.

Every registry writer is replaced: the Run key is a dictionary here, and the registry module itself raises if anything
reaches it. Every home is a temporary folder.

    PYTHONPATH="src;tests" python -m unittest test_run_value_bundled
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import plugin_setup  # noqa: E402
from codex_auto_resume import config, startup  # noqa: E402
from codex_auto_resume.control.watcher import WatcherMixin  # noqa: E402

VERSION = "3.15.2"


class NoRegistry:
    def __getattr__(self, name):
        raise AssertionError("the real registry was reached (%s)" % name)


class Switch(WatcherMixin):
    """The Dashboard's Start at sign-in, on a scratch home: only `paths` of the control layer is needed."""

    def __init__(self, home):
        self.paths = config.Paths(home)


class RunValueTests(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.home = Path(made.name).resolve() / "home"
        for folder in ("runtime", "runtimes/" + VERSION):
            (self.home / folder).mkdir(parents=True)
            for name in ("python.exe", "pythonw.exe"):
                (self.home / folder / name).write_bytes(b"")
        (self.home / "watcher-launcher.py").write_text("", encoding="utf-8")
        self.run_key = {}
        for name, replacement in (("_winreg", lambda: NoRegistry()),
                                  ("current_value", lambda: self.run_key.get("value")),
                                  ("install", self.write),
                                  ("uninstall", lambda: self.run_key.pop("value", None) is not None)):
            patcher = mock.patch.object(startup, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, command):
        changed = self.run_key.get("value") != command
        self.run_key["value"] = command
        return changed

    def under(self, folder):
        return mock.patch.object(startup.sys, "executable", str(self.home / folder / "python.exe"))

    def test_on_a_chosen_python_the_switch_names_the_bundled_runtime(self):
        """Fails with R1 reverted: the value names runtimes\\3.15.2\\pythonw.exe, gone after Back."""
        with self.under("runtimes/" + VERSION):
            self.assertTrue(Switch(self.home).set_startup_enabled(True), "still read as this installation's own")
        value = self.run_key["value"]
        self.assertNotIn("runtimes", value)
        self.assertTrue(value.startswith('"%s"' % (self.home / "runtime" / "pythonw.exe")), value)
        self.assertIn(str(self.home / "watcher-launcher.py"), value)

    def test_the_switch_and_setup_write_the_same_value(self):
        """One function, not two writers that disagree: on the bundled runtime or a chosen one."""
        for folder in ("runtime", "runtimes/" + VERSION):
            with self.subTest(folder), self.under(folder):
                self.run_key.clear()
                Switch(self.home).set_startup_enabled(True)
                self.assertEqual(self.run_key["value"], plugin_setup.watcher_command(self.home))
                self.assertEqual(plugin_setup.python_for_watcher(self.home), startup.watcher_python(self.home))

    def test_with_no_bundled_runtime_it_is_the_one_beside_this_interpreter(self):
        """A source run, or a home with no runtime: as before, never a console interpreter."""
        bare = self.home.parent / "bare"
        bare.mkdir()
        with self.under("runtime"):
            self.assertEqual(startup.watcher_python(bare), (self.home / "runtime" / "pythonw.exe").resolve())
            self.assertEqual(startup.watcher_python(None), (self.home / "runtime" / "pythonw.exe").resolve())
        (self.home / "runtime" / "pythonw.exe").unlink()
        with self.under("runtime"), self.assertRaises(startup.StartupError):
            startup.watcher_python(bare)

    def test_the_command_line_install_names_the_bundled_runtime_too(self):
        source = (ROOT / "src" / "codex_auto_resume" / "commands" / "install.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("launcher=startup.watcher_python(app.paths.home)"), 2, "the Run value and the button")


if __name__ == "__main__":
    unittest.main()
