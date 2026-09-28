"""The popup and the notification card hold their longest words in every language at every scale (v0.6.11).

The window has its layout audit, which builds every page in every language at five scalings and reports
whatever is cut. The popup and the card are drawn by GDI into a card of fixed width, and their own tests
each lay out a view or two; eighteen catalogs later, a sentence that only one language makes long enough
to cut would pass them. Here each of their slots is filled with every string that can stand in it - every
state, every status of a task, both labels of the toggle, both notices, every note, a usage line of two
windows, every notification with every reason - measured by GDI in the fonts each language is drawn in, at
every scale from 100% to 300% (a display's scaling, or Windows' text size on top of it), in all eighteen
catalogs: the two held right-to-left ones too, mirrored as they would be drawn.

What counts as cut is each surface's own rule: a line on its own that is wider than its place (only a
conversation's name and a reason's chip may end in an ellipsis), a word wider than the column it wraps in
(GDI would break it in two), and wrapped lines taller than the room they were given.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import l10n, notice_card, notify, reasons  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.words import WEEK_MINUTES, usage_line  # noqa: E402

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 3.0)
# Only these end in an ellipsis rather than wrap (popup.layout, notice_card.layout).
MAY_END_SHORT = frozenset({"name", "chip"})
NOW = 1_790_000_000.0
LONGEST_TIME = "23:59:59"
LONG_NAME = "A conversation whose name is far longer than any card is wide, and then some more"


def cut(plan, measure, where=""):
    """Every place a plan cuts its words, as one line each: the surfaces' own rules (module docstring)."""
    found = []
    card = plan["card"]
    for item in plan["items"]:
        rect = item.get("rect")
        if rect is not None and item["kind"] != "card" and item["kind"] != "focusable":
            if rect[0] < card[0] or rect[2] > card[2] or rect[1] < card[1] or rect[3] > card[3]:
                found.append("%s%s leaves the card: %r" % (where, item["kind"], item.get("text", "")))
        if item["kind"] != "text":
            continue
        left, top, right, bottom = item["rect"]
        width, height, role, text = right - left, bottom - top, item["role"], item["text"]
        if not item["wrap"]:
            if role not in MAY_END_SHORT and measure(role, text, width, False)[0] > width:
                found.append("%s%s is wider than its place (%d px): %r" % (where, role, width, text))
            continue
        for piece in popup.unbroken(text):
            if measure(role, piece, 100000, False)[0] > width:
                found.append("%s%s has a word wider than its column (%d px): %r in %r" % (where, role, width, piece,
                                                                                          text))
        if measure(role, text, width, True)[1] > height:
            found.append("%s%s is taller than its room: %r" % (where, role, text))
    return found


def popup_views(strings):
    """Views whose every slot holds, across them, every string that can stand in it."""
    say = lambda key, **fields: popup.say(strings, key, **fields)  # noqa: E731
    statuses = [say("activity.recovering"), say("activity.waiting"), say("popup.held")]
    statuses += [say(key, time=LONGEST_TIME) for key in ("popup.until_reset", "popup.until_retry", "popup.offline")]
    chips = [say(reasons.label_key(category)) for category in reasons.ALL]
    reading = {"read_at": NOW - 7200, "windows": [
        {"window_minutes": 300, "used_percent": 100, "reset_at": NOW + 3600},
        {"window_minutes": WEEK_MINUTES, "used_percent": 99.6,
         "reset_at": NOW + 5 * 86400}]}
    notes = {"zero_note": say("popup.zero_note"), "observe_note": say("popup.observe_only"),
             "usage_note": usage_line(reading, say, NOW)}
    notices = [say("popup.stale"), say("action.failed")]
    views = []
    for index, state in enumerate(popup.STATES):
        for paused in (index % 2 == 1,):                    # both labels of the toggle, across the states
            tasks = []
            for row in range(3):
                status = statuses[(index * 3 + row) % len(statuses)]
                tasks.append({"interruption_id": "%02d" % row, "thread_id": "t%d" % row,
                              "name": LONG_NAME, "reason": chips[(index * 3 + row) % len(chips)],
                              "tone": "waiting", "status": status, "check_label": say("pending.col_resume"),
                              "checked": row % 2 == 0, "busy": False, "at_zero": True})
            views.append(dict(notes, **{
                "title": say("tray.title"), "state": state, "light": state if state != "attention" else "idle",
                "state_text": say("activity." + state),
                "counts": [(say("popup.count_waiting"), "88"), (say("popup.count_recovering"), "88"),
                           (say("popup.next_check"), LONGEST_TIME)],
                "tasks": tasks, "more": say("popup.more", n=97),
                "empty": say("popup.nothing"), "error": say("pending.unavailable") if paused else None,
                "notice": notices[index % 2], "paused": paused,
                "toggle_text": say("action.resume" if paused else "action.pause"), "toggle_busy": False,
                "dashboard_text": say("popup.open_dashboard")}))
    return views


