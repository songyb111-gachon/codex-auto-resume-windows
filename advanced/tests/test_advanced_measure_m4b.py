"""M4B, finished by the Stop hook's writer (v0.6.20, D-stop-hook.md): the harness reads whether this installation's Stop
hook is declared, whether Codex's hooks can be listed and whether one of them runs our launcher - booleans only, no
command or path in the record - and leaves the verdict to the person who failed a turn and watched it go on.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from test_advanced_measure_v019 import V019Case  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

LAUNCHER = "C:\\Users\\ExampleUser\\.codex-auto-resume\\app\\hook\\codex-auto-resume-hook.exe"
LISTED = {"data": [{"cwd": "C:\\work", "hooks": [{"eventName": "stop", "command": LAUNCHER, "source": "plugin"}]}]}


class M4BTests(V019Case):
    def test_declared_and_listed_it_waits_for_the_person_with_booleans_only(self):
        """Fails with the probe's start alone (M4B before v0.6.20): neither the declaration nor the listing is read."""
        record = self.run_one(Measurement.M4B, replies={"hooks/list": LISTED},
                              hands={"stop_hook": lambda: {"declared": True, "commands": [LAUNCHER]}})
        self.assertEqual(record["verdict"], "blocked")
        observed = record["observed"]
        self.assertEqual({key: observed[key] for key in ("hooks_listed", "declared", "ours_listed")},
                         {"hooks_listed": True, "declared": True, "ours_listed": True})
        text = str(record)
        self.assertNotIn("codex-auto-resume-hook.exe", text)
        self.assertNotIn("ExampleUser", text)

    def test_not_declared_it_says_to_turn_the_capability_on_first(self):
        record = self.run_one(Measurement.M4B, replies={"hooks/list": {"data": []}},
                              hands={"stop_hook": lambda: {"declared": False, "commands": [LAUNCHER]}})
        self.assertEqual((record["verdict"], record["observed"]["declared"], record["observed"]["ours_listed"]),
                         ("blocked", False, False))
        self.assertIn("turn Continue inside the turn on", record["note"])

    def test_another_hook_listed_is_not_ours(self):
        other = {"data": [{"hooks": [{"command": "C:\\tools\\other.exe"}]}]}
        record = self.run_one(Measurement.M4B, replies={"hooks/list": other},
                              hands={"stop_hook": lambda: {"declared": True, "commands": [LAUNCHER]}})
        self.assertFalse(record["observed"]["ours_listed"])

    def test_with_no_hand_nothing_is_claimed(self):
        record = self.run_one(Measurement.M4B, replies={"hooks/list": LISTED})
        self.assertEqual((record["observed"]["declared"], record["observed"]["ours_listed"]), (False, False))


if __name__ == "__main__":
    unittest.main()
