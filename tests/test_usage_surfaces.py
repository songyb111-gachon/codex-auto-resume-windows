"""Where the icon, the popup and a notice show the advanced edition's usage meter (v0.6.16-beta.3, issue #29), and
that the standard edition shows nothing new anywhere.

The meter is the advanced edition's; what core does is read the one key a plug's fields are put under
(domain/plug.EXTRA) - in the icon's snapshot and in the status - and say what is there in its own words. The standard
edition's plug puts nothing there, so its tooltip, its popup line and its notices are exactly what they were.

    PYTHONPATH=src;tests python -m unittest test_usage_surfaces
"""
from __future__ import annotations

import unittest

from codex_auto_resume import l10n, notifier
from codex_auto_resume.domain.plug import EXTRA, NULL, Surface, guard
from codex_auto_resume.ui.popup import model
from codex_auto_resume.ui.tray import words

NOW = 1_800_000_000
METER = {"read_at": NOW - 60, "notices": [],
         "windows": [{"bucket": "codex", "window_minutes": 300, "used_percent": 87.6, "reset_at": NOW + 3600,
                      "band": "warn"},
                     {"bucket": "codex", "window_minutes": 10080, "used_percent": 40, "reset_at": None,
                      "band": "none"}]}


class KeyTests(unittest.TestCase):
    def test_the_icon_and_the_popup_read_the_one_key_a_plug_adds_under(self):
        self.assertEqual((words.EXTRA, model.EXTRA), (EXTRA, EXTRA))

    def test_the_standard_editions_plug_adds_nothing_to_the_icon_or_the_status(self):
        for surface in (Surface.TRAY, Surface.STATUS):
            self.assertEqual(repr(guard(NULL).surface(surface, {})), "DEFER")


class TooltipTests(unittest.TestCase):
    def test_the_meter_is_one_line_after_what_the_tooltip_said(self):
        tip = words.tooltip({"waiting": 0, EXTRA: {"meter": METER}}, {}, NOW, "advanced")
        self.assertEqual(tip.split("\n")[-1], "5-hour 13% left · weekly 60% left")
        self.assertLess(len(tip), words.TIP_CHARS)

    def test_without_a_meter_the_tooltip_is_what_it_always_was(self):
        for snapshot in ({"waiting": 0}, {"waiting": 0, EXTRA: {"edition": "advanced", "on": 0}},
                         {"waiting": 0, EXTRA: {"meter": "nonsense"}}):
            with self.subTest(snapshot=snapshot):
                self.assertEqual(words.tooltip(snapshot, {}, NOW), "Codex Auto Resume\nNothing waiting")


class PopupTests(unittest.TestCase):
    WATCHER = {"read_at": NOW - 600, "windows": [{"bucket": "codex", "window_minutes": 300, "used_percent": 10,
                                                  "reset_at": NOW + 3600}]}

    def test_the_meters_reading_is_shown_where_it_is_newer(self):
        status = {"watcher": {"usage": self.WATCHER}, EXTRA: {"meter": METER}}
        # v0.6.26 final: in core's own window shape (domain/usage.meter_windows): the slot core names, no band.
        self.assertEqual(model.newest_reading(status), {"read_at": METER["read_at"], "windows": [
            {"bucket": "codex", "window": "primary", "used_percent": 87.6, "window_minutes": 300, "reset_at": NOW + 3600},
            {"bucket": "codex", "window": "secondary", "used_percent": 40, "window_minutes": 10080, "reset_at": None}]})

    def test_the_watchers_own_reading_stays_where_it_is_newer_or_there_is_no_meter(self):
        newer = dict(self.WATCHER, read_at=NOW)
        self.assertIs(model.newest_reading({"watcher": {"usage": newer}, EXTRA: {"meter": METER}}), newer)
        self.assertIs(model.newest_reading({"watcher": {"usage": self.WATCHER}}), self.WATCHER)
        self.assertIsNone(model.newest_reading(None))


