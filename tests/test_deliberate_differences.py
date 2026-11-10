"""Rules that look written twice and are not: each pair here differs on purpose, and this keeps the next reader from
unifying them. The v0.6.23 audit listed them; each was read again on 2026-11-10 and each side is right for its use.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from codex_auto_resume import homefind, homes, machine
from codex_auto_resume.commands import base
from codex_auto_resume.control import state as control_state
from codex_auto_resume.control.actions import _reads_usage
from codex_auto_resume.engine.freshness import FreshnessMixin
from codex_auto_resume.managed import Managed
from codex_auto_resume.runtime import homes as runtime_homes
from codex_auto_resume.win import handover


class TheClickSeesTheRecordTheWatcherSeesItsGates(unittest.TestCase):
    """Retry now can only read the record; the watcher alone has the consent gate, and may still answer `held`."""

    ROW = {"interruption_id": "a", "thread_id": "t", "category": "usage_limit", "state": sorted(machine.WAITING)[0],
           "cancel_requested": 0, "submitted_at": None, "reset_at": 200.0, "not_before": None}

    class Watcher:
        _not_served = FreshnessMixin._not_served
        managed = Managed()

        class store:
            @staticmethod
            def settings():
                return {"enabled": True, "observe_only": False}

            @staticmethod
            def thread_enabled(_thread_id):
                return True

        @staticmethod
        def observing(_settings):
            return False

        @staticmethod
        def offline():
            return False

    def test_a_record_the_click_may_ask_about_can_still_be_held_by_a_gate(self):
        self.assertTrue(_reads_usage(self.ROW, 100.0))
        self.assertEqual(self.Watcher()._not_served(self.ROW, 100.0, None, {"consent": ("blocked", "x")}, 99.0), "held")

    def test_with_the_gate_passing_the_watcher_serves_it(self):
        self.assertIsNone(self.Watcher()._not_served(self.ROW, 100.0, None, {"consent": (machine.PASS, None)}, 99.0))


class ToastCancelAndCardCancelOpenTheStateDifferently(unittest.TestCase):
    """Windows starts the toast's process whatever is running, even with an older state and no watcher; a card's Cancel
    runs in a current watcher, through Control, which refuses such a state."""

    def test_the_toast_takes_an_older_state_and_the_control_layer_does_not(self):
        app = types.SimpleNamespace(paths=types.SimpleNamespace(state_dir="state"))
        with patch.object(base, "open_state") as toast:
            base._open_state(app)
        with patch.object(control_state, "open_state") as card:
            control_state.StateMixin._open(types.SimpleNamespace(paths=app.paths))
        self.assertEqual(toast.call_args.kwargs["legacy"], "always")
        self.assertEqual(card.call_args.kwargs["legacy"], "if_reducing")
        self.assertFalse(card.call_args.kwargs["reducing"])


class FolderSpellings(unittest.TestCase):
    """As written tells apart what a person wrote and looks at no file; `key` and `spelled` ask which folder it really is."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="spellings-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.real = self.root / "real"
        self.real.mkdir()
        self.link = self.root / "link"
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(self.link), str(self.real)], check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_a_junction_is_another_spelling_and_the_same_folder(self):
        self.assertNotEqual(homes.as_written(self.link), homes.as_written(self.real))
        self.assertEqual(homes.key(self.link), homes.key(self.real))
        self.assertEqual(handover.spelled(self.link / "a.exe"), handover.spelled(self.real / "a.exe"))

    def test_as_written_is_one_case_and_needs_no_folder(self):
        gone = str(self.root / "Gone" / ".." / "Elsewhere")
        with patch.object(os.path, "realpath", side_effect=AssertionError("looked at the disk")):
            self.assertEqual(homes.as_written(gone), homes.as_written(gone.upper()))

    def test_the_suggestions_and_the_watcher_share_it(self):
        self.assertFalse(hasattr(homefind, "_spelling"))
        self.assertFalse(hasattr(runtime_homes, "_spelling"))


if __name__ == "__main__":
    unittest.main()
