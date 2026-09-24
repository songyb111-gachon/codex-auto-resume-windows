"""v0.6.5: the notification card wired into the watcher, and its entrance on a real screen.

The card's core (notifier, notice_card, notice_window, notice_presence) is held by
tests/test_notice_card.py. This file holds the wiring around it:

* the watcher builds one Notice per event and delivers it by one route - the card when the icon's
  thread hosts it and Windows allows it, today's toast otherwise - from the notifications thread;
* the icon's thread hosts the cards (attaching the inbox), lets go of them when the icon goes
  (detaching it, so later notices are toasts), and draws them in the Theme and Reduce motion stored
  now, which the watcher also takes up when it starts and whenever it reloads its settings;
* a card's button reaches the same in-process handler the toast's buttons reach;
* and two things the real-screen check found: a card's life starts once it is drawn, so drawing
  it never eats into its entrance, and its frames are blended at GDI+'s high speed, as the popup's
  are, rather than gamma-corrected at several times the cost.

Nothing here raises a real toast (PowerShell is stubbed), opens a real Dashboard, or puts a card
anywhere a screen shows it.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from codex_auto_resume import (config, l10n, notice_card, notice_presence, notifier, notify,
                               settings)
from codex_auto_resume.ui import popup as tray_popup, tray
from codex_auto_resume.ui.card import win32 as card_win32
from test_notice_card import ALLOWED, EVENTS, FULL, THREAD, build, captured_xml

ROOT = Path(__file__).resolve().parents[1]
OFFSCREEN = {"work": (-24000, -24000, -22000, -22800), "monitor": (-24000, -24000, -22000, -22752),
             "anchor": None, "dpi": 96}
LIGHT = {"theme": "light", "contrast": False, "reduced": False}


def keep_preferences(case):
    """The watcher's process-wide preferences, put back after each test."""
    previous = l10n.preference()
    case.addCleanup(l10n.set_preference, previous)
    case.addCleanup(tray_popup.set_theme, tray_popup.THEME_SYSTEM)
    case.addCleanup(tray_popup.set_reduce_motion, False)


class _Wake:
    def __init__(self):
        self.woken = 0

    def __call__(self):
        self.woken += 1
        return True