class NoticeTests(unittest.TestCase):
    def setUp(self):
        before = l10n.preference()
        l10n.set_preference("en")
        self.addCleanup(l10n.set_preference, before)

    def test_a_near_limit_notice_names_the_window_and_its_share_and_no_conversation(self):
        notice = notifier.build("near_limit", {"minutes": 300, "percent": 87.6, "reset_at": NOW + 3600})
        self.assertEqual((notice.kind, notice.status, notice.key), ("near_limit", "attention", None))
        self.assertIn("5-hour 13% left", notice.origin)
        weekly = notifier.build("near_limit", {"minutes": 10080, "percent": 91})
        self.assertIn("weekly 9% left", weekly.origin)

    def test_a_near_limit_notice_says_what_is_left_at_every_edge(self):
        """v0.6.24 final: the share left - 100 minus the whole share used, 0 at and above 100 - and no number at all
        where the share cannot be read (never a "100% left" nobody read)."""
        for percent, said in ((0, "5-hour 100% left"), (99.6, "5-hour 1% left"), (100, "5-hour 0% left"),
                              (130, "5-hour 0% left")):
            with self.subTest(percent=percent):
                self.assertEqual(notifier.build("near_limit", {"minutes": 300, "percent": percent}).origin.count(said), 1)
        for percent in (None, "lots", float("nan"), True):
            with self.subTest(percent=percent):
                notice = notifier.build("near_limit", {"minutes": 300, "percent": percent})
                self.assertNotIn("%", notice.origin)


class WatcherNoticeTests(unittest.TestCase):
    def test_each_warning_the_plug_adds_is_shown_once_in_a_watchers_life(self):
        from codex_auto_resume.runtime.app import App

        class Watcher:
            def __init__(self):
                self.shown = []

            def _watcher_notice(self, event, detail):
                self.shown.append((event, detail["minutes"]))
        watcher = Watcher()
        added = {"meter": dict(METER, notices=[{"key": "codex:300:1", "window_minutes": 300, "used_percent": 86,
                                                 "reset_at": NOW + 3600}])}
        for _tick in range(3):
            App._near_limit(watcher, added)
        self.assertEqual(watcher.shown, [("near_limit", 300)])
        App._near_limit(watcher, {"edition": "advanced", "on": 1})       # no meter: nothing
        App._near_limit(watcher, "DEFER")
        self.assertEqual(len(watcher.shown), 1)

    def test_the_forced_stops_notices_carry_their_kind_and_say_it_in_their_own_words(self):
        """v0.6.16-beta.4: a notice of the advanced edition's forced stop near a limit - a turn it could not stop, a
        queue to Resume in Codex, a conversation it could not continue - has a title and a sentence of its own."""
        from codex_auto_resume import l10n, notify
        from codex_auto_resume.runtime.app import App

        class Watcher:
            def __init__(self):
                self.shown = []

            def _watcher_notice(self, event, detail):
                self.shown.append((event, detail.get("kind")))
        watcher = Watcher()
        notices = [{"key": "%s:300:1" % kind, "window_minutes": 300, "used_percent": None, "reset_at": None,
                    "kind": kind} for kind in notify.NEAR_LIMIT_KINDS]
        App._near_limit(watcher, {"meter": dict(METER, notices=notices)})
        self.assertEqual(watcher.shown, [("near_limit", kind) for kind in notify.NEAR_LIMIT_KINDS])
        titles = set()
        for kind in notify.NEAR_LIMIT_KINDS:
            content = notify.near_limit_content(300, None, None, kind)
            self.assertIn(l10n.message("toast_near_limit_" + kind), repr(content))
            self.assertIn(l10n.message("near_limit_%s_body" % kind), repr(content))
            titles.add(l10n.message("toast_near_limit_" + kind))
        self.assertEqual(len(titles), 3)
        self.assertIn(l10n.message("toast_near_limit"), repr(notify.near_limit_content(300, 86, None)),
                      "a warning as before")
        # v0.6.16: each is a notice of its own kind, so it can be kept on screen apart from the warning
        # (notice_kinds); a warning, or a kind no one knows, is the warning's.
        for kind in notify.NEAR_LIMIT_KINDS:
            notice = notifier.build("near_limit", {"minutes": 300, "kind": kind})
            self.assertEqual((notice.kind, notice.status, notice.key), ("near_limit_" + kind, "attention", None))
        for kind in (None, "warn", "unheard_of"):
            self.assertEqual(notifier.build("near_limit", {"minutes": 300, "percent": 90, "kind": kind}).kind,
                             "near_limit")


if __name__ == "__main__":
    unittest.main()
