"""#58's follow-up: every surface a record waiting app_server_unmatched reaches says so.

The overlay every header's rule reads, the popup's row and light, the notification-area icon, the command line, the words in
every language, and the panel in its own code. The window's are tests/test_light_parity.py's vectors (its header, its facts
and its taskbar button, compiled) and tests/test_gui_compat.py (its Diagnostics card).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from test_cli import _reset_logging, run_cli  # noqa: E402
from test_mcpui_compat import NODE, page, summary, with_compat  # noqa: E402
from test_mcpui_v063 import run_javascript  # noqa: E402
from codex_auto_resume import l10n, machine  # noqa: E402
from codex_auto_resume.runtime.app import App  # noqa: E402
from codex_auto_resume.ui import popup, tray  # noqa: E402
from codex_auto_resume.ui.popup import model as popup_model  # noqa: E402

ENGLISH = l10n.catalog("en")
NOW = 1_800_000_000.0
RUNNING = {"watcher_running": True, "enabled": True, "watcher": {"running": True, "ticking": True, "engine_state": "verified"},
           "upgrade_pending": False, "pending": 1, "codes": {"waiting_thread": 1}}
OVERLAY = "app_server_unmatched"


class CommandLineTests(unittest.TestCase):
    """`status` and `doctor`, on a stand-in for the engine they find: nothing here reads this PC's processes."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(_reset_logging)
        self.home = str(Path(temp.name) / "home")
        self.exe = Path(temp.name) / "codex.exe"
        self.exe.write_bytes(b"MZ")
        self.look = None
        made = self

        class Stand:
            codex_exe = self.exe
            engine_version = "codex-cli 0.166.0"
            engine_verified = False
            app_look, app_looked_at = None, None

            def app_identity(self):
                self.app_look = made.look
                return None

            def engine_checks(self):
                return {}
        scratch = {"CODEX_HOME": str(Path(temp.name) / "codex-home"), "LOCALAPPDATA": str(Path(temp.name) / "local"),
                   "USERPROFILE": str(Path(temp.name) / "profile")}
        for stub in (patch.object(App, "backend", lambda _self: Stand()), patch.dict(os.environ, scratch),
                     patch("codex_auto_resume.startup.current_value", return_value=None),
                     patch("codex_auto_resume.runtime.app.app_engines", return_value=frozenset())):
            stub.start()
            self.addCleanup(stub.stop)

    def line(self, command):
        _code, out, _err = run_cli("--home", self.home, command)
        return next(text for text in out.splitlines() if text.startswith("ChatGPT app"))

    def test_an_open_app_with_no_server_matched_is_said_as_that(self):
        """The reverse-applied product says "not running" here, beside the open app."""
        self.look = "unmatched"
        for command in ("status", "doctor"):
            with self.subTest(command):
                line = self.line(command)
                self.assertIn("running, but its Codex server could not be matched", line)
                self.assertNotIn("not running", line)

    def test_any_other_look_says_what_it_always_said(self):
        for look in ("closed", None):
            self.look = look
            self.assertIn("not running / not paired", self.line("status"))
            self.assertIn("not running or not paired with the configured engine", self.line("doctor"))


class OverlayTests(unittest.TestCase):
    RECORD = {"state": "waiting_for_app", "last_error": OVERLAY}

    def test_a_record_waiting_for_it_carries_it(self):
        self.assertEqual(machine.overlays(self.RECORD), [OVERLAY])
        self.assertEqual(machine.overlays(dict(self.RECORD, last_error="desktop_app_unavailable")), [])

    def test_only_while_the_watcher_would_act_on_it(self):
        self.assertEqual(machine.overlays(self.RECORD, enabled=False), ["paused"])
        self.assertEqual(machine.overlays(self.RECORD, thread_enabled=False), ["thread_disabled"])
        self.assertEqual(machine.overlays(dict(self.RECORD, hold="ask")), ["held"])
        self.assertEqual(machine.overlays(dict(self.RECORD, state="turn_started")), [])


class PopupTests(unittest.TestCase):
    def row(self, *overlays):
        return {"state": "waiting_for_app", "code": "waiting_thread", "category": "usage_limit", "eligible_at": NOW + 60,
                "overlays": list(overlays) or [OVERLAY], "reason": OVERLAY, "interruption_id": "k", "thread_id": "t"}

    def test_the_header_asks_for_a_person_with_the_amber_light(self):
        """The reverse-applied product says Waiting in cyan, as if the watcher were about to act."""
        rows = [self.row()]
        self.assertEqual(popup.activity(RUNNING, rows, NOW), "attention")
        self.assertEqual(popup.light_for(RUNNING, "attention", rows), "attention")
        self.assertTrue(popup_model.icon_attention(RUNNING, rows))

    def test_a_stopped_watcher_keeps_its_grey(self):
        rows = [self.row(OVERLAY, "engine_unavailable")]
        self.assertEqual(popup.light_for(RUNNING, "attention", rows), "idle")

    def test_the_row_says_what_it_waits_for_instead_of_a_countdown(self):
        item = popup.task_item(self.row(), ENGLISH, NOW)
        self.assertEqual(item["status"], ENGLISH["overlay." + OVERLAY])
        self.assertEqual(item["tone"], "warning")
        self.assertFalse(item["at_zero"])