# ------------------------------------------------------------------------------ the watcher
class AppWiringTests(unittest.TestCase):
    def setUp(self):
        keep_preferences(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name) / "home"
        self.codex = Path(folder.name) / "codex"
        self.codex.mkdir()
        self.paths = config.Paths(self.home)

    def app(self, stored=None):
        from codex_auto_resume import app
        if stored:
            self.paths.state_dir.mkdir(parents=True, exist_ok=True)
            settings.update(self.paths.settings_file, stored)
        return app.App(self.paths, codex_home=self.codex, enable_logging=False)

    def announce(self, instance, event, detail):
        source = types.SimpleNamespace(identity=lambda thread: FULL)
        announce = instance._notifier(source)
        with patch.object(notifier, "_presence", lambda: dict(ALLOWED)):
            result = []
            raised = captured_xml(lambda: result.append(announce(event, dict(detail, thread_id=THREAD))))
        return result[0], raised

    def test_the_watcher_has_one_inbox_and_nothing_is_attached_until_the_icon_hosts_the_card(self):
        instance = self.app()
        self.assertIsInstance(instance._inbox, notifier.Inbox)
        self.assertFalse(instance._inbox.attached)

    def test_with_the_card_hosted_a_notice_goes_to_the_card_and_raises_no_toast(self):
        instance = self.app()
        wake = _Wake()
        instance._inbox.attach(wake)
        event, detail, _ = EVENTS[0]
        shown, raised = self.announce(instance, event, detail)
        self.assertIs(shown, True)
        self.assertEqual(raised, [], "the card route raises nothing itself; its host ends the notice")
        handed = instance._inbox.take()
        with patch.object(notify, "_local_time", return_value="14:05"):      # as captured_xml has it
            expected = notifier.build(event, dict(detail, thread_id=THREAD), FULL)
        self.assertEqual(handed, [expected])
        self.assertEqual(wake.woken, 1)

    def test_the_setting_off_or_no_icon_is_today_s_toast(self):
        event, detail, _ = EVENTS[0]
        for attached, card in ((True, False), (False, True)):
            with self.subTest(attached=attached, card=card):
                instance = self.app({"notification_card": card})
                if attached:
                    instance._inbox.attach(_Wake())
                shown, raised = self.announce(instance, event, detail)
                self.assertIs(shown, True)
                self.assertEqual(len(raised), 1, "exactly one toast")
                self.assertNotIn("SILENT", raised[0])
                self.assertEqual(instance._inbox.take(), [])

    def test_a_notification_switched_off_is_neither(self):
        instance = self.app({"notifications": False})
        instance._inbox.attach(_Wake())
        event, detail, _ = EVENTS[0]
        shown, raised = self.announce(instance, event, detail)
        self.assertIs(shown, False)
        self.assertEqual(raised, [])
        self.assertEqual(instance._inbox.take(), [])

    def test_the_watcher_takes_up_the_stored_theme_when_it_starts_and_when_it_reloads(self):
        self.app({"theme": "dark", "reduce_motion": True})
        self.assertEqual(tray_popup.theme_setting(), "dark")
        self.assertTrue(tray_popup.reduced_motion())
        instance = self.app({"theme": "light", "reduce_motion": False})
        self.assertEqual(tray_popup.theme_setting(), "light")
        settings.update(self.paths.settings_file, {"theme": "dark"})
        instance._settings_stamp_seen = None
        engine = types.SimpleNamespace(apply_policy=lambda values: None)
        self.assertTrue(instance.refresh_settings(engine))
        self.assertEqual(tray_popup.theme_setting(), "dark")

    @unittest.skipUnless(os.name == "nt", "the icon is a Windows notification-area icon")
    def test_the_icon_is_given_the_inbox_the_button_handler_and_the_ending(self):
        instance = self.app()
        made = {}

        class Recorder:
            def __init__(self, **kwargs):
                made.update(kwargs)

            def start(self):
                return True

        with patch.object(tray, "Tray", Recorder):
            icon = instance._start_tray(stop=None)
        self.assertIsInstance(icon, Recorder)
        self.assertIs(made["inbox"], instance._inbox)
        self.assertEqual(made["on_notice_action"], instance._notice_action)
        self.assertIs(made["on_notice_complete"], notifier.complete)

    def test_a_card_button_is_the_toast_button_done_in_process(self):
        instance = self.app()
        seen = {}
        with patch.object(notifier, "activate", lambda uri, **kwargs: seen.update(kwargs, uri=uri) or "opened"):
            self.assertEqual(instance._notice_action("codex-auto-resume:open?page=pending"), "opened")
        self.assertEqual(seen["uri"], "codex-auto-resume:open?page=pending")
        self.assertEqual(seen["control"].paths.home, self.paths.home)
        opened = []
        with patch.object(tray, "open_dashboard", lambda home, page=None: opened.append((home, page)) or True):
            self.assertTrue(seen["open_dashboard"]("pending"))
        self.assertEqual(opened, [(self.paths.home, "pending")])
        delivered = []
        with patch.object(notifier, "deliver", lambda notice, **kwargs: delivered.append((notice, kwargs))):
            seen["announce"]("a notice")
        self.assertEqual(delivered, [("a notice", {"inbox": instance._inbox, "setting": True})])
        self.assertEqual(seen["log"], instance.logger.info, "what a press did goes to the watcher's log")

    def test_a_card_button_leaves_its_line_in_the_watcher_s_log(self):
        """End to end through the real notifier.activate: a press that does nothing still says so."""
        instance = self.app()
        lines = []
        with patch.object(instance, "logger", types.SimpleNamespace(info=lines.append)):
            self.assertEqual(instance._notice_action("codex-auto-resume:cancel?i=zz"), "ignored")
            with patch.object(tray, "open_dashboard", lambda home, page=None: False):
                self.assertEqual(instance._notice_action(notify.open_uri("pending")), "not_installed")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(all("notification card" in line for line in lines), lines)


