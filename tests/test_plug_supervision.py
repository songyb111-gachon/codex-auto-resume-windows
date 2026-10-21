"""P13 in the launcher (v0.6.19, plans/v0619-design/D-groundwork.md section 3): asked before the watcher runs -
`{"phase": "start"}`, where SUPERVISE would mean run it as a child and stay - and once it ended - `{"phase": "ended",
"exit_code": n, "clean": ...}`, where RESTART would mean start it once more. Both words are the point's now, and
the launcher carries neither out yet (the supervisor's own commit does): with the standard edition's NULL plug, and
with any answer at all, it runs the watcher once and returns what it returned, exactly as before.

    PYTHONPATH="src;tests" python -m unittest test_plug_supervision
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import config, edition  # noqa: E402
from codex_auto_resume.domain import plug  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, NULL, Alternative, Point, consult  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_plug_points import Asked  # noqa: E402

CODES = (0, 1, 3, 4, 5)


class LauncherCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        copy = self.home / "watcher-launcher.py"
        shutil.copyfile(ROOT / "scripts" / "watcher_launcher.py", copy)
        (self.home / "runtime.json").write_text(json.dumps({"home": str(self.home)}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("watcher_launcher_p13", copy)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(self.launcher.RELAUNCH_MARK, None)

    def launch(self, argv, code, found):
        """The launcher's main with `found` as the installed edition's plug and a watcher that returns `code`: what
        it returned, and every call it made of the watcher and of its own relaunch."""
        with patch.object(self.launcher, "resolve_plugin_root", return_value=ROOT), \
                patch("codex_auto_resume.cli.main", return_value=code) as watcher, \
                patch.object(self.launcher, "_relaunch_once") as relaunch, \
                patch.object(edition, "plug", return_value=found):
            returned = self.launcher.main(argv)
        return returned, [call.args for call in watcher.call_args_list], [call.args for call in relaunch.call_args_list]


class NullTests(LauncherCase):
    def test_with_null_the_launcher_does_exactly_what_it_did(self):
        """Run, every exit code, and another command: one run of the watcher with the same arguments, the relaunch
        only for a newer state, its code returned - and no heartbeat read for NULL."""
        for argv, command in (([], ["run"]), (["activate", "codex-auto-resume:open"], ["activate",
                                                                                         "codex-auto-resume:open"])):
            for code in CODES:
                with self.subTest(argv=argv, code=code), \
                        patch.object(self.launcher, "_ended_cleanly") as read:
                    returned, runs, relaunches = self.launch(argv, code, NULL)
                    self.assertEqual(returned, code)
                    self.assertEqual(runs, [(["--home", str(self.home), "--quiet"] + command,)])
                    self.assertEqual(len(relaunches), int(code == self.launcher.EXIT_SCHEMA_NEWER and not argv))
                    read.assert_not_called()

    def test_null_answers_defer_to_both_questions(self):
        for facts in ({"phase": "start"}, {"phase": "ended", "exit_code": 1, "clean": False}):
            with self.subTest(facts=facts):
                self.assertIs(consult(NULL, Point.SUPERVISION, facts), DEFER)
                self.assertIs(plug.guard(NULL).supervise(facts), DEFER)


class AskedTests(LauncherCase):
    def test_a_run_is_asked_at_its_start_and_once_it_ended(self):
        """Fails with the start question reverted: the plug is asked only once, after the run."""
        for code in (0, 1, 3, 5):
            with self.subTest(code=code):
                asked = Asked()
                returned, runs, _ = self.launch([], code, asked)
                self.assertEqual(returned, code)
                self.assertEqual(asked.asked, [("supervise", ({"phase": "start"},)),
                                               ("supervise", ({"phase": "ended", "exit_code": code, "clean": None},))])

    def test_the_relaunch_for_a_newer_state_is_asked_only_at_the_start(self):
        asked = Asked()
        self.launch([], self.launcher.EXIT_SCHEMA_NEWER, asked)
        self.assertEqual(asked.asked, [("supervise", ({"phase": "start"},))])

    def test_another_command_asks_nothing(self):
        asked = Asked()
        self.launch(["activate", "codex-auto-resume:open"], 0, asked)
        self.assertEqual(asked.asked, [])

    def test_supervise_and_restart_are_the_points_words_and_change_nothing_yet(self):
        """Taken by the guard as the point's own (not DEFER), and carried out by no one: the watcher runs once, its
        code is returned and nothing is relaunched, whatever the plug says."""
        self.assertEqual(plug.ALTERNATIVES[Point.SUPERVISION], frozenset({Alternative.SUPERVISE, Alternative.RESTART}))
        for answer in (Alternative.SUPERVISE, Alternative.RESTART, "restart", Alternative.HOLD, RuntimeError("no")):
            with self.subTest(answer=answer):
                asked = Asked(supervise=answer)
                expected = (Alternative(answer) if answer in (Alternative.SUPERVISE, Alternative.RESTART, "restart")
                            else DEFER)
                self.assertIs(plug.guard(asked).supervise({"phase": "start"}), expected)
                returned, runs, relaunches = self.launch([], 1, Asked(supervise=answer))
                self.assertEqual((returned, len(runs), relaunches), (1, 1, []))

    def test_the_plugs_answer_never_reaches_the_watchers_arguments(self):
        returned, runs, _ = self.launch([], 0, Asked(supervise=Alternative.SUPERVISE))
        self.assertEqual(runs, [(["--home", str(self.home), "--quiet", "run"],)])


class CleanTests(LauncherCase):
    """`clean`: whether the heartbeat the watcher left says it stopped on purpose."""

    def beat(self, end=None):
        paths = config.Paths(self.home)
        store = Store(paths.state_dir, migrate=True)
        try:
            store.heartbeat(1.8e9, pid=7, session_id="s", started_at=1.8e9, ok=True, engine_state="running",
                            code_version="0.6.18")
            if end is not None:
                store.watcher_ended(1.8e9 + 1, end)
        finally:
            store.close()

    def ended(self):
        asked = Asked()
        self.launch([], 0, asked)
        return asked.asked[-1][1][0]["clean"]

    def test_a_watcher_that_stopped_on_purpose_ended_cleanly(self):
        for end in ("clean", "memory_guard"):
            with self.subTest(end=end):
                self.beat(end)
                self.assertIs(self.ended(), True)

    def test_a_heartbeat_still_running_did_not(self):
        self.beat()
        self.assertIs(self.ended(), False)

    def test_no_state_or_one_that_cannot_be_read_is_not_known(self):
        self.assertIsNone(self.ended())
        self.assertFalse((config.Paths(self.home).state_dir / "state.sqlite").exists(), "nothing was made to read it")
        with patch.object(Store, "watcher_status", side_effect=RuntimeError("damaged")):
            self.beat()
            self.assertIsNone(self.ended())


if __name__ == "__main__":
    unittest.main()
