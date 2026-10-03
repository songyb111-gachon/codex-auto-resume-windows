"""The watcher's notification-area icon.

It shows what the last tick found and counts down locally; it never decides anything.
The pure parts - the wording and the countdown - are tested everywhere, and the real
icon is started and stopped on Windows, where a leaked window or thread would show.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest

from codex_auto_resume import interface
from codex_auto_resume.ui import tray
from codex_auto_resume.store import Store

ROOT = Path(__file__).resolve().parents[1]
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"


class WordingTests(unittest.TestCase):
    def test_the_countdown_is_short_and_never_negative(self):
        self.assertEqual(tray.countdown(45), "45s")
        self.assertEqual(tray.countdown(65), "1:05")
        self.assertEqual(tray.countdown(3725), "1:02:05")
        self.assertEqual(tray.countdown(-10), "0s")

    def test_paused_says_paused_and_nothing_else(self):
        text = tray.tooltip({"enabled": False, "waiting": 3, "next_at": 2000}, interface.STRINGS["en"], 1000)
        self.assertEqual(text, "Codex Auto Resume\nPaused")

    def test_waiting_work_shows_the_next_check(self):
        text = tray.tooltip({"enabled": True, "waiting": 2, "running": 1, "next_at": 1754},
                            interface.STRINGS["en"], 1000)
        self.assertIn("1 running in Codex", text)
        self.assertIn("2 waiting", text)
        self.assertIn("next check in 12:34", text)

    def test_every_language_fits_the_tooltip_limit(self):
        for language, strings in interface.STRINGS.items():
            with self.subTest(language=language):
                text = tray.tooltip({"enabled": True, "waiting": 99, "running": 99,
                                     "next_at": 10 ** 6}, strings, 0)
                self.assertLess(len(text), tray.TIP_CHARS)
                for key in ("tray.title", "tray.paused", "tray.idle", "tray.waiting", "tray.running",
                            "tray.next", "menu.open", "menu.pause", "menu.resume", "menu.stop"):
                    self.assertTrue(strings.get(key), key)


class SnapshotTests(unittest.TestCase):
    def test_the_snapshot_comes_from_our_own_store_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            with Store(Path(temporary)) as store:
                store.set_enabled(True, 100.0)
                store.register({"thread_id": THREAD, "turn_id": "0a1b2c3d-0002-7000-8000-000000000002",
                                "completed_at": 110.0, "started_at": 105.0, "ordinal": 2,
                                "interruption_id": "a" * 64, "reset_at": 500.0, "limit_type": "x",
                                "uncertain": False}, 100.0, next_retry_at=300.0)
                snapshot = tray.snapshot_from(store, 200.0)
        # The next check is the later of the schedule and the usage reset.
        # Since v0.6.8 it also carries when the newest certain failure was, and the newest claim: none here.
        self.assertEqual(snapshot, {"enabled": True, "waiting": 1, "running": 0, "next_at": 500.0,
                                    "failures": {"failed_at": None, "started_at": None}})


class _Menu:
    """Just enough of user32 for the menu to be built without being shown, choosing `chosen`."""

    def __init__(self, chosen=0):
        self.items, self.chosen = [], chosen

    def CreatePopupMenu(self):
        return 1

    def AppendMenuW(self, menu, flags, identifier, text):
        self.items.append((identifier, text))

    def GetCursorPos(self, point):
        return 1

    def SetForegroundWindow(self, hwnd):
        return 1

    def TrackPopupMenu(self, *unused):
        return self.chosen

    def PostMessageW(self, *unused):
        return 1

    def DestroyMenu(self, menu):
        return 1


class PowerMenuTests(unittest.TestCase):
    """v0.6.12: while the power action after usage-limit recoveries is armed - and only then - the menu
    offers to turn it off, right after Pause, in the words of the action armed. It never offers to turn
    it on (H14)."""

    def setUp(self):
        from codex_auto_resume import config, control
        from codex_auto_resume.ui.tray import menu
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(Path(folder.name))
        self.paths.ensure()
        self.control = control.Control(self.paths)
        self.menu = menu
        self.logged = []
        # The menu speaks the stored Interface language (_adopt_settings), whose default follows Windows:
        # English is stored, so the words below are this PC's in no language but the one chosen.
        self.choose_language("en")
        self.icon = tray.Tray(strings=dict(interface.STRINGS["en"]), control=self.control, log=self.logged.append)

    def choose_language(self, language):
        from codex_auto_resume import settings
        settings.save(self.paths.settings_file, dict(settings.defaults(), interface_language=language))

    def arm(self, action):
        import json
        from codex_auto_resume import poweraction
        self.paths.power_action_file.write_text(json.dumps({
            "format": poweraction.FORMAT, "shown": None, "last": None,
            "armed": {"nonce": "0123456789abcdef", "action": action, "after": "any_end", "repeat": "always",
                      "grace_seconds": 300, "armed_at": 1_790_000_000.0, "since": 1_790_000_000.0, "carried": [],
                      "stop_at": None}}), encoding="utf-8")

    def open(self, chosen=0):
        from unittest.mock import patch
        fake = _Menu(chosen)
        with patch.object(self.menu, "_dll", lambda name: fake),                 patch.object(self.menu, "prefer_app_mode", lambda mode: False):
            self.icon._menu()
        return fake.items

    def test_the_item_is_there_only_while_armed(self):
        self.assertNotIn(tray.MENU_POWER_OFF, [identifier for identifier, _ in self.open()])
        english = interface.STRINGS["en"]
        for action in ("sleep", "hibernate", "shut_down"):
            with self.subTest(action=action):
                self.arm(action)
                items = self.open()
                identifiers = [identifier for identifier, _ in items]
                self.assertIn(tray.MENU_POWER_OFF, identifiers)
                self.assertEqual(identifiers.index(tray.MENU_POWER_OFF), identifiers.index(tray.MENU_TOGGLE) + 1)
                self.assertEqual(dict(items)[tray.MENU_POWER_OFF], english["menu.power_off." + action])
                self.assertEqual(self.menu.POWER_OFF_WORDS[action], english["menu.power_off." + action],
                                 "the fallback is the English sentence")
        self.paths.power_action_file.write_text("{not json", encoding="utf-8")
        self.assertNotIn(tray.MENU_POWER_OFF, [identifier for identifier, _ in self.open()],
                         "a file that cannot be believed is off")
        self.assertEqual(self.logged, [])

    def test_the_item_speaks_the_language_stored(self):
        self.choose_language("ko")
        self.icon = tray.Tray(strings=dict(interface.STRINGS["en"]), control=self.control, log=self.logged.append)
        korean = interface.STRINGS["ko"]
        for action in ("sleep", "hibernate", "shut_down"):
            with self.subTest(action=action):
                self.arm(action)
                words = dict(self.open())[tray.MENU_POWER_OFF]
                self.assertEqual(words, korean["menu.power_off." + action])
                self.assertNotEqual(words, interface.STRINGS["en"]["menu.power_off." + action])

    def test_choosing_it_turns_it_off_as_the_icon(self):
        import json
        from unittest.mock import patch
        self.arm("shut_down")
        with patch.object(self.control, "disarm_power_action", wraps=self.control.disarm_power_action) as disarm:
            self.open(chosen=tray.MENU_POWER_OFF)
        disarm.assert_called_once_with(actor="tray")
        self.assertIsNone(json.loads(self.paths.power_action_file.read_text(encoding="utf-8"))["armed"])
        self.assertNotIn(tray.MENU_POWER_OFF, [identifier for identifier, _ in self.open()])

    def test_an_icon_without_a_control_layer_offers_nothing(self):
        self.assertIsNone(tray.Tray(strings={})._power_armed())
        self.assertEqual(tray.MENU_POWER_OFF, 5)
        self.assertEqual(len({tray.MENU_OPEN, tray.MENU_TOGGLE, tray.MENU_STOP, tray.MENU_PENDING,
                              tray.MENU_POWER_OFF}), 5)


@unittest.skipUnless(sys.platform == "win32", "Windows notification area")
class LiveIconTests(unittest.TestCase):
    def test_the_icon_starts_updates_and_goes_away_cleanly(self):
        icon = tray.Tray(icon_path=ROOT / "assets" / "codex-auto-resume.ico",
                         strings=interface.STRINGS["en"])
        self.assertTrue(icon.start())
        try:
            icon.update({"enabled": False})
            deadline = time.monotonic() + 3
            while icon._last_tip != "Codex Auto Resume\nPaused" and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertEqual(icon._last_tip, "Codex Auto Resume\nPaused")
        finally:
            icon.stop()
        self.assertFalse(icon._thread.is_alive(), "the icon's thread ends with the watcher")


if __name__ == "__main__":
    unittest.main()
