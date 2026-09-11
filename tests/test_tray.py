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

from codex_auto_resume import interface, tray
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
        self.assertEqual(snapshot, {"enabled": True, "waiting": 1, "running": 0, "next_at": 500.0})


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
