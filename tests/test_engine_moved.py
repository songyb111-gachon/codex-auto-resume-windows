"""v0.6.13: the watcher looks for Codex's engine again when an update moves or replaces it.

It found codex.exe once, when it built its backend, and never again. On 2026-10-07 the Codex app
(26.930) restarted into a new bin/<hex> folder and emptied the old one; the watcher kept pairing
the app with a server at the old path, and every recovery waited, "ChatGPT app or its Codex
server not running", until the watcher was restarted.

A module of its own: test_compat_characterization.py, whose fixture these use, must stay the
file v0.6.10 had (tests/test_released_calls.py replays its scenarios against v0.6.10).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_compat_characterization import FakeCodex, Fixture  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.runtime import loop  # noqa: E402


class EngineMovedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        self.first = self.fixture.app.backend()

    def versions_asked(self):
        return self.fixture.codex.calls.count(("--version",))

    def test_the_same_file_is_not_looked_for_again(self):
        asked = self.versions_asked()
        self.assertFalse(self.fixture.app.engine_moved())
        self.assertIs(self.fixture.app.backend(), self.first)
        self.assertEqual(self.versions_asked(), asked)

    def test_an_engine_moved_to_another_folder_is_found_there(self):
        moved = self.fixture.exe.parent.parent / "fedcba9876543210" / "codex.exe"
        moved.parent.mkdir()
        moved.write_bytes(b"MZ-second-build")
        self.fixture.exe.unlink()
        self.assertTrue(self.fixture.app.engine_moved())
        self.assertEqual(self.fixture.app.backend().codex_exe, moved.resolve())

    def test_another_file_at_the_same_path_is_checked_again(self):
        asked = self.versions_asked()
        self.fixture.exe.write_bytes(b"MZ-a-longer-second-build")
        self.assertTrue(self.fixture.app.engine_moved())
        self.assertIsNot(self.fixture.app.backend(), self.first)
        self.assertGreater(self.versions_asked(), asked)

    def test_an_engine_gone_with_none_in_its_place_is_refused_not_kept(self):
        self.fixture.exe.unlink()
        self.assertTrue(self.fixture.app.engine_moved())
        with self.assertRaises(config.ConfigError):
            self.fixture.app.backend()

    def test_the_watcher_asks_before_every_tick_but_its_first(self):
        source = Path(loop.__file__).read_text(encoding="utf-8")
        self.assertIn("if engine is not None and self.engine_moved():\n"
                      "                        engine = None\n"
                      "                    if engine is None:", source)


if __name__ == "__main__":
    unittest.main()