def every_language():
    """All eighteen catalogs, the two held ones as though offered, so each is built in its own words."""
    return (patch.object(l10n, "OFFERED", l10n.LOCALES),
            patch.object(l10n, "CHOICES", (l10n.SYSTEM,) + l10n.LOCALES))


@unittest.skipUnless(os.name == "nt", "measured by GDI in the fonts each language is drawn in")
class PopupWordsFitTests(unittest.TestCase):
    def setUp(self):
        self.renderer = popup.Renderer()
        self.addCleanup(self.renderer.close)

    def test_every_string_of_every_slot_fits_in_every_language_at_every_scale(self):
        problems = []
        for locale in l10n.LOCALES:
            views = popup_views(l10n.catalog(locale))
            for scale in SCALES:
                for number, vm in enumerate(views):
                    plan = self.renderer.layout(vm, scale, locale)
                    problems += cut(plan, self.renderer.measure, "%s %.2f #%d " % (locale, scale, number))
        self.assertEqual(problems, [])

    def test_the_check_finds_a_line_too_wide_a_word_cut_and_a_short_room(self):
        """So a quiet report is the check having looked."""
        vm = popup_views(l10n.catalog("en"))[0]
        vm["toggle_text"] = "Pause" * 40
        vm["notice"] = "W" * 200
        plan = self.renderer.layout(vm, 1.0, "en")
        text = next(item for item in plan["items"] if item["kind"] == "text" and item["role"] == "state")
        text["rect"] = (text["rect"][0], text["rect"][1], text["rect"][2], text["rect"][1] + 1)
        found = cut(plan, self.renderer.measure)
        self.assertTrue(any("button" in line and "wider" in line or "button" in line and "word" in line
                            for line in found), found)
        self.assertTrue(any("small has a word wider" in line for line in found), found)
        self.assertTrue(any("state is taller" in line for line in found), found)


@unittest.skipUnless(os.name == "nt", "measured by GDI in the fonts each language is drawn in")
class CardWordsFitTests(unittest.TestCase):
    IDENTITY = {"name": LONG_NAME, "project": "a-project-with-rather-a-long-name", "cwd_basename": "a-repo"}

    def notices(self, locale):
        from test_notice_card import EVENTS, THREAD, INTERRUPTION, in_locale
        from codex_auto_resume import notifier
        with in_locale(locale):
            for event, detail, _identity in EVENTS:
                yield notifier.build(event, dict(detail, thread_id=THREAD), self.IDENTITY)
            # Every reason's chip, and every hold's sentence (notify.HELD_MESSAGES).
            for category, hold in ([(category, None) for category in reasons.ALL]
                                   + [("usage_limit", hold) for hold in notify.HELD_MESSAGES]):
                detail = {"thread_id": THREAD, "interruption_id": INTERRUPTION, "reset_at": NOW + 3600,
                          "category": category, "hold": hold}
                yield notifier.build("interruption", detail, self.IDENTITY)

    def test_every_notice_fits_in_every_language_at_every_scale(self):
        renderer = popup.Renderer()
        self.addCleanup(renderer.close)
        problems = []
        first, second = every_language()
        with first, second:
            for locale in l10n.LOCALES:
                notices = [notice for notice in self.notices(locale) if notice is not None]
                self.assertEqual({notice.locale for notice in notices}, {locale})
                for scale in SCALES:
                    renderer.use(locale, scale)
                    for notice in notices:
                        vm = notice_card.view(notice)
                        plan = notice_card.layout(vm, scale, renderer.measure)
                        problems += cut(plan, renderer.measure, "%s %.2f %s " % (locale, scale, notice.kind))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
