"""Crash restart over a watcher under a chosen Python (v0.6.23 final, X1 of the owner's logs of 2026-11-13).

The launcher (scripts/watcher_launcher.py) runs a watcher under the Python the person chose as a supervised child. Before
this, it asked P13 only which Python to use and never the start question, and crash restart answers an end only in a
launcher it answered SUPERVISE in - so a crash there was left down, with no row and no line. Here the launcher's own code
drives the edition's own crash restart: a child that exits 1 is started again under the chosen Python, each restart a
`restarts` row, and the cap of three an hour holds. Every process is a fake; the stop event and the notice are the fakes
test_advanced_supervise uses; nothing real is started, waited on or shown.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_chosen_restart.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_supervise import SuperviseCase  # noqa: E402
from codex_auto_resume import chosen_runtime  # noqa: E402
from codex_auto_resume_advanced.engine import supervise  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VERSION = "3.15.2"


def launcher_module():
    spec = importlib.util.spec_from_file_location("watcher_launcher_chosen_restart", ROOT / "scripts" / "watcher_launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChosenRestartTests(SuperviseCase):
    def setUp(self):
        super().setUp()
        where = self.home / "runtimes" / VERSION
        where.mkdir(parents=True)
        for name in chosen_runtime.required(VERSION):
            (where / name).write_bytes(b"chosen")
        (self.home / "runtimes" / "chosen.json").write_text(json.dumps({"version": VERSION, "at": 1}), encoding="utf-8")
        self.launcher = launcher_module()
        self.started = []
        for name in ("_note", "_complain"):
            patcher = patch.object(self.launcher, name, lambda *_a: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = patch("codex_auto_resume.runtime.app.App")
        app.start().return_value.watcher_running.return_value = False
        self.addCleanup(app.stop)

    def supervise(self, _home, facts):
        """P13 as the launcher asks it: which Python is python_choice's (not under test here), the rest the edition's own."""
        if facts["phase"] == self.launcher.PHASE_RUNTIME:
            return self.launcher.SUPERVISE
        if facts["phase"] == self.launcher.PHASE_ENDED:
            facts = dict(facts, clean=False)          # the heartbeat says it still ran: a crash
        return self.plug.supervise(facts)

    def child(self, *_a, **_k):
        if len(self.started) > 2 * supervise.CAP:
            raise AssertionError("started past the cap: %d children" % len(self.started))
        self.now += 60                                # each child runs a minute; a row's time is its key
        process = MagicMock()
        process.pid = 4242 + len(self.started)
        process.wait.return_value = 1
        self.started.append(_a[0][0])
        return process

    def run_launcher(self):
        with patch.object(self.launcher, "_supervise", self.supervise), patch("subprocess.Popen", side_effect=self.child), \
                patch.object(self.launcher, "_why_held", lambda _home: self.plug.supervise_held()), \
                patch.object(self.launcher, "_came_up", return_value=True):
            return self.launcher._on_chosen(self.home, self.home)

    def test_a_crash_under_the_chosen_python_is_restarted_and_counted_against_the_cap(self):
        """Fails with the start question reverted in `_on_chosen`: one child, no row, the watcher left down."""
        self.on()
        self.assertEqual(self.run_launcher(), 1)
        chosen = str(self.home / "runtimes" / VERSION / "pythonw.exe")
        self.assertEqual(self.started, [chosen] * (1 + supervise.CAP), "started again under the chosen Python, up to the cap")
        self.assertEqual([row["restarted"] for row in self.rows()], [1] * supervise.CAP + [0])
        self.assertEqual(self.notices, [self.paths], "the one notice that it was left stopped")
        self.assertTrue(self.stop.held, "the stop event held from the start, as for the bundled runtime")

    def test_off_the_chosen_watcher_ends_once_and_nothing_is_written(self):
        self.assertEqual(self.run_launcher(), 1)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