class IconTests(unittest.TestCase):
    class Store:
        def __init__(self, *rows, disabled=()):
            self.rows, self.disabled = rows, disabled

        def pending(self):
            return list(self.rows)

        def settings(self):
            return {"enabled": True}

        def failure_marks(self):
            return {"failed_at": None, "started_at": None, "unconfirmed_at": None}

        def disabled_threads(self):
            return set(self.disabled)

    RECORD = {"state": "waiting_for_app", "last_error": OVERLAY, "hold": None, "thread_id": "t", "next_retry_at": NOW + 60,
              "reset_at": None, "not_before": None}

    def test_the_icon_asks_for_attention_as_the_headers_do(self):
        snapshot = tray.snapshot_from(self.Store(self.RECORD), NOW)
        self.assertEqual(snapshot["unmatched"], 1)
        self.assertEqual(popup.snapshot_activity(snapshot, NOW), "attention")
        self.assertEqual(tray.icon_state(snapshot), "attention")

    def test_under_a_pause_and_for_a_conversation_switched_off_it_does_not(self):
        snapshot = tray.snapshot_from(self.Store(self.RECORD), NOW)
        self.assertEqual(popup.snapshot_activity(dict(snapshot, enabled=False), NOW), "paused")
        off = tray.snapshot_from(self.Store(self.RECORD, disabled=("t",)), NOW)
        self.assertEqual(off["unmatched"], 0)
        self.assertEqual(popup.snapshot_activity(off, NOW), "waiting")

    def test_any_other_waiting_record_is_as_it_was(self):
        snapshot = tray.snapshot_from(self.Store(dict(self.RECORD, last_error="desktop_app_unavailable")), NOW)
        self.assertEqual((snapshot["unmatched"], popup.snapshot_activity(snapshot, NOW)), (0, "waiting"))


class CatalogTests(unittest.TestCase):
    KEYS = ("overlay." + OVERLAY, "compat.server", "compat.server.matched", "compat.server.not_matched",
            "compat.server.not_checked", "compat.server.notice")

    def test_every_language_says_each_of_them_its_own_way(self):
        for locale in l10n.LOCALES:
            words = l10n.catalog(locale)
            for key in self.KEYS:
                self.assertTrue(words[key].strip(), (locale, key))
            answers = [words["compat.server." + name] for name in ("matched", "not_matched", "not_checked")]
            self.assertEqual(len(set(answers)), 3, locale)
            if locale != l10n.DEFAULT:
                self.assertNotEqual(words["compat.server.notice"], ENGLISH["compat.server.notice"], locale)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelCardTests(unittest.TestCase):
    ROW = {"interruption_id": "a" * 64, "thread_id": "0a1b2c3d-0001-7000-8000-000000000001", "state": "waiting_for_app",
           "code": "waiting_thread", "category": "usage_limit", "eligible_at": None, "overlays": [OVERLAY]}

    def seen(self, *rows, **made):
        data = with_compat(summary(**made))
        data["pending"] = list(rows)
        return page(data)

    def test_a_task_waiting_for_it_is_said_as_a_callout_above_the_parts_that_read_as_compatible(self):
        """The reverse-applied panel says Compatible and nothing else."""
        seen = self.seen(self.ROW)
        self.assertEqual(seen["callout"], [ENGLISH["compat.server.notice"]])
        self.assertEqual(seen["chip"], ENGLISH["compat.state.COMPATIBLE"], "the registry's word stays what it is")

    def test_nothing_is_said_without_one(self):
        self.assertEqual(self.seen()["callout"], [])
        self.assertEqual(self.seen(dict(self.ROW, overlays=["paused"]))["callout"], [])

    def test_a_view_that_cannot_be_used_says_only_why(self):
        self.assertNotIn(ENGLISH["compat.server.notice"], self.seen(self.ROW, status="stale")["callout"])


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelHeaderTests(unittest.TestCase):
    def test_the_header_names_the_cause_and_never_says_the_watcher_is_not_responding(self):
        rows = [{"state": "waiting_for_app", "code": "waiting_thread", "eligible_at": NOW + 60, "overlays": [OVERLAY]}]
        word, light, cause, facts, chip = run_javascript(
            ["t", "fill", "activity", "due", "checkingRow", "attentionCause", "lightFor", "clockTime", "stoppedFact",
             "heroFacts", "tone"], """
          S = %s;
          var now = %s, status = %s, rows = %s;
          var word = activity(status, rows, now, now);
          process.stdout.write(JSON.stringify([word, lightFor(status, word, rows), attentionCause(status, rows),
                                               heroFacts(status, word, rows), tone('app_server_unmatched')]));
        """ % (json.dumps(ENGLISH), json.dumps(NOW), json.dumps(RUNNING), json.dumps(rows)))
        self.assertEqual((word, light, cause), ("attention", "attention", OVERLAY))
        self.assertEqual(facts[0], ENGLISH["overlay." + OVERLAY])
        self.assertEqual(chip, "warning")


if __name__ == "__main__":
    unittest.main()
