"""v0.6.20 (the owner's report of 2026-10-26): every state its matching light, on every surface that shows one.

The map is outputs/plans/v0620-status-light-map.md. This module holds what that audit changed, surface by surface:

* a record waiting for a person (held: its conversation asks first, or only notifies) is "Needs your attention", amber,
  in the popup, the notification-area icon, the card of the sleep notice and the Codex panel - the window's header and
  taskbar button are tests/test_light_parity.py's vectors, and the window's starting watcher is test_gui_busy_light's;
* under a watcher not known to run (the grey of a stopped watcher), and over a pause and every cyan state;
* the icon's red for a failure nobody has seen still outranks it (J14).

Pure Python and the panel's own code in Node: nothing is compiled and nothing is shown.
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_mcpui_v063 import NODE, run_javascript  # noqa: E402

from codex_auto_resume import l10n, notifier  # noqa: E402
from codex_auto_resume.ui import popup, tray  # noqa: E402
from codex_auto_resume.ui.popup import model as popup_model  # noqa: E402

NOW = 1_800_000_000.0
RUNNING = {"watcher_running": True, "enabled": True, "watcher": {"running": True, "ticking": True, "engine_state": "verified"},
           "upgrade_pending": False, "pending": 1, "codes": {"scheduled": 1}}


def row(*overlays, code="scheduled", at=None):
    return {"state": "waiting_backoff" if code == "scheduled" else code, "code": code, "eligible_at": at,
            "overlays": list(overlays)}


class PopupTests(unittest.TestCase):
    def test_a_row_held_for_a_person_asks_for_their_attention(self):
        """Fails with the held rule gone: the word is waiting and the light cyan."""
        rows = [row("held")]
        self.assertEqual(popup.activity(RUNNING, rows, NOW), "attention")
        self.assertEqual(popup.light_for(RUNNING, "attention", rows), "attention")
        view = popup.view_model(rows, RUNNING, l10n.catalog("en"), NOW)
        self.assertEqual((view["state"], view["light"], view["state_text"]), ("attention", "attention", "Needs your attention"))

    def test_it_outranks_a_pause_and_every_cyan_state(self):
        paused = dict(RUNNING, enabled=False)
        self.assertEqual(popup.activity(paused, [row("paused", "held")], NOW), "attention")
        self.assertEqual(popup.activity(RUNNING, [row("held"), row(code="turn_running")], NOW), "attention")
        self.assertEqual(popup.activity(RUNNING, [row("held"), row(code="waiting_reset", at=NOW - 5)], NOW), "attention")

    def test_a_watcher_not_known_to_run_keeps_its_grey_light(self):
        stopped = [row("held", "engine_unavailable")]
        self.assertEqual(popup.activity(RUNNING, stopped, NOW), "attention")
        self.assertEqual(popup.light_for(RUNNING, "attention", stopped), "idle")

    def test_a_row_let_go_is_waiting_again(self):
        self.assertEqual(popup.activity(RUNNING, [row()], NOW), "waiting")

    def test_the_held_overlay_is_kept_apart_from_the_watcher_s_attention_overlays(self):
        """So a held row's tone and the icon's own rule (icon_attention) are what they were."""
        self.assertNotIn(popup_model.HELD_OVERLAY, popup_model.ATTENTION_OVERLAYS)
        self.assertFalse(popup_model.icon_attention(RUNNING, [row("held")]))


class IconTests(unittest.TestCase):
    def snapshot(self, **fields):
        return dict({"enabled": True, "waiting": 1, "running": 0, "held": 0, "next_at": None,
                     "failures": {"failed_at": None, "started_at": None, "unconfirmed_at": None}}, **fields)

    def test_the_icon_asks_for_attention_while_a_record_waits_for_a_person(self):
        self.assertEqual(popup.snapshot_activity(self.snapshot(held=1), NOW), "attention")
        self.assertEqual(tray.icon_state(self.snapshot(held=1)), "attention")

    def test_it_outranks_a_pause_and_a_run_in_codex(self):
        self.assertEqual(tray.icon_state(self.snapshot(held=1, enabled=False)), "attention")
        self.assertEqual(tray.icon_state(self.snapshot(held=1, running=1)), "attention")

    def test_nothing_held_is_as_it_was(self):
        self.assertEqual(tray.icon_state(self.snapshot()), "watching")
        self.assertEqual(tray.icon_state(self.snapshot(enabled=False)), "idle")
        self.assertEqual(tray.icon_state(self.snapshot(running=1)), "recovering")

    def test_the_red_of_a_failure_nobody_has_seen_still_comes_first(self):
        self.assertEqual(tray.icon_state(self.snapshot(held=1), failed=True), "failed")


class CardTests(unittest.TestCase):
    def test_the_sleep_notice_wears_the_attention_light_as_the_needs_you_notice_does(self):
        """What fell due during a long sleep waits for a person (hold `after_sleep`): the same state."""
        self.assertEqual(notifier.NOTICE_STATUS["after_sleep"], "attention")
        self.assertEqual(notifier.NOTICE_STATUS["after_sleep"], notifier.NOTICE_STATUS["needs_you"])


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = [[RUNNING, [row("held")]], [dict(RUNNING, enabled=False), [row("paused", "held")]],
                 [RUNNING, [row("held", "engine_unavailable")]], [RUNNING, [row()]],
                 [dict(RUNNING, upgrade_pending=True), [row("held")]]]
        cls.answers = run_javascript(["t", "fill", "activity", "due", "checkingRow", "attentionCause", "lightFor", "clockTime",
                                      "stoppedFact", "heroFacts"], """
          var now = %s;
          var out = %s.map(function (c) {
            var word = activity(c[0], c[1], now, now);
            return [word, lightFor(c[0], word, c[1]), attentionCause(c[0], c[1]), heroFacts(c[0], word, c[1])];
          });
          process.stdout.write(JSON.stringify(out));
        """ % (json.dumps(NOW), json.dumps(cases)))

    def test_a_held_row_is_attention_with_its_own_cause_and_words(self):
        word, light, cause, facts = self.answers[0]
        self.assertEqual((word, light, cause), ("attention", "attention", "held"))
        self.assertEqual(facts[0], l10n.catalog("en")["popup.held"])
        self.assertNotEqual(facts[0], l10n.catalog("en")["status.not_responding"])

    def test_it_outranks_a_pause(self):
        self.assertEqual(self.answers[1][:2], ["attention", "attention"])

    def test_a_stopped_watcher_keeps_its_grey_light(self):
        self.assertEqual(self.answers[2][:2], ["attention", "idle"])

    def test_the_watcher_s_own_causes_come_before_it(self):
        self.assertEqual(self.answers[4][2], "upgrade_pending")
        self.assertEqual(self.answers[3][:3], ["waiting", "waiting", None])


if __name__ == "__main__":
    unittest.main()
