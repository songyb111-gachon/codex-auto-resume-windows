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
# Those at no point that pays for a send of a record: each states so here, so a new capability is decided on purpose.
NO_CONTINUATION = {
    "account_switch", "codex_retry_settings", "crash_restart", "empty_response", "every_conversation", "fleet_view",
    "idle_update_check", "keep_going", "local_api", "open_to_send", "parallel_dispatch", "power_after_tasks", "push_notices",
    "reset_message", "start_with_codex", "status_feed", "steer_send", "stop_hook_continuation", "telegram_remote",
    "usage_analytics", "usage_meter", "usage_pause", "usage_wrap_up", "wake_for_reset", "window_anchor",
    # An action, and the one that is itself a resend.
    "python_choice", "compat_report", "local_api_actions", "local_api_lan", "long_reset_message", "open_codex_button", "telegram_continue",
    "once_more_when_unsure"}


def tasks(*threads):
    return {"ok": True, "result": {"done": True, "refusal": None, "armed": None,
                                   "running": [{"thread_id": thread, "name": thread} for thread in threads]}}


def profile(key):
    return {"id": key, "mask": key + "@example.com", "plan": "plus", "state": "ready", "in_use": False}


def saved(*keys):
    return {"ok": True, "result": {"done": True, "refusal": None, "store": "usable", "offered": True, "add_state": None,
                                   "profiles": [profile(key) for key in keys]}}


def telegram():
    return {"ok": True, "result": {"done": True, "refusal": None, "paired": False, "token_saved": False, "pairing": False,
                                   "state": "no_token", "continue": False}}


def courier():
    rows = [{"channel": channel, "on": False, "saved": False, "refused_today": 0, "tripped": False}
            for channel in ("ntfy", "webhook", "telegram", "email")]
    return {"ok": True, "result": {"done": True, "refusal": None, "channels": rows, "events": 15,
                                   "event_order": ["recovered", "failed"],
                                   "telegram": {"token_saved": False, "paired": False, "pairing": False}, "feed": None}}


class PageTests(PageCase):
    @classmethod
    def scenario_notices(cls, bridge):
        """No bot token: Open the notices card, and where the column stands once that card is read."""
        cls.watched(bridge, PUSH, state="armed")
        cls.watched(bridge, TELEGRAM, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-remote-pair-state"] = [telegram()] * 8
        script["advanced-courier"] = [courier()] * 8
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": TELEGRAM}, {"do": "look"},
                 {"do": "remote", "button": "open notices"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

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

    def test_open_the_notices_card_lands_on_the_card(self):
        result, _ = self.of("scenario_notices")
        before, opened = result["looks"]
        self.assertEqual((before["open"], before["scrolled"]), (TELEGRAM, 0))
        self.assertEqual(opened["open"], PUSH)
        self.assertGreater(opened["courier_top"], 0, "the courier's card is under the capability's own")
        self.assertGreater(opened["scrolled"], 0, "it stayed at the top of the column")
        self.assertLessEqual(opened["scrolled"], opened["courier_top"])


class SendAgainOfferedTests(ac.AdvancedCase):
    """Also send again when unsure... is a button that can do something, or it is not there."""

    def test_every_capability_states_it_correctly(self):
        # Every one the module defines, those a measurement has not offered yet (registry.offered) too.
        every = [value for value in vars(registry).values() if isinstance(value, registry.CapabilityDef)]
        self.assertEqual({definition.id for definition in every if not arming.offers_send_again(definition)},
                         NO_CONTINUATION)

    def keep(self, runtime, capability, send_again):
        return runtime.arming.set_keep_on(capability, True, send_again=send_again, generation=runtime.state.meta()["generation"],
                                          confirmed=["keep_on", "send_again"] if send_again else ["keep_on"],
                                          actor=Actor.DASHBOARD)

    def quiet_runtime(self):
        quiet = ac.definition(id="test_look", points=frozenset({Point.TICK}), journal_prefix="tl")
        where = tempfile.TemporaryDirectory()
        self.addCleanup(where.cleanup)
        self.catalogs = ac.catalogs(where.name, ac.definition(), quiet)
        return self.runtime(ac.definition(), quiet)

    def test_set_keep_on_refuses_it_for_one_that_sends_no_continuation(self):
        runtime = self.quiet_runtime()
        self.assertTrue(self.arm(runtime, capability="test_look", state="armed")["done"])
        self.assertTrue(self.keep(runtime, "test_look", False)["done"])
        self.assertEqual(self.keep(runtime, "test_look", True)["refusal"], Refusal.INVALID_REQUEST)
        self.assertFalse(runtime.state.arming()["test_look"]["send_again"])

    def test_the_listing_says_which(self):
        runtime = self.quiet_runtime()
        said = {item["id"]: item["send_again_offered"] for item in runtime.arming.listing()["capabilities"]}
        self.assertEqual(said, {"test_wake": True, "test_look": False})

    def test_a_row_already_holding_it_keeps_working(self):
        runtime = self.quiet_runtime()
        self.assertTrue(self.arm(runtime, capability="test_look", state="armed")["done"])
        self.assertTrue(self.keep(runtime, "test_look", False)["done"])
        runtime.state.set_keep_on("test_look", True, send_again=True, actor=Actor.DASHBOARD,
                                  generation=runtime.state.meta()["generation"], at=ac.NOW)
        self.assertTrue(self.keep(runtime, "test_look", True)["done"], "the row as it is, confirmed again")
        self.assertTrue(runtime.state.arming()["test_look"]["send_again"])
        let_go = runtime.arming.set_keep_on("test_look", False, send_again=False, generation=None, actor=Actor.DASHBOARD)
        self.assertTrue(let_go["done"])
        self.assertFalse(runtime.state.arming()["test_look"]["send_again"])

    def test_the_window_asks_the_listing(self):
        body = guiscan._block(EDITORS["keep"], EDITORS["keep"].index("private void BuildKeepOn("))
        self.assertIn('kept && !again && Equals(Get(item, "send_again_offered"), true)', body)


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
                                   capture_output=True, encoding="locale", errors="replace", timeout=120,
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


class KoreanRegisterTests(unittest.TestCase):
    def test_the_two_accounts_help_lines_speak_to_the_person_alike(self):
        words = json.loads((ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales" / "ko.json")
                           .read_text(encoding="utf-8"))
        self.assertTrue(words["page.accounts.help"].startswith("\ub2f9\uc2e0\uc758 "))
        self.assertTrue(words["page.accounts.help_switch"].startswith("\ub2f9\uc2e0\uc758 "))


if __name__ == "__main__":
    unittest.main()
