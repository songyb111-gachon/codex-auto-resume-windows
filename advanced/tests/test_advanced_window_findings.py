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

EDITORS = {"keep": (ROOT / "advanced" / "gui" / "AdvancedKeepOn.cs").read_text(encoding="utf-8"),
           "editor": (ROOT / "advanced" / "gui" / "AdvancedEditor.cs").read_text(encoding="utf-8")}
HARNESS = """
using System;
internal static class Sweep
{
    private const string PastedPrefix = "%s";
    %s
    private static int Main() { SweepPasted(); return 0; }
}
"""


class PastedSweepTests(unittest.TestCase):
    """E1: SweepPasted itself, compiled alone and run with a temporary folder of the test's own."""

    @unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
    def test_only_a_day_old_paste_is_removed(self):
        source = EDITORS["editor"]
        prefix = re.search(r'const string PastedPrefix = "([^"]+)";', source).group(1)
        body = guiscan._block(source, source.index("private static void SweepPasted("))
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            temp = work / "temp"
            temp.mkdir()
            (work / "sweep.cs").write_text(HARNESS % (prefix, body), encoding="utf-8")
            built = subprocess.run([str(CSC), "/nologo", "/out:" + str(work / "sweep.exe"), str(work / "sweep.cs")],
                                   capture_output=True, text=True, timeout=120,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(built.returncode, 0, built.stdout)
            old = time.time() - 2 * 86400
            for name, when in ((prefix + "a.png", old), (prefix + "b.png", None), ("other-paste-c.png", old)):
                (temp / name).write_bytes(b"x")
                if when:
                    os.utime(temp / name, (when, when))
            environment = dict(os.environ, TEMP=str(temp), TMP=str(temp))
            ran = subprocess.run([str(work / "sweep.exe")], env=environment, timeout=60,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(ran.returncode, 0)
            self.assertEqual(sorted(path.name for path in temp.iterdir()), sorted([prefix + "b.png", "other-paste-c.png"]))

    def test_it_runs_when_the_editor_opens(self):
        source = EDITORS["editor"]
        opening = guiscan._block(source, source.index("private void OpenEditor("))
        self.assertLess(opening.index("SweepPasted();"), opening.index("BuildEditor(row)"))


if __name__ == "__main__":
    unittest.main()
