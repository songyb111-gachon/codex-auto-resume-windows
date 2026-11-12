"""A date or a time inside a right-to-left sentence keeps its order, in the popup and on the card (v0.6.23).

The live acceptance of 2026-11-11 (P3) found the tray popup's usage line in Persian showing the weekly reset as
"21:49 12-11-2026" beside the 5-hour one's "2026-11-12 00:14": the bidi algorithm, inside a right-to-left paragraph,
had turned the value's parts round. Every value the popup and the card put into a sentence - a reset's date and time, a
countdown, a time of day, a version - is now kept one left-to-right run there (l10n.embedded: LRE ... PDF, which GDI's
DrawText and Windows' notifications both honour, as the notices' ids already were), and is itself in a left-to-right
language. Persian and Arabic are held here, and English to show nothing changes there.

The window's own (the design audit's F5): a list cell holding a date with its time - History's Detected and Finished,
the timeline dialog, the advanced Follow, Other PCs and Scheduled rows - and a sentence filled with one are kept one
run too (Mirror.Embed, or S/Word with the value as a token, which embed it). SourceTests scans gui/ and advanced/gui/:
a date written by When or ClockTime anywhere else fails it.

Pure: the popup's view and the notices' content as values, and the window's sources as text; no window.
"""
from __future__ import annotations

from pathlib import Path
import re
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
    return {"interruption_id": "ab" * 32, "thread_id": "12345678-89ab-7cde-8f01-23456789abcd", "state": "waiting_reset",
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
                usage = notify.scheduled_content("12345678-89ab-7cde-8f01-23456789abcd", "ab" * 32, LATER_TODAY)
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


ROOT = Path(__file__).resolve().parents[1]
# A date or a time as the window writes one (gui/DashboardData.cs): "yyyy-MM-dd HH:mm", or "HH:mm" today.
DATED = re.compile(r"\b(When|ClockTime)\(")
# The value of a token, S(key, fallback, "time", value) or Word(...): both embed it (SettingsApp.cs, AdvancedPage.cs).
TOKEN = re.compile(r'"\w+",\s*$')
KEPT = "Mirror.Embed("
ASSIGNED = re.compile(r"^\s*string\s+(\w+)\s*=\s")
# Callers whose parameter goes into a sentence as a token (SettingsPower.cs PowerGraceLine: S(..., "time", time)).
PASSED_ON = ("PowerGraceLine(action, ",)
# ClockTime's own body, a date for any other day.
OWN = (("gui/DashboardData.cs", ": When(stamp);"),)


def bare_dates(root: Path) -> list:
    """Every date or time of When/ClockTime the window's sources put into a cell or a sentence bare: neither in
    Mirror.Embed nor a token's value, nor a variable later passed only as one."""
    found = []
    for path in sorted(list((root / "gui").glob("*.cs")) + list((root / "advanced" / "gui").glob("*.cs"))):
        name = path.relative_to(root).as_posix()
        lines = [line.split("//", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
        held = set()
        for number, line in enumerate(lines, 1):
            if re.search(r"static string (When|ClockTime)\(double", line) or (name, line.strip()) in OWN:
                continue
            for call in DATED.finditer(line):
                before = line[:call.start()]
                if before.rstrip().endswith(KEPT) or TOKEN.search(before) or before.endswith(PASSED_ON):
                    continue
                if not before.strip() and TOKEN.search(next((l for l in reversed(lines[:number - 1]) if l.strip()), "")):
                    continue
                assigned = ASSIGNED.match(before)
                if assigned:
                    held.add(assigned.group(1))
                    continue
                found.append("%s:%d: %s" % (name, number, line.strip()))
        for number, line in enumerate(lines, 1):
            for variable in held:
                if (re.search(r'\.Replace\("\{\w+\}",\s*%s\)' % variable, line)
                        or re.search(r"\+\s*%s\b(?!\s*[(.])" % variable, line) or re.search(r"\b%s\s*\+" % variable, line)):
                    found.append("%s:%d: %s (%s)" % (name, number, line.strip(), variable))
    return found


class SourceTests(unittest.TestCase):
    def test_no_date_goes_bare_into_a_window_cell_or_sentence(self):
        """Fails with any of the design audit's F5 sites reverted: History's Detected and Finished, the timeline
        dialog, Follow, Other PCs, Scheduled, a queued message's series, the reset credits' reading, the early check's
        second reading, the watch log's Last."""
        self.assertEqual(bare_dates(ROOT), [])

    def test_the_scan_sees_a_bare_date(self):
        """The scan itself: a cell and a .Replace of a held value, each written bare, are found."""
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            gui = Path(folder) / "gui"
            gui.mkdir()
            (gui / "Sample.cs").write_text("\n".join([
                'var line = new ListViewItem(When(at));',
                'string time = ClockTime(at);',
                'return Word("k", "{every} at {time}", "every", every).Replace("{time}", time);',
                'string ok = S("k", "at {time}", "time", ClockTime(at)) + Mirror.Embed(When(at));']),
                encoding="utf-8")
            (Path(folder) / "advanced" / "gui").mkdir(parents=True)
            found = bare_dates(Path(folder))
        self.assertEqual([entry.split(":")[1] for entry in found], ["1", "3"], found)


if __name__ == "__main__":
    unittest.main()
