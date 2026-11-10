"""The Advanced page's small open findings (v0.6.23, windows-and-tooling audit area A), the window driven as a person would.

P1: a re-read that changes the power tasks' or the saved accounts' list keeps the rows that were ticked.
E1: a pasted picture a killed window left in the temporary folder is swept when the editor opens, that prefix alone.
Send again: offered and accepted only for a capability that can send a continuation.
Open the notices card lands on the card, not at the top of the column.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests -p test_advanced_window_findings.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import Point  # noqa: E402
from codex_auto_resume_advanced import arming, registry  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, Refusal  # noqa: E402
from pagecase import PageCase, snapshot  # noqa: E402
import guiscan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWER = "power_after_tasks"
ACCOUNTS = "account_switch"
PUSH = "push_notices"
TELEGRAM = "telegram_remote"
def tasks(*threads):
    return {"ok": True, "result": {"done": True, "refusal": None, "armed": None,
                                   "running": [{"thread_id": thread, "name": thread} for thread in threads]}}


def profile(key):
    return {"id": key, "mask": key + "@example.com", "plan": "plus", "state": "ready", "in_use": False}


def saved(*keys):
    return {"ok": True, "result": {"done": True, "refusal": None, "store": "usable", "offered": True, "add_state": None,
                                   "profiles": [profile(key) for key in keys]}}


class PageTests(PageCase):
    @classmethod
    def scenario_power_ticks(cls, bridge):
        """Two ticked of three; one turn ends and the next read's list has lost it: the other stays ticked."""
        cls.watched(bridge, POWER, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-power-tasks"] = [tasks("a", "b", "c")] * 4
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": POWER},
                 {"do": "tick", "card": "power", "id": "a"}, {"do": "tick", "card": "power", "id": "c"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-power-tasks", "with": [tasks("b", "c")] * 4},
                 {"do": "read_card", "card": "power"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_account_ticks(cls, bridge):
        cls.watched(bridge, ACCOUNTS, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-accounts"] = [saved("one", "two")] * 4
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": ACCOUNTS},
                 {"do": "tick", "card": "accounts", "id": "two"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-accounts", "with": [saved("one", "two", "three")] * 4},
                 {"do": "read_card", "card": "accounts"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    def test_the_power_tasks_ticked_survive_a_changed_list(self):
        result, _ = self.of("scenario_power_ticks")
        self.assertEqual([sorted(look["ticked"]) for look in result["looks"]], [["a", "c"], ["c"]])

    def test_the_saved_accounts_ticked_survive_a_changed_list(self):
        result, _ = self.of("scenario_account_ticks")
        self.assertEqual([look["ticked"] for look in result["looks"]], [["two"], ["two"]])

if __name__ == "__main__":
    unittest.main()
