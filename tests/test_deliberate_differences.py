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


if __name__ == "__main__":
    unittest.main()
