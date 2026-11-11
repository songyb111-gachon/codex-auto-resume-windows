"""A date or a time inside a right-to-left sentence keeps its order, in the popup and on the card (v0.6.23).

The live acceptance of 2026-11-11 (P3) found the tray popup's usage line in Persian showing the weekly reset as
"21:49 12-11-2026" beside the 5-hour one's "2026-11-12 00:14": the bidi algorithm, inside a right-to-left paragraph,
had turned the value's parts round. Every value the popup and the card put into a sentence - a reset's date and time, a
countdown, a time of day, a version - is now kept one left-to-right run there (l10n.embedded: LRE ... PDF, which GDI's
DrawText and Windows' notifications both honour, as the notices' ids already were), and is itself in a left-to-right
language. Persian and Arabic are held here, and English to show nothing changes there.

Pure: the popup's view and the notices' content as values, no window.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n, notify  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import model as popup_model  # noqa: E402

LRE, PDF = "‪", "‬"
NOW = time.mktime((2026, 11, 11, 21, 0, 0, 0, 0, -1))
LATER_TODAY = NOW + 2 * 3600 + 14 * 60
NEXT_WEEK = NOW + 6 * 86400 + 49 * 60
RIGHT_TO_LEFT = ("fa", "ar")


def kept(value):
    return LRE + value + PDF


def reading():
    return {"read_at": NOW - 15 * 60, "windows": [
        {"window_minutes": 300, "used_percent": 76, "reset_at": LATER_TODAY},
        {"window_minutes": 7 * 24 * 60, "used_percent": 100, "reset_at": NEXT_WEEK}]}


def status():
    return {"enabled": True, "watcher": {"usage": reading()}, "settings": {}}


def waiting_row():
    return {"interruption_id": "ab" * 32, "thread_id": "01234567-89ab-7cde-8f01-23456789abcd", "state": "waiting_reset",
            "code": "waiting_reset", "category": "network_transient", "eligible_at": NOW + 3725, "overlays": [],
            "thread_enabled": True, "hold": None, "tier": None}


def clock(at):
    return time.strftime("%H:%M" if time.localtime(at)[:3] == time.localtime(NOW)[:3] else "%Y-%m-%d %H:%M",
                         time.localtime(at))


class PopupTests(unittest.TestCase):
    def view(self, locale):
        return popup_model.view_model([waiting_row()], status(), l10n.catalog(locale), NOW)

    def test_the_usage_lines_reset_dates_and_times_are_kept_in_a_right_to_left_sentence(self):
        """Fails with the isolate reverted: "2026-11-17 21:49" goes into the Persian sentence bare."""
        for locale in RIGHT_TO_LEFT:
            with self.subTest(locale=locale):
                note = self.view(locale)["usage_note"]
                self.assertIn(kept(clock(NEXT_WEEK)), note, "the weekly reset, with its date")
                self.assertIn(kept(clock(LATER_TODAY)), note, "the 5-hour reset")
                self.assertEqual(note.count(LRE), note.count(PDF))

    def test_a_tasks_countdown_is_kept_too(self):
        for locale in RIGHT_TO_LEFT:
            with self.subTest(locale=locale):
                status_line = self.view(locale)["tasks"][0]["status"]
                self.assertIn(kept("1:02:05"), status_line)

    def test_a_left_to_right_language_is_as_it_was(self):
        view = self.view("en")
        self.assertNotIn(LRE, view["usage_note"])
        self.assertIn(clock(NEXT_WEEK), view["usage_note"])
        self.assertEqual(view["tasks"][0]["status"], "Next check · 1:02:05")
        self.assertEqual(popup.task_item(waiting_row(), l10n.catalog("en"), NOW)["status"], "Next check · 1:02:05")


class NoticeTests(unittest.TestCase):
    """The notices, which the card draws (notice_card.view) as Windows' notifications show them."""

    def setUp(self):
        self.addCleanup(l10n.set_preference, l10n.preference())

    def test_times_and_a_version_are_kept_in_a_right_to_left_notice(self):
        """Fails with the isolate reverted: the times and the version go into the sentence bare."""
        for locale in RIGHT_TO_LEFT:
            with self.subTest(locale=locale):
                l10n.set_preference(locale)
                at = time.strftime("%H:%M", time.localtime(LATER_TODAY))
                self.assertIn(kept(at), notify.objection_message(LATER_TODAY))
                usage = notify.scheduled_content("01234567-89ab-7cde-8f01-23456789abcd", "ab" * 32, LATER_TODAY)
                self.assertIn(kept(at), " ".join(usage.get("extra") or []))
                near = notify.near_limit_content(300, 76, int(LATER_TODAY))
                self.assertIn(kept(at), near["body"])
                offered = notify.update_offered_content("0.6.24-beta.2", prerelease=True)
                self.assertIn(kept("0.6.24-beta.2"), offered["body"])

    def test_in_english_nothing_is_added(self):
        l10n.set_preference("en")
        at = time.strftime("%H:%M", time.localtime(LATER_TODAY))
        self.assertNotIn(LRE, notify.objection_message(LATER_TODAY))
        self.assertIn(at, notify.objection_message(LATER_TODAY))
        self.assertNotIn(LRE, notify.update_offered_content("0.6.24", prerelease=False)["body"])


if __name__ == "__main__":
    unittest.main()