# --------------------------------------------------------------------------------- the icon
@unittest.skipUnless(os.name == "nt", "the icon is a Windows notification-area icon")
class IconHostTests(unittest.TestCase):
    def setUp(self):
        keep_preferences(self)

    def test_an_icon_with_an_inbox_hosts_the_cards_and_lets_go_when_it_goes(self):
        inbox = notifier.Inbox()
        icon = tray.Tray(icon_path=ROOT / "assets" / "codex-auto-resume.ico", strings={}, inbox=inbox,
                         on_notice_action=lambda uri: None, on_notice_complete=lambda notice, shown: None)
        self.assertTrue(icon.start())
        try:
            self.assertIsNotNone(icon._cards)
            self.assertTrue(inbox.attached)
            self.assertIs(icon._cards.inbox, inbox)
        finally:
            icon.stop()
        self.assertFalse(icon._thread.is_alive())
        self.assertIsNone(icon._cards)
        self.assertFalse(inbox.attached, "a notice after the icon has gone is today's toast")
        self.assertFalse(inbox.post("anything"))

    def test_an_icon_without_an_inbox_hosts_nothing(self):
        icon = tray.Tray(strings={})
        self.assertTrue(icon.start())
        try:
            self.assertIsNone(icon._cards)
        finally:
            icon.stop()

    def test_a_stack_that_cannot_be_made_costs_the_card_only(self):
        from codex_auto_resume import notice_window

        class Broken:
            def __init__(self, **kwargs):
                pass

            def create(self):
                raise OSError("RegisterClassW")

        logged, inbox = [], notifier.Inbox()
        with patch.object(notice_window, "CardStack", Broken):
            icon = tray.Tray(strings={}, inbox=inbox, log=logged.append)
            self.assertTrue(icon.start(), "the icon still starts")
        try:
            self.assertIsNone(icon._cards)
            self.assertFalse(inbox.attached)
            self.assertIn("notification card unavailable (OSError)", logged)
        finally:
            icon.stop()

    def test_a_card_is_drawn_in_the_theme_and_motion_stored_now(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        stored = Path(folder.name) / "settings.json"
        settings.update(stored, {"theme": "dark", "reduce_motion": True})
        control = types.SimpleNamespace(get_settings=lambda: settings.load(stored), settings_path=lambda: stored)
        icon = tray.Tray(strings={}, control=control)
        # Windows' own animation switch answers "on" here, as on a desktop (GitHub's runner has it off); the
        # stored Reduce motion is what this test is about.
        with patch.object(tray_popup, "apps_use_light_theme", lambda: True), \
                patch.object(tray_popup, "high_contrast", lambda: False), \
                patch.object(tray_popup, "reduced_motion", lambda: bool(tray_popup.theme._reduce_motion_setting)), \
                patch.object(notice_presence, "battery_saver", lambda: False):
            look = icon._card_look()
            self.assertEqual(look, {"theme": "dark", "contrast": False, "reduced": True})
            settings.update(stored, {"theme": "light", "reduce_motion": False})
            os.utime(stored, ns=(time.time_ns(), time.time_ns() + 10_000_000))
            self.assertEqual(icon._card_look(), {"theme": "light", "contrast": False, "reduced": False})


# ------------------------------------------------------------------------- the entrance
class EntranceTests(unittest.TestCase):
    def test_restarting_begins_the_life_at_the_moment_given(self):
        motion = notice_card.CardMotion(0.0)
        motion.restart(500.0)
        self.assertEqual(motion.frame(500.0).alpha, 0.0, "the entrance starts from nothing")
        self.assertEqual(motion.frame(500.0 + notice_card.ENTRANCE_MS), notice_card.SETTLED)
        reduced = notice_card.CardMotion(0.0, reduced=True, hold_ms=1000)
        reduced.restart(500.0)
        self.assertEqual(reduced.frame(500.0), notice_card.SETTLED)
        self.assertEqual(reduced.frame(1499.0), notice_card.SETTLED)
        self.assertFalse(reduced.gone)
        reduced.frame(1500.0)
        self.assertTrue(reduced.gone, "a reduced card holds its whole time from the restart")
        retired = notice_card.CardMotion(0.0)
        retired.retire(10.0)
        retired.restart(20.0)
        self.assertEqual(retired.phase, "exit", "a card already leaving is not brought back")

    @unittest.skipUnless(os.name == "nt", "the card is a Windows window")
    def test_a_card_s_entrance_starts_once_it_is_drawn(self):
        """Drawing a card takes tens of milliseconds at 200%. Started before that, the first frame
        anybody saw was already partway in; now the first frame shown is the entrance's first."""
        from codex_auto_resume import notice_window
        moments = iter([0.0] + [650.0] * 50)
        ended = []
        stack = notice_window.CardStack(clock=lambda: next(moments), locate=lambda: dict(OFFSCREEN),
                                        appearance=lambda: dict(LIGHT), on_complete=lambda n, s: ended.append(s),
                                        worker=lambda target, *args: target(*args)).create()
        try:
            card = stack.show(build(*EVENTS[0][:2]))
            self.assertIsNotNone(card)
            self.assertEqual(card.motion.since, 650.0)
            self.assertEqual(card.motion.phase, "enter")
            self.assertFalse(card.seen)
            self.assertEqual(card._pushed[2], 0.0, "the first frame on screen is the first of the entrance")
        finally:
            stack.destroy()

    def test_frames_are_blended_at_speed_as_the_popup_s_are(self):
        """GDI+'s high-quality compositing is gamma-corrected: at 200% it made a frame of the card
        cost several times what it does now. The surface asks for the high-speed blend."""
        from codex_auto_resume import notice_window
        calls = []

        class Recorder:
            def __getattr__(self, name):
                def record(*args):
                    calls.append((name, args))
                    return 0
                return record

        layer = types.SimpleNamespace(width=4, height=4, bits=ctypes.c_void_p(0))
        # The handle cache every part of the card looks up in ui/card/win32.py, since
        # v0.6.10-alpha: on the notice_window front the patch reached nothing, and the real
        # GDI+ ran instead of the recorder.
        with patch.object(card_win32, "_dll", lambda name: Recorder()):
            with notice_window._Surface(layer):
                pass
        quality = [args[-1] for name, args in calls if name == "GdipSetCompositingQuality"]
        self.assertEqual(quality, [notice_window.COMPOSITING_HIGH_SPEED])
        self.assertEqual(notice_window.COMPOSITING_HIGH_SPEED, 1)


if __name__ == "__main__":
    unittest.main()
